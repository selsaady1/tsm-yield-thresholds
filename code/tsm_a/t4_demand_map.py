"""
t4_demand_map.py  (TSM-A, reviewer item R1.7d, demand part)   run_id: t4_demand_map
====================================================================================
Demand on the decision map. Two-dimensional grid of FE yield half-range
(the 50 Step 5/6 levels, FE mean 0.875, clipping as in Eq. (11)) times demand
half-range dh in {0, 75, 150, 225, 300} units, at three demand means
qbar in {675, 750, 825} (0.9, 1.0, 1.1 times the base mean 750). Demand levels
are qbar - dh and qbar + dh (equiprobable, as in the paper); BE 0.70/0.90.

Per cell: %VSS and service gap (RP vs EEV), exactly as in the paper.
Per (qbar, dh): the %VSS = 2% and gap = 1 crossings, the solver-located gap
onset (bisection inside the bracketing grid interval, as in
experiments/capacity_cliff_sweep.py), and the onset predicted by Eq. (12):
first h with n * y_lo * W_EV(h) + L_G < N_max, with W_EV from the
expected-value solve at h and N_max from revision_common.max_die_requirement
for that demand. rho = (N_max - L_G) / N_bar with N_bar the dies used by the
expected-value plan at zero FE spread.

Reuse of Step 8: the qbar = 750 row is the Step 8 one-factor "demand_spread"
sweep (results/Revision/ParamSensitivity/ofat_sweep_points.csv, factor =
demand_spread). It is recomputed here and the maximum absolute difference in
%VSS and service gap against that file is written to reuse_check.csv.

    cd tsm-yield-thresholds && .venv/bin/python code/tsm_a/t4_demand_map.py [--smoke]
Outputs: results/tsm_a/t4_demand_map/{grid.csv, summary.csv, reuse_check.csv, run.json, log.txt}
"""
import csv
import os
import sys
import time

from tsa_common import (RESULTS, REPO, FE_MEAN, HALF_GRID, base_inst, two_point, scenarios_2x2x2,
                        solve_plan, evaluate_plan, ev_scenario, crossing_up, self_check,
                        write_run_json, max_die_requirement)

SMOKE = "--smoke" in sys.argv
RUN_ID = "t4_demand_map"
SEED = 0
OUT = os.path.join(RESULTS, RUN_ID + ("_smoke" if SMOKE else ""))
HALVES = [0.05, 0.15, 0.25, 0.35, 0.45] if SMOKE else HALF_GRID
MEANS = [750.0] if SMOKE else [675.0, 750.0, 825.0]
DHS = [0.0, 150.0, 300.0] if SMOKE else [0.0, 75.0, 150.0, 225.0, 300.0]
B_LO, B_HI = 0.70, 0.90
EPS = 1e-6
STEP8 = os.path.join(REPO, "results", "Revision", "ParamSensitivity", "ofat_sweep_points.csv")


def point(inst, h):
    lo, hi = two_point(FE_MEAN, h)
    sc = scenarios_2x2x2(lo, hi, inst["demand_lo"], inst["demand_hi"], B_LO, B_HI)
    rp = solve_plan(inst, sc, tag="RP")
    ev = solve_plan(inst, ev_scenario(sc), tag="EV")
    if rp["status"] != "Optimal" or ev["status"] != "Optimal":
        return None
    eev = evaluate_plan(inst, sc, ev["X_F"])
    if eev["status"] != "Optimal":
        return None
    vss = rp["obj"] - eev["exp_profit"]
    return {"half": h, "fe_lo": lo, "fe_hi": hi, "clipped": int(FE_MEAN + h > 1 + 1e-9),
            "rp_obj": rp["obj"], "eev_obj": eev["exp_profit"], "vss": vss,
            "pct_vss": 100 * vss / rp["obj"], "rp_unmet": rp["exp_unmet"],
            "eev_unmet": eev["exp_unmet"], "unmet_gap": eev["exp_unmet"] - rp["exp_unmet"],
            "ev_wafers": ev["W_total"], "rp_wafers": rp["W_total"],
            "ev_dies_used": max(ev["dies_used"].values())}


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

    say(f"t4_demand_map ({'SMOKE' if SMOKE else 'FULL'}) -> {OUT}")
    say(f"self-check: max |dev| = {self_check():.2e}")
    grid, summary, bad = [], [], 0
    for qbar in MEANS:
        for dh in DHS:
            inst = base_inst(demand_lo=qbar - dh, demand_hi=qbar + dh)
            rows = []
            for h in HALVES:
                r = point(inst, h)
                if r is None:
                    bad += 1
                    continue
                r.update({"demand_mean": qbar, "demand_half": dh})
                rows.append(r)
            grid += rows
            xs = [r["half"] for r in rows]
            c2, n2 = crossing_up(xs, [r["pct_vss"] for r in rows], 2.0)
            c1, n1 = crossing_up(xs, [r["unmet_gap"] for r in rows], 1.0)
            first = next((r["half"] for r in rows if r["unmet_gap"] > EPS), None)
            if first is None:
                h_on = None
            else:
                prev = max([x for x in xs if x < first], default=0.0)
                h_on = bisect_first(lambda h: point(inst, h)["unmet_gap"] > EPS, prev, first)
            n_max = max_die_requirement(inst)
            l_g = sum(inst["L_G"].values())
            n = inst["n_f_i"]
            ev0 = solve_plan(inst, ev_scenario(scenarios_2x2x2(FE_MEAN, FE_MEAN, inst["demand_lo"],
                                                               inst["demand_hi"], B_LO, B_HI)), tag="EV0")
            n_bar = max(ev0["dies_used"].values())
            rho = (n_max - l_g) / n_bar

            def short(h):
                lo, hi = two_point(FE_MEAN, h)
                sc = scenarios_2x2x2(lo, hi, inst["demand_lo"], inst["demand_hi"], B_LO, B_HI)
                w = solve_plan(inst, ev_scenario(sc), tag="EVp")["W_total"]
                return n * lo * w + l_g < n_max - 1e-6

            h_pred = bisect_first(short, 0.0, 0.5)
            fm = lambda x: "NA" if x is None else f"{x:.4f}"
            rec = {"demand_mean": qbar, "demand_half": dh, "N_max": f"{n_max:.2f}",
                   "N_bar": f"{n_bar:.2f}", "L_G": l_g, "rho": f"{rho:.4f}",
                   "vss2_half": fm(c2) if c2 is not None else n2,
                   "gap1_half": fm(c1) if c1 is not None else n1,
                   "gap_onset_half": fm(h_on), "pred_onset_half": fm(h_pred),
                   "abs_err_pred_vs_solved": ("NA" if (h_on is None or h_pred is None)
                                              else f"{abs(h_on - h_pred):.5f}"),
                   "pct_vss_at_first_grid": f"{rows[0]['pct_vss']:.4f}",
                   "pct_vss_max": f"{max(r['pct_vss'] for r in rows):.4f}",
                   "gap_max": f"{max(r['unmet_gap'] for r in rows):.4f}"}
            summary.append(rec)
            say("  " + " ".join(f"{k}={v}" for k, v in rec.items()))

    keys = ["demand_mean", "demand_half", "half", "fe_lo", "fe_hi", "clipped", "rp_obj", "eev_obj",
            "vss", "pct_vss", "rp_unmet", "eev_unmet", "unmet_gap", "rp_wafers", "ev_wafers",
            "ev_dies_used"]
    with open(os.path.join(OUT, "grid.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for p in grid:
            w.writerow({k: (f"{p[k]:.6f}" if isinstance(p[k], float) else p[k]) for k in keys})
    with open(os.path.join(OUT, "summary.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)

    # reuse check against Step 8 (qbar = 750 slice)
    chk = []
    if os.path.exists(STEP8):
        s8 = [r for r in csv.DictReader(open(STEP8)) if r["factor"] == "demand_spread"]
        for dh in DHS:
            mine = {round(p["half"], 4): p for p in grid if p["demand_mean"] == 750.0 and p["demand_half"] == dh}
            theirs = [r for r in s8 if abs(float(r["level"]) - dh) < 1e-9]
            d_v = [abs(mine[round(float(r["half"]), 4)]["pct_vss"] - float(r["pct_vss"]))
                   for r in theirs if round(float(r["half"]), 4) in mine]
            d_g = [abs(mine[round(float(r["half"]), 4)]["unmet_gap"] - float(r["unmet_gap"]))
                   for r in theirs if round(float(r["half"]), 4) in mine]
            chk.append({"demand_half": dh, "n_matched": len(d_v),
                        "max_abs_diff_pct_vss": f"{max(d_v):.6f}" if d_v else "NA",
                        "max_abs_diff_unmet_gap": f"{max(d_g):.6f}" if d_g else "NA",
                        "step8_file": os.path.relpath(STEP8, REPO)})
        with open(os.path.join(OUT, "reuse_check.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(chk[0].keys()))
            w.writeheader()
            w.writerows(chk)
        for c in chk:
            say("  reuse " + " ".join(f"{k}={v}" for k, v in c.items()))
    say(f"non-optimal points dropped: {bad}")
    say(f"done in {time.time() - t0:.0f} s")
    log.close()
    write_run_json(OUT, RUN_ID + ("_smoke" if SMOKE else ""),
                   "cd tsm-yield-thresholds && .venv/bin/python code/tsm_a/t4_demand_map.py"
                   + (" --smoke" if SMOKE else ""), SEED, t0, time.time(),
                   {"n_points": len(grid), "n_non_optimal": bad})


if __name__ == "__main__":
    main()
