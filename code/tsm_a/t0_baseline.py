"""
t0_baseline.py  (TSM-A)  run_id: t0_baseline
Reproduce the paper's baseline RP, EEV and VSS (Section VI-A of main.tex:
RP $6,380.66, EEV $6,288.50, VSS $92.16) with the TSM-A builder before any
new experiment, and assert agreement with revision_common/step2.

    cd tsm-yield-thresholds && .venv/bin/python code/tsm_a/t0_baseline.py
"""
import csv
import os
import sys
import time

from tsa_common import (RESULTS, base_inst, scenarios_2x2x2, solve_plan, evaluate_plan,
                        ev_scenario, self_check, write_run_json, max_die_requirement)

RUN_ID = "t0_baseline"
SEED = 0  # deterministic, no randomness


def main():
    t0 = time.time()
    out = os.path.join(RESULTS, RUN_ID)
    os.makedirs(out, exist_ok=True)
    dev = self_check()
    inst = base_inst()
    sc = scenarios_2x2x2(0.80, 0.95, 600, 900, 0.70, 0.90)
    rp = solve_plan(inst, sc, tag="RP")
    ev = solve_plan(inst, ev_scenario(sc), tag="EV")
    eev = evaluate_plan(inst, sc, ev["X_F"])
    rows = [
        ["self_check_max_abs_dev", f"{dev:.2e}"],
        ["rp_obj", f"{rp['obj']:.2f}"], ["eev_obj", f"{eev['obj']:.2f}"],
        ["vss", f"{rp['obj'] - eev['obj']:.2f}"],
        ["pct_vss", f"{100 * (rp['obj'] - eev['obj']) / rp['obj']:.2f}"],
        ["rp_wafers", f"{rp['W_total']:.2f}"], ["ev_wafers", f"{ev['W_total']:.2f}"],
        ["rp_exp_unmet", f"{rp['exp_unmet']:.4f}"], ["eev_exp_unmet", f"{eev['exp_unmet']:.4f}"],
        ["N_max", f"{max_die_requirement(inst):.2f}"],
        ["N_bar_ev_dies_used", f"{max(ev['dies_used'].values()):.2f}"],
    ]
    paper = {"rp_obj": "6380.66", "eev_obj": "6288.50", "vss": "92.16", "pct_vss": "1.44",
             "rp_wafers": "13.12", "ev_wafers": "10.29"}
    ok = all(dict(rows)[k] == v for k, v in paper.items())
    with open(os.path.join(out, "baseline.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["quantity", "value", "paper_value", "match"])
        for k, v in rows:
            w.writerow([k, v, paper.get(k, ""), "" if k not in paper else int(v == paper[k])])
    for k, v in rows:
        print(f"  {k:24s} {v:>12s}  paper {paper.get(k, '-')}")
    print("BASELINE REPRODUCED" if ok else "BASELINE MISMATCH")
    write_run_json(out, RUN_ID, "cd tsm-yield-thresholds && .venv/bin/python code/tsm_a/t0_baseline.py",
                   SEED, t0, time.time(), {"baseline_reproduced": ok})
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
