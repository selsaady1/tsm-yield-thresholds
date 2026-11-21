"""
t3_capacity.py  (TSM-A, reviewer item R1.7d, capacity part)   run_id: t3_capacity
================================================================================
Capacity uncertainty on the paper's base instance, two separate experiments,
each capacity independent of the yields and of demand (2x2x2x2 = 16
equiprobable scenarios), over the Step 5/6 FE half-range sweep:

  LG : outsourced FE capacity L_G two-point, 300(1 - d) or 300(1 + d) dies
  LF : in-house FE capacity two-point, (1 - d) or (1 + d) times 10 / 8 wafers
       (a common shock to both fabs). Planned wafer starts x_f are first-stage
       (x_f <= (1 + d) L_F,f); the wafers processed are min(x_f, L_F,f,xi) and
       c_F is charged on processed wafers (tsa_common.solve_plan).
  d in {0, 0.1, 0.2, 0.3}; d = 0 must reproduce the paper's sweep (checked).

Deterministic plan: the expected-value problem with mean yields, mean demand
and MEAN capacity (L_G = 300; L_F = 10 / 8). In LF the expected-value problem
does not determine how wafers are split between the identical fabs; the plan
is split in proportion to fab capacity (equal utilisation, the rule of
Section VII-E). The split returned by CBC (FE1 first) is also evaluated and
reported as eev_obj_cbc_split.

Cliff check (Eq. (12) of main.tex with L_G replaced by its low value):
  predicted onset = first h with  n * y_lo * W_EV + L_G,lo < N_max   (LG)
                                  n * y_lo * min(W_EV, (1-d) sum L_F) + L_G < N_max   (LF)
with W_EV from the expected-value solve at that h and N_max from a solve with
FE supply non-binding (revision_common.max_die_requirement). The solved onset
is located by bisection on real solves inside the bracketing grid interval
(same procedure as experiments/capacity_cliff_sweep.py).

    cd tsm-yield-thresholds && .venv/bin/python code/tsm_a/t3_capacity.py [--smoke]
Outputs: results/tsm_a/t3_capacity/{points.csv, summary.csv, run.json, log.txt}
"""
import csv
import os
import sys
import time

from tsa_common import (RESULTS, FE_MEAN, HALF_GRID, base_inst, two_point, scenarios_2x2x2,
                        solve_plan, evaluate_plan, ev_scenario, crossing_up, self_check,
                        write_run_json, max_die_requirement)

SMOKE = "--smoke" in sys.argv
RUN_ID = "t3_capacity"
SEED = 0
OUT = os.path.join(RESULTS, RUN_ID + ("_smoke" if SMOKE else ""))
HALVES = [0.05, 0.15, 0.2, 0.25, 0.35, 0.45] if SMOKE else HALF_GRID
DELTAS = [0.0, 0.3] if SMOKE else [0.0, 0.1, 0.2, 0.3]
D_LO, D_HI, B_LO, B_HI = 600, 900, 0.70, 0.90
EPS = 1e-6
BASE = base_inst()
LF_NOM = dict(BASE["L_F"])
LG_NOM = BASE["L_G"]["G1"]


def make(kind, d, lo, hi):
    """(inst for RP/EEV, inst for EV, 16 scenarios)"""
    base = scenarios_2x2x2(lo, hi, D_LO, D_HI, B_LO, B_HI)
    sc = []
    if kind == "LG":
        for tag, cap in (("Glo", LG_NOM * (1 - d)), ("Ghi", LG_NOM * (1 + d))):
            for s in base:
                sc.append(dict(s, name=s["name"] + "_" + tag, prob=s["prob"] / 2, L_G=cap))
        return base_inst(), base_inst(), sc
    for tag, m in (("Flo", 1 - d), ("Fhi", 1 + d)):
        for s in base:
            sc.append(dict(s, name=s["name"] + "_" + tag, prob=s["prob"] / 2,
                           L_F={f: v * m for f, v in LF_NOM.items()}))
    return base_inst(L_F={f: v * (1 + d) for f, v in LF_NOM.items()}), base_inst(), sc


def run_point(kind, d, h):
    lo, hi = two_point(FE_MEAN, h)
    inst, inst_ev, sc = make(kind, d, lo, hi)
    rp = solve_plan(inst, sc, tag="RP")
    ev = solve_plan(inst_ev, ev_scenario(sc), tag="EV")
    if rp["status"] != "Optimal" or ev["status"] != "Optimal":
        return {"ok": False}
    w_ev = ev["W_total"]
    tot = sum(LF_NOM.values())
    x_bal = {f: w_ev * LF_NOM[f] / tot for f in LF_NOM}
    eev = evaluate_plan(inst, sc, x_bal if kind == "LF" else ev["X_F"])
    eev_cbc = evaluate_plan(inst, sc, ev["X_F"])
    if eev["status"] != "Optimal" or eev_cbc["status"] != "Optimal":
        return {"ok": False}
    vss = rp["obj"] - eev["exp_profit"]
    return {"ok": True, "kind": kind, "delta": d, "half": h, "fe_lo": lo, "fe_hi": hi,
            "clipped": int(FE_MEAN + h > 1 + 1e-9),
            "rp_obj": rp["obj"], "eev_obj": eev["exp_profit"], "vss": vss,
            "pct_vss": 100 * vss / rp["obj"],
            "eev_obj_cbc_split": eev_cbc["exp_profit"],
            "pct_vss_cbc_split": 100 * (rp["obj"] - eev_cbc["exp_profit"]) / rp["obj"],
            "rp_unmet": rp["exp_unmet"], "eev_unmet": eev["exp_unmet"],
            "unmet_gap": eev["exp_unmet"] - rp["exp_unmet"],
            "rp_wafers": rp["W_total"], "ev_wafers": w_ev,
            "rp_fe1": rp["X_F"]["FE1"], "rp_fe2": rp["X_F"]["FE2"]}


def bisect_first(f, a, b, tol=1e-4):
    if not f(b):
        return None
    while b - a > tol:
        m = 0.5 * (a + b)
        if f(m):
            b = m
        else:
            a = m
    return 0.5 * (a + b)


def main():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    log = open(os.path.join(OUT, "log.txt"), "w")

    def say(msg):
        print(msg, flush=True)
        log.write(msg + "\n")

    say(f"t3_capacity ({'SMOKE' if SMOKE else 'FULL'}) -> {OUT}")
    say(f"self-check: max |dev| = {self_check():.2e}")
    n = BASE["n_f_i"]
    n_max = max_die_requirement(BASE)
    say(f"N_max = {n_max:.4f}")
    points, summary, bad = [], [], 0
    for kind in ("LG", "LF"):
        for d in DELTAS:
            rows = []
            for h in HALVES:
                r = run_point(kind, d, h)
                if not r["ok"]:
                    bad += 1
                    say(f"  non-optimal at {kind} d={d} h={h}")
                    continue
                rows.append(r)
            points += rows
            xs = [r["half"] for r in rows]
            c2, n2 = crossing_up(xs, [r["pct_vss"] for r in rows], 2.0)
            c1, n1 = crossing_up(xs, [r["unmet_gap"] for r in rows], 1.0)
            first = next((r["half"] for r in rows if r["unmet_gap"] > EPS), None)
            if first is None:
                h_on = None
            else:
                prev = max([x for x in xs if x < first], default=0.0)
                h_on = bisect_first(lambda h: run_point(kind, d, h)["unmet_gap"] > EPS, prev, first)

            lg_lo = LG_NOM * (1 - d) if kind == "LG" else LG_NOM
            cap_lo = sum(LF_NOM.values()) * (1 - d) if kind == "LF" else 1e9

            def w_ev(h):
                lo, hi = two_point(FE_MEAN, h)
                _, inst_ev, sc = make(kind, d, lo, hi)
                return solve_plan(inst_ev, ev_scenario(sc), tag="EVp")["W_total"]

            def short(h, lgv):
                lo = two_point(FE_MEAN, h)[0]
                return n * lo * min(w_ev(h), cap_lo) + lgv < n_max - 1e-6

            h_pred = bisect_first(lambda h: short(h, lg_lo), 0.0, 0.5)
            h_pred_mean = bisect_first(lambda h: short(h, LG_NOM), 0.0, 0.5)
            rp0 = rows[0]["rp_unmet"]
            h_rp_unmet = next((r["half"] for r in rows if r["rp_unmet"] > rp0 + 1e-4), None)
            fm = lambda x: "NA" if x is None else f"{x:.4f}"
            ylo = lambda h: "NA" if h is None else f"{two_point(FE_MEAN, h)[0]:.4f}"
            rec = {"kind": kind, "delta": d, "L_G_low": lg_lo,
                   "fe_cap_low_wafers": "NA" if kind == "LG" else f"{cap_lo:.2f}",
                   "N_max": f"{n_max:.2f}",
                   "vss2_half": fm(c2) if c2 is not None else n2,
                   "gap1_half": fm(c1) if c1 is not None else n1,
                   "gap_onset_half": fm(h_on), "gap_onset_ylo": ylo(h_on),
                   "pred_onset_half_Lglow": fm(h_pred), "pred_onset_ylo_Lglow": ylo(h_pred),
                   "pred_onset_half_Lgmean": fm(h_pred_mean),
                   "abs_err_pred_vs_solved": ("NA" if (h_on is None or h_pred is None)
                                              else f"{abs(h_on - h_pred):.5f}"),
                   "rp_unmet_first_rise_grid_half": fm(h_rp_unmet),
                   "pct_vss_at_0.25": next((f"{r['pct_vss']:.4f}" for r in rows if abs(r["half"] - 0.25) < 1e-9), "NA"),
                   "gap_at_0.50": f"{rows[-1]['unmet_gap']:.4f}"}
            summary.append(rec)
            say("  " + " ".join(f"{k}={v}" for k, v in rec.items()))

    keys = list(points[0].keys())
    keys.remove("ok")
    with open(os.path.join(OUT, "points.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for p in points:
            w.writerow({k: (f"{p[k]:.6f}" if isinstance(p[k], float) else p[k]) for k in keys})
    with open(os.path.join(OUT, "summary.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)
    say(f"non-optimal points dropped: {bad}")
    say(f"done in {time.time() - t0:.0f} s")
    log.close()
    write_run_json(OUT, RUN_ID + ("_smoke" if SMOKE else ""),
                   "cd tsm-yield-thresholds && .venv/bin/python code/tsm_a/t3_capacity.py"
                   + (" --smoke" if SMOKE else ""), SEED, t0, time.time(),
                   {"n_points": len(points), "n_non_optimal": bad})


if __name__ == "__main__":
    main()
