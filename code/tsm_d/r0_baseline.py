"""r0_baseline.py: reproduce the published baseline RP, EEV, VSS (Step 1) and rho
before any new TSM-D experiment, and check that the named-constraint LP used by
r1 gives the same objectives as the published model builder.

    python code/tsm_d/r0_baseline.py   (from SANDBOX)
"""
import csv, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tsmd_common as T
rc = T.rc

RUN = "tsmd_r0_baseline"
PUBLISHED = {"rp_obj": 6380.66, "eev_obj": 6288.50, "vss": 92.16, "pct_vss": 1.44,
             "rp_wafers": 13.12, "ev_wafers": 10.29}   # main.tex Section VI-A (Step 1)


def main():
    t0, started = time.time(), T.now()
    d = T.run_dir(RUN)
    dev = rc.self_check()
    base = rc.base_inst()
    r = rc.evaluate(base, 0.80, 0.95)
    got = {"rp_obj": r["rp_obj"], "eev_obj": r["eev_obj"], "vss": r["vss"], "pct_vss": r["pct_vss"],
           "rp_wafers": r["rp_fe1"] + r["rp_fe2"], "ev_wafers": r["ev_fe1"] + r["ev_fe2"]}
    # rho ingredients at the base instance (same definitions as param_sensitivity_revision.py)
    n_max = rc.max_die_requirement(base)
    ev0 = rc.evaluate(base, rc.FE_MEAN, rc.FE_MEAN)
    w_ev = ev0["ev_fe1"] + ev0["ev_fe2"]
    n_bar = base["n_f_i"] * rc.FE_MEAN * w_ev
    l_g = sum(base["L_G"].values())
    rho = (n_max - l_g) / n_bar
    # named LP versus published builder at several half-ranges
    lp_dev = 0.0
    for h in (0.075, 0.15, 0.2, 0.35):
        lo, hi = rc.two_point(rc.FE_MEAN, h)
        sc = rc.scenarios_2x2x2(lo, hi, base["demand_lo"], base["demand_hi"], rc.BE_LO, rc.BE_HI)
        a = rc.solve_model(base, sc)
        b = T.solve_lp_named(base, sc)
        mean = lambda k: sum(s["prob"] * s[k] for s in sc)
        ev = rc.solve_model(base, [{"name": "EV", "prob": 1.0, "fe_yield": mean("fe_yield"),
                                    "demand": mean("demand"), "be_yield": mean("be_yield")}])
        a2 = rc.solve_model(base, sc, fix_xf=ev["X_F"])
        b2 = T.solve_lp_named(base, sc, fix_xf=ev["X_F"])
        lp_dev = max(lp_dev, abs(a["obj"] - b["obj"]), abs(a2["obj"] - b2["obj"]))
    rows = []
    ok = True
    for k, pub in PUBLISHED.items():
        match = abs(round(got[k], 2) - pub) < 1e-9
        ok &= match
        rows.append({"quantity": k, "published": pub, "reproduced": f"{got[k]:.6f}",
                     "rounded_2dp": f"{got[k]:.2f}", "match": int(match)})
    for k, v in (("N_bar", n_bar), ("N_max", n_max), ("L_G", l_g), ("rho", rho),
                 ("rho_times_ybar", rho * rc.FE_MEAN), ("rho_over_2_minus_rho", rho / (2 - rho)),
                 ("selfcheck_max_dev_vs_step2", dev), ("named_lp_max_dev", lp_dev)):
        rows.append({"quantity": k, "published": "", "reproduced": f"{v:.6f}",
                     "rounded_2dp": f"{v:.2f}", "match": ""})
    out = os.path.join(d, "baseline_check.csv")
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    for row in rows:
        print(row)
    status = "OK" if (ok and dev < 1e-4 and lp_dev < 1e-4) else "FAILED"
    T.write_run_json(RUN, "Baseline reproduction (RP, EEV, VSS, rho) before new runs; supports all TSM-D IDs",
                     "nice -n 10 python code/tsm_d/r0_baseline.py", "none (deterministic LP/MILP)",
                     started, t0, status, T.MODEL_FILES, [out],
                     [os.path.abspath(__file__)] + T.MODEL_FILES,
                     notes="published values from main.tex Section VI-A; named LP fixes o_g=o_a=1 (property (b))")
    print("STATUS", status)


if __name__ == "__main__":
    main()
