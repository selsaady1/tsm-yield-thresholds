"""run_r01_leadtime.py: multi-period variant with lead times and die-bank inventory (R1.7c).

FE half-range sweep (0.01..0.50 step 0.01, plus the base 0.075), FE mean 0.875
(paper convention with clipping), BE yield 0.70/0.90, demand 600/900 per period.

Configurations (T periods, BE lead time lB, mode, FE lead time lF):
  P1_l0   T=1 lB=0 two     (= paper's model; reference)
  P4_l0   T=4 lB=0 two     (inventory between periods, no lead time)
  P1_l1   T=1 lB=1 two     (BE lead time only)
  P4_l1   T=4 lB=1 two     (main: lead time and inventory; lF irrelevant
                            in the two-stage version)
  P4_l1_m1  T=4 lB=1 multistage lF=1
  P4_l1_m2  T=4 lB=1 multistage lF=2
  P3_l1     T=3 lB=1 two     (for the multistage comparison at T=3)
  P3_l1_m1  T=3 lB=1 multistage lF=1
  P3_l1_m2  T=3 lB=1 multistage lF=2
For multistage configurations the rolling deterministic policy (re-plan with
mean values each period) is also evaluated.

Outputs: sweep.csv (one row per configuration and half-range), summary.csv
(crossings, cliff onset solved and predicted), log.txt, run.json.
Usage: nice -n 10 $PY run_r01_leadtime.py [--smoke]
"""
import sys

from tsmb_common import Run, write_csv, crossing, bisect_first
import revision_common as rc
import tsmb_multiperiod as mp

SMOKE = "--smoke" in sys.argv
run = Run("tsmb_r01_leadtime" + ("_smoke" if SMOKE else ""),
          "R1.7c: multi-period model with FE/BE lead times and die-bank inventory; "
          "two-stage and multistage; VSS, %VSS, service, cliff",
          [__file__, mp.__file__, rc.__file__])
inst = rc.base_inst()
DEM = (inst["demand_lo"], inst["demand_hi"])
BE = (rc.BE_LO, rc.BE_HI)
HALVES = sorted(set(rc.HALF_GRID + [0.075]))
if SMOKE:
    HALVES = [0.075, 0.20, 0.40]
CONFIGS = [("P1_l0", 1, 0, "two", 1), ("P4_l0", 4, 0, "two", 1),
           ("P1_l1", 1, 1, "two", 1), ("P4_l1", 4, 1, "two", 1),
           ("P4_l1_m1", 4, 1, "multi", 1), ("P4_l1_m2", 4, 1, "multi", 2),
           ("P3_l1", 3, 1, "two", 1), ("P3_l1_m1", 3, 1, "multi", 1),
           ("P3_l1_m2", 3, 1, "multi", 2)]
if SMOKE:
    CONFIGS = [c for c in CONFIGS if c[1] <= 3]
N_MAX = rc.max_die_requirement(inst)
L_G = sum(inst["L_G"].values())
n = inst["n_f_i"]
run.log(f"T=1 check deviation {mp.check_T1():.1e}; N_max={N_MAX}; L_G={L_G}; "
        f"{len(CONFIGS)} configurations x {len(HALVES)} half-ranges")


def point(T, lB, mode, lF, h, with_rh):
    fe = rc.two_point(rc.FE_MEAN, h)
    tree = mp.Tree(T, lB, fe, BE, DEM)
    r = mp.evaluate(inst, T, lB, fe, BE, DEM, mode=mode, lF=lF, tree=tree)
    out = {"half": h, "fe_lo": fe[0], "fe_hi": fe[1], "clipped": int(rc.FE_MEAN + h > 1 + 1e-9),
           "ok": r["ok"], "rp_obj": r["rp_obj"], "eev_obj": r["eev_obj"], "vss": r["vss"],
           "pct_vss": r["pct_vss"], "rp_unmet_pp": r["rp_unmet_pp"],
           "eev_unmet_pp": r["eev_unmet_pp"], "unmet_gap_pp": r["unmet_gap_pp"],
           "rp_starts_pp": sum(r["rp"]["starts"].values()) / T,
           "ev_starts_pp": sum(r["ev"]["x"].values()) / T,
           "ev_starts_min_period": min(sum(r["ev"]["x"][(f, a)] for f in inst["FE_set"])
                                       for a in range(1, T + 1)),
           "rp_inv_pp": sum(r["rp"]["exp_inv_by_period"].values()) / T,
           "eev_inv_pp": sum(r["eev"]["exp_inv_by_period"].values()) / T,
           "rp_outs_pp": sum(r["rp"]["exp_outs_by_period"].values()) / T,
           "eev_outs_pp": sum(r["eev"]["exp_outs_by_period"].values()) / T,
           "n_nodes": r["n_nodes"]}
    if mode == "multi":
        two = mp.solve_tree(inst, tree, mode="two", tag="RP2")
        out["rp_two_obj"] = two["obj"]
        out["vms"] = r["rp_obj"] - two["obj"]
        out["ok"] = out["ok"] and two["status"] == "Optimal"
        if with_rh:
            rh = mp.rolling_ev(inst, tree, lF)
            out["rh_obj"] = rh["obj"]
            out["rh_unmet_pp"] = rh["unmet_pp"]
            out["vss_vs_rh"] = r["rp_obj"] - rh["obj"]
            out["pct_vss_vs_rh"] = 100 * (r["rp_obj"] - rh["obj"]) / abs(r["rp_obj"])
    return out


rows, summary = [], []
for (name, T, lB, mode, lF) in CONFIGS:
    crow = []
    for h in HALVES:
        p = point(T, lB, mode, lF, h, with_rh=True)
        p.update({"config": name, "T": T, "lB": lB, "mode": mode, "lF": lF})
        crow.append(p)
        run.progress(f"{name} h={h}")
    bad = [p["half"] for p in crow if not p["ok"]]
    for p in crow:
        p["gap_rise_pp"] = p["unmet_gap_pp"] - crow[0]["unmet_gap_pp"]
    rows += crow
    g0 = crow[0]["unmet_gap_pp"]
    # solved onset: first h with a rise of the per-period gap above its smallest-spread value
    first = next((p["half"] for p in crow if p["gap_rise_pp"] > 1e-6), None)
    if first is None:
        onset = None
    else:
        prev = max([p["half"] for p in crow if p["half"] < first], default=0.0)
        onset = bisect_first(lambda h: point(T, lB, mode, lF, h, False)["unmet_gap_pp"] - g0 > 1e-6,
                             prev, first)

    # prediction: the single-period rule applied per period to the EV plan
    def short(h):
        fe = rc.two_point(rc.FE_MEAN, h)
        ev = mp.ev_plan(inst, T, lB, fe, BE, DEM)
        wmin = min(sum(ev["x"][(f, a)] for f in inst["FE_set"]) for a in range(1, T + 1))
        return n * fe[0] * wmin + L_G < N_MAX - 1e-6
    pred = bisect_first(short, 0.0, 0.50)
    fmt = lambda c: ("below_grid" if c == "below_grid" else ("none" if c is None else f"{c:.4f}"))
    s = {"config": name, "T": T, "lB": lB, "mode": mode, "lF": lF,
         "pct_vss_at_0.075": next(p["pct_vss"] for p in crow if abs(p["half"] - 0.075) < 1e-9),
         "vss_at_0.075": next(p["vss"] for p in crow if abs(p["half"] - 0.075) < 1e-9),
         "gap_pp_at_0.075": next(p["unmet_gap_pp"] for p in crow if abs(p["half"] - 0.075) < 1e-9),
         "gap_pp_at_0.50": crow[-1]["unmet_gap_pp"], "gap_pp_at_0.01": g0,
         "gap_rise_0.01_to_0.50": crow[-1]["unmet_gap_pp"] - g0,
         "vss2_half": fmt(crossing(crow, "pct_vss", 2.0)),
         "vss15_half": fmt(crossing(crow, "pct_vss", 1.5)),
         "gap1_half": fmt(crossing(crow, "unmet_gap_pp", 1.0)),
         "gaprise1_half": fmt(crossing(crow, "gap_rise_pp", 1.0)),
         "gap_onset_solved": fmt(onset), "gap_onset_pred_rho": fmt(pred),
         "max_rp_inv_pp": max(p["rp_inv_pp"] for p in crow),
         "max_eev_inv_pp": max(p["eev_inv_pp"] for p in crow),
         "nonoptimal_halves": ";".join(str(b) for b in bad) or "none"}
    if mode == "multi":
        s["vms_at_0.075"] = next(p["vms"] for p in crow if abs(p["half"] - 0.075) < 1e-9)
        s["vms_max"] = max(p["vms"] for p in crow)
        s["vms_max_half"] = max(crow, key=lambda p: p["vms"])["half"]
        s["pct_vss_vs_rh_at_0.075"] = next(p["pct_vss_vs_rh"] for p in crow
                                           if abs(p["half"] - 0.075) < 1e-9)
        s["vss2_vs_rh_half"] = fmt(crossing(crow, "pct_vss_vs_rh", 2.0))
    summary.append(s)
    run.log(f"{name}: %VSS(0.075)={s['pct_vss_at_0.075']:.3f} 2%@{s['vss2_half']} "
            f"gap>1@{s['gap1_half']} rise>1@{s['gaprise1_half']} onset {s['gap_onset_solved']} "
            f"pred {s['gap_onset_pred_rho']} nonopt {s['nonoptimal_halves']}")

fields = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("config", "half"), k))
write_csv(run.path("sweep.csv"), rows, fields)
sfields = sorted({k for r in summary for k in r}, key=lambda k: (k != "config", k))
write_csv(run.path("summary.csv"), summary, sfields)
allok = all(r["ok"] for r in rows)
run.finish("OK" if allok else "PARTIAL", ["sweep.csv", "summary.csv", "log.txt"],
           notes=f"{len(rows)} sweep points; all optimal: {allok}; smoke={SMOKE}")
