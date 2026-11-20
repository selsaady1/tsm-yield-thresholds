"""run_r03_congestion.py: WIP and congestion through a clearing function (R1.8).

Each fab's output is limited by a concave clearing function of its WIP,
x_f <= L_f W_f / (W_f + t0 L_f) (t0 = 1 period of raw process time), and WIP
costs c_W per wafer per period.  Base c_W = c_K * n * mean FE yield = 4.375
(the paper's die-bank holding cost applied to one wafer's good dies).

Configurations:
  nocong       paper's model (reference)
  cf_k1        clearing function, c_W = 4.375
  cf_k025      c_W x 0.25
  cf_k4        c_W x 4
  pwl_k1       cross-check: same WIP cost as a convex piecewise-linear cost of
               utilisation (Factory Physics VUT form, V = 1)
  cf_k1_be     clearing functions at FE and at both BE facilities (BE WIP
               cost c_K = 0.05 per die per period); BE loading is recourse, so
               BE cycle time differs by scenario
  tg_cf_k1     tool groups with one clearing function per group (raw time
               shares litho 0.45, etch 0.35, implant 0.20)
  ni_cf_k1     non-identical fabs (ni_main of run r02) with congestion
  ni_nocong    non-identical fabs without congestion (reference)
Outputs: sweep.csv, summary.csv, scenario_ct.csv (per-scenario utilisation
and cycle-time proxy at the base half-range), log.txt, run.json.
Usage: nice -n 10 $PY run_r03_congestion.py [--smoke]
"""
import sys

from tsmb_common import Run, write_csv
import revision_common as rc
import tsmb_static as ts
import tsmb_sweeps as sw

SMOKE = "--smoke" in sys.argv
run = Run("tsmb_r03_congestion" + ("_smoke" if SMOKE else ""),
          "R1.8: load-dependent cycle time (clearing function / convex congestion cost); "
          "facility loading, hedge, VSS, threshold",
          [__file__, sw.__file__, ts.__file__, rc.__file__])
halves = [0.075, 0.20, 0.40] if SMOKE else sw.HALVES
base = rc.base_inst()
cw = sw.C_W_BASE
cf = lambda m, **x: dict({"mode": "cf", "c_W": cw * m, "t0": 1.0}, **x)
NI = {"fe2_mean": 0.825, "corr": False, "c_F_f": {"FE1": 1.50, "FE2": 1.65}}
CONFIGS = [
    {"name": "nocong", "inst": base},
    {"name": "cf_k1", "inst": base, "cong": cf(1.0)},
    {"name": "cf_k025", "inst": base, "cong": cf(0.25)},
    {"name": "cf_k4", "inst": base, "cong": cf(4.0)},
    {"name": "pwl_k1", "inst": base, "cong": dict(cf(1.0), mode="pwl")},
    {"name": "cf_k1_be", "inst": base, "cong": cf(1.0, be=True, c_W_be=base["c_K"], t0_be=1.0)},
    {"name": "tg_cf_k1", "inst": base, "groups": sw.TOOL_GROUPS,
     "cong": cf(1.0, per_group=True, t0_k=sw.T0_SHARE)},
    dict({"name": "ni_cf_k1", "inst": base, "cong": cf(1.0)}, **NI),
    dict({"name": "ni_nocong", "inst": base}, **NI),
]
run.log(f"c_W base = {cw}; clearing-function tangent points: {ts.U_GRID}")
rows, summary, ctrows = [], [], []
ref = None
for cfg in CONFIGS:
    rs = sw.sweep(cfg, halves, run.progress)
    s = sw.summarize(cfg, rs)
    s.update(sw.cliff(cfg, rs))
    if cfg["name"] == "nocong":
        ref = s
    if ref is not None and ref["hedge_at_0.075"]:
        s["hedge_drop_pct_vs_nocong"] = 100 * (ref["hedge_at_0.075"] - s["hedge_at_0.075"]) / ref["hedge_at_0.075"]
    # per-scenario utilisation / cycle-time proxy at the base half-range
    raw = next(r for r in rs if abs(r["half"] - 0.075) < 1e-9)["_raw"]
    sc, _, _ = sw.scen(cfg, 0.075)
    for plan in ("rp", "eev"):
        res = raw[plan]
        for scn in sc:
            row = {"config": cfg["name"], "plan": plan, "scenario": scn["name"],
                   "fe1_yield": scn["fe_yield_f"]["FE1"], "fe2_yield": scn["fe_yield_f"]["FE2"],
                   "demand": scn["demand"], "be_yield": scn["be_yield"],
                   "u_fe1": res["util"]["FE1"], "u_fe2": res["util"]["FE2"],
                   "ct_fe1": res.get("ct_fe", {}).get("FE1", ""),
                   "ct_fe2": res.get("ct_fe", {}).get("FE2", ""),
                   "unmet": res["M"][scn["name"]]}
            if "ct_be" in res:
                row.update({"u_be1": res["util_be"][scn["name"]]["BE1"],
                            "u_be2": res["util_be"][scn["name"]]["BE2"],
                            "ct_be1": res["ct_be"][scn["name"]]["BE1"],
                            "ct_be2": res["ct_be"][scn["name"]]["BE2"]})
            ctrows.append(row)
    summary.append(s)
    for r in rs:
        r.pop("_raw", None)
        r["config"] = cfg["name"]
    rows += rs
    run.log(f"{cfg['name']}: %VSS(0.075)={s['pct_vss_at_0.075']:.3f} hedge={s['hedge_at_0.075']:.3f} "
            f"util RP {s['rp_u1_at_0.075']:.3f}/{s['rp_u2_at_0.075']:.3f} EV {s['ev_u1_at_0.075']:.3f}/"
            f"{s['ev_u2_at_0.075']:.3f} 2%@{s['vss2_half']} gap>1@{s['gap1_half']} onset "
            f"{s['gap_onset_solved']} pred {s['gap_onset_pred']} maxdiff {s['max_abs_util_diff_rp']:.4f}")

fields = ["config"] + sorted({k for r in rows for k in r if k != "config"})
write_csv(run.path("sweep.csv"), rows, fields)
sf = sorted({k for s in summary for k in s}, key=lambda k: (k != "config", k))
write_csv(run.path("summary.csv"), summary, sf)
cf_ = ["config", "plan", "scenario"] + sorted({k for r in ctrows for k in r} - {"config", "plan", "scenario"})
write_csv(run.path("scenario_ct.csv"), ctrows, cf_)
ok = all(r["ok"] for r in rows)
run.finish("OK" if ok else "PARTIAL", ["sweep.csv", "summary.csv", "scenario_ct.csv", "log.txt"],
           notes=f"all optimal: {ok}; smoke={SMOKE}")
