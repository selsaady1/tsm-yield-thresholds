"""r3_mapping.py (T5; R2.1, R2.2, R2.3): how the 'about 70%' worst-case FE
yield moves when demand, BE capacity, outsourced FE capacity, FE capacity and
mean yields change one at a time (levels of Table S-IV, Step 8).

For each configuration:
  rho = (N_max - L_G) / N_bar, with N_max from repo max_die_requirement (a
        solve), N_bar = n * ybar * W_EV from the expected-value plan at zero
        spread (a solve), L_G the outsourced FE capacity;
  predicted onset worst-case yield: rho*ybar if (1-rho)*ybar <= 1-ybar
        (symmetric regime), else rho/(2-rho) (upper yield clipped at 1);
  solved onset: first grid point (0.01 step) with service gap > 1e-6, then
        bisection to 1e-5 on real RP/EEV solves;
  %VSS = 2% crossing: 0.01 grid, linear interpolation (the paper's rule).

    nice -n 10 python code/tsm_d/r3_mapping.py [--smoke]
"""
import csv, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tsmd_common as T
rc = T.rc

SMOKE = "--smoke" in sys.argv
RUN = "tsmd_r3_mapping" + ("_smoke" if SMOKE else "")
BASE = rc.base_inst()
GAP_TOL = 1e-6


def scaled(d, m):
    return {k: v * m for k, v in d.items()}


def configs():
    C = [("base", 0, {}, rc.FE_MEAN, (rc.BE_LO, rc.BE_HI))]
    std = lambda o: (o, rc.FE_MEAN, (rc.BE_LO, rc.BE_HI))
    for m in (0.8, 0.9, 1.1, 1.2):
        C.append(("demand_level", m) + std({"demand_lo": 600 * m, "demand_hi": 900 * m}))
    for dd in (0.0, 75.0, 225.0, 300.0):
        C.append(("demand_spread", dd) + std({"demand_lo": 750 - dd, "demand_hi": 750 + dd}))
    for m in (0.8, 0.9, 1.1, 1.25, 1.5):
        C.append(("be_capacity", m) + std({"L_B": scaled(BASE["L_B"], m)}))
    for c in (0.0, 150.0, 450.0, 600.0):
        C.append(("outs_fe_capacity", c) + std({"L_G": {"G1": c}}))
    for m in (0.6, 0.8, 1.25, 1.5):
        C.append(("fe_capacity", m) + std({"L_F": scaled(BASE["L_F"], m)}))
    for m in (0.70, 0.75, 0.80, 0.82, 0.85, 0.90, 0.92, 0.95):
        C.append(("fe_mean", m, {}, m, (rc.BE_LO, rc.BE_HI)))
    for m in (0.70, 0.75, 0.85, 0.90):
        C.append(("be_mean", m, {}, rc.FE_MEAN, (round(m - 0.10, 4), round(m + 0.10, 4))))
    if SMOKE:
        C = [C[0], C[1], C[10], C[-3]]
    return C


def rho_parts(inst, ybar, bl, bh):
    n_max = rc.max_die_requirement(inst, bl, bh)
    ev0 = rc.evaluate(inst, ybar, ybar, bl, bh)
    w_ev = ev0["ev_fe1"] + ev0["ev_fe2"]
    n_bar = inst["n_f_i"] * ybar * w_ev
    l_g = sum(inst["L_G"].values())
    rho = (n_max - l_g) / n_bar if n_bar > 1e-9 else float("inf")
    return n_max, n_bar, l_g, rho, w_ev, ev0["ok"]


def predicted(rho, ybar):
    if rho <= 0:
        return None, None, "none (rho<=0)"
    if (1 - rho) * ybar <= 1 - ybar + 1e-12:          # symmetric regime at the onset
        ylo = rho * ybar
        return max(0.0, ybar - ylo), ylo, "symmetric"
    ylo = rho / (2 - rho)
    return max(0.0, ybar - ylo), ylo, "clipped"


def solved_onset(inst, ybar, bl, bh, halves, rows):
    prev = 0.0
    for h, r in zip(halves, rows):
        if r["ok"] and r["unmet_gap"] > GAP_TOL:
            a, b = prev, h
            g = lambda x: rc.evaluate(inst, *rc.two_point(ybar, x), bl, bh)["unmet_gap"]
            while b - a > 1e-5:
                m = 0.5 * (a + b)
                if g(m) > GAP_TOL:
                    b = m
                else:
                    a = m
            return 0.5 * (a + b)
        prev = h
    return None


def main():
    t0, started = time.time(), T.now()
    d = T.run_dir(RUN)
    log = open(os.path.join(d, "progress.log"), "w")
    halves = rc.HALF_GRID[1::2] if SMOKE else rc.HALF_GRID
    out, bad = [], 0
    for fac, lv, over, ybar, (bl, bh) in configs():
        inst = rc.base_inst(**over)
        n_max, n_bar, l_g, rho, w_ev, ok0 = rho_parts(inst, ybar, bl, bh)
        rows = rc.sweep(inst, fe_mean=ybar, be_lo=bl, be_hi=bh, halves=halves)
        bad += sum(1 for r in rows if not r["ok"]) + (0 if ok0 else 1)
        c2 = rc.crossing(rows, "pct_vss", 2.0)
        h_on = solved_onset(inst, ybar, bl, bh, halves, rows)
        ph, pylo, preg = predicted(rho, ybar)
        rec = {"factor": fac, "level": lv, "fe_mean": ybar, "be_lo": bl, "be_hi": bh,
               "N_max": round(n_max, 4), "N_bar": round(n_bar, 4), "L_G": l_g, "W_EV": round(w_ev, 6),
               "rho": round(rho, 6), "rho_times_ybar": round(rho * ybar, 6),
               "pred_onset_half": "NA" if ph is None else round(ph, 5),
               "pred_onset_ylo": "NA" if pylo is None else round(pylo, 5), "pred_regime": preg}
        if h_on is None:
            rec.update({"solved_onset_half": "none", "solved_onset_ylo": "NA", "onset_abs_err_half": "NA"})
        else:
            lo, hi = rc.two_point(ybar, h_on)
            rec.update({"solved_onset_half": round(h_on, 5), "solved_onset_ylo": round(lo, 5),
                        "onset_abs_err_half": "NA" if ph is None else round(abs(ph - h_on), 5)})
        if c2 is None:
            rec.update({"vss2_half": "none", "vss2_ylo": "NA", "vss2_regime": "no_crossing"})
        elif c2["half"] is None:
            rec.update({"vss2_half": "below_grid", "vss2_ylo": "NA", "vss2_regime": "above_at_first_grid_point"})
        else:
            rec.update({"vss2_half": round(c2["half"], 5), "vss2_ylo": round(c2["y_lo"], 5),
                        "vss2_regime": "clipped" if c2["clipped"] else "symmetric"})
        out.append(rec)
        msg = f"{T.now()} {fac}={lv}: rho={rho:.4f} pred_ylo={rec['pred_onset_ylo']} solved_ylo={rec['solved_onset_ylo']} vss2_ylo={rec['vss2_ylo']}"
        print(msg, flush=True); log.write(msg + "\n"); log.flush()
    p = os.path.join(d, "mapping_table.csv")
    with open(p, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader(); w.writerows(out)
    log.close()
    T.write_run_json(RUN, "T5 (R2.1-R2.3): worst-case-yield threshold and rho under one-factor changes",
                     "nice -n 10 python code/tsm_d/r3_mapping.py" + (" --smoke" if SMOKE else ""),
                     "none (deterministic)", started, t0, "OK" if bad == 0 else "FAILED",
                     T.MODEL_FILES, [p], [os.path.abspath(__file__)] + T.MODEL_FILES,
                     notes=f"non-optimal solves: {bad}; factor levels are those of Step 8 (Table S-IV)")


if __name__ == "__main__":
    main()
