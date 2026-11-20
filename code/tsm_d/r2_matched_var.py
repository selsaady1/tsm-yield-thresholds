"""r2_matched_var.py (T4; R1.6): is the two-point threshold conservative?

Base instance, FE yield only is varied (demand and BE yield keep their two
levels). Families compared:

  matched support  -- the same interval [y_lo, y_hi] of eq. (twopoint) for a
                      half-range h: two-point {y_lo, y_hi}; uniform on the
                      interval; Beta(2,2) on the interval. Discretised at K
                      quantile midpoints (K = 7 as in the paper's Beta check,
                      and K = 15 to check the discretisation). All three are
                      symmetric on the interval, so they share the mean.
  matched mean/sd  -- Beta with mean 0.875 and standard deviation sigma
                      (K = 7 quantile midpoints, as in Section S-VI).

For every family we record %VSS and the service gap on a grid, the %VSS = 2%
crossing (linear interpolation, the paper's rule) and the service-gap onset
(grid bracket, then bisection to 1e-5), each with the realised mean, the
realised standard deviation, and the lowest support point there.

    nice -n 10 python code/tsm_d/r2_matched_var.py [--smoke]
"""
import csv, math, os, sys, time
import numpy as np
from scipy.stats import beta as beta_dist
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tsmd_common as T
rc = T.rc

SMOKE = "--smoke" in sys.argv
RUN = "tsmd_r2_matched_var" + ("_smoke" if SMOKE else "")
BASE = rc.base_inst()
MU = rc.FE_MEAN


def support_points(family, h, K):
    lo, hi = rc.two_point(MU, h)
    if family == "two_point":
        return [lo, hi], [0.5, 0.5]
    qs = (np.arange(1, K + 1) - 0.5) / K
    if family == "uniform":
        u = qs
    elif family == "beta22":
        u = beta_dist.ppf(qs, 2, 2)
    else:
        raise ValueError(family)
    return [float(lo + (hi - lo) * x) for x in u], [1.0 / K] * K


def beta_meansd_points(sigma, K=7):
    t = MU * (1 - MU) / sigma ** 2 - 1.0
    a, b = MU * t, (1 - MU) * t
    qs = (np.arange(1, K + 1) - 0.5) / K
    return [float(beta_dist.ppf(q, a, b)) for q in qs], [1.0 / K] * K


def evaluate_points(pts, probs):
    sc = [{"name": f"F{i}_{dn}_{bn}", "prob": pf * 0.25, "fe_yield": fv, "demand": dv, "be_yield": bv}
          for i, (fv, pf) in enumerate(zip(pts, probs))
          for dn, dv in (("Dlo", BASE["demand_lo"]), ("Dhi", BASE["demand_hi"]))
          for bn, bv in (("BElo", rc.BE_LO), ("BEhi", rc.BE_HI))]
    r = rc.evaluate_scenarios(BASE, sc)
    mean = sum(p * y for y, p in zip(pts, probs))
    sd = math.sqrt(sum(p * (y - mean) ** 2 for y, p in zip(pts, probs)))
    return {"ok": r["ok"], "pct_vss": r["pct_vss"], "gap": r["unmet_gap"], "mean": mean, "sd": sd,
            "lowest": min(pts), "lowest_over_mean": min(pts) / mean}


def analyse(label, K, param_name, grid, make):
    rows = []
    for x in grid:
        pts, pr = make(x)
        e = evaluate_points(pts, pr)
        e.update({"family": label, "K": K, param_name: x})
        rows.append(e)
    # %VSS = 2 % crossing, linear interpolation (paper rule)
    c2 = None
    if rows[0]["pct_vss"] >= 2.0:
        c2 = "below_grid"
    else:
        for a, b in zip(rows, rows[1:]):
            if a["pct_vss"] < 2.0 <= b["pct_vss"]:
                t = (2.0 - a["pct_vss"]) / (b["pct_vss"] - a["pct_vss"])
                c2 = {k: a[k] + t * (b[k] - a[k]) for k in (param_name, "mean", "sd", "lowest")}
                break
    # service-gap onset: first grid point with gap > 1e-6, then bisection
    on = None
    prev = None
    for r in rows:
        if r["gap"] > 1e-6:
            a_, b_ = (prev[param_name] if prev else 0.0), r[param_name]
            while b_ - a_ > 1e-5:
                m = 0.5 * (a_ + b_)
                if evaluate_points(*make(m))["gap"] > 1e-6:
                    b_ = m
                else:
                    a_ = m
            x = 0.5 * (a_ + b_)
            e = evaluate_points(*make(x))
            on = {param_name: x, "mean": e["mean"], "sd": e["sd"], "lowest": e["lowest"],
                  "lowest_over_mean": e["lowest_over_mean"]}
            break
        prev = r
    return rows, c2, on


def main():
    t0, started = time.time(), T.now()
    d = T.run_dir(RUN)
    log = open(os.path.join(d, "progress.log"), "w")
    hgrid = [round(0.005 * i, 4) for i in range(1, 101)]
    sgrid = [round(0.005 * i, 4) for i in range(2, 51)]       # sigma 0.01 .. 0.25
    Ks = [7, 15]
    if SMOKE:
        hgrid, sgrid, Ks = hgrid[9::10], sgrid[::6], [7]
    pts_rows, summ = [], []
    bad = 0
    specs = [("two_point", 2, "half", hgrid, lambda h: support_points("two_point", h, 2))]
    for K in Ks:
        specs.append(("uniform", K, "half", hgrid, (lambda K: lambda h: support_points("uniform", h, K))(K)))
        specs.append(("beta22", K, "half", hgrid, (lambda K: lambda h: support_points("beta22", h, K))(K)))
    specs.append(("beta_mean_sd", 7, "sigma", sgrid, lambda s: beta_meansd_points(s, 7)))
    for label, K, pname, grid, make in specs:
        rows, c2, on = analyse(label, K, pname, grid, make)
        bad += sum(1 for r in rows if not r["ok"])
        for r in rows:
            pts_rows.append({"family": label, "K": K, "param": pname, "value": r[pname],
                             "mean": f"{r['mean']:.6f}", "sd": f"{r['sd']:.6f}",
                             "lowest": f"{r['lowest']:.6f}", "pct_vss": f"{r['pct_vss']:.6f}",
                             "service_gap": f"{r['gap']:.6f}", "ok": int(r["ok"])})
        rec = {"family": label, "K": K, "param": pname}
        if isinstance(c2, dict):
            rec.update({f"vss2_{pname}": f"{c2[pname]:.5f}", "vss2_mean": f"{c2['mean']:.5f}",
                        "vss2_sd": f"{c2['sd']:.5f}", "vss2_lowest": f"{c2['lowest']:.5f}"})
        else:
            rec.update({f"vss2_{pname}": c2 or "none", "vss2_mean": "NA", "vss2_sd": "NA", "vss2_lowest": "NA"})
        if on:
            rec.update({f"onset_{pname}": f"{on[pname]:.5f}", "onset_mean": f"{on['mean']:.5f}",
                        "onset_sd": f"{on['sd']:.5f}", "onset_lowest": f"{on['lowest']:.5f}",
                        "onset_lowest_over_mean": f"{on['lowest_over_mean']:.5f}"})
        else:
            rec.update({f"onset_{pname}": "none", "onset_mean": "NA", "onset_sd": "NA",
                        "onset_lowest": "NA", "onset_lowest_over_mean": "NA"})
        summ.append(rec)
        log.write(f"{T.now()} {label} K={K}: {rec}\n"); log.flush()
        print(rec, flush=True)
    # normalise summary columns
    keys = []
    for r in summ:
        for k in r:
            if k not in keys:
                keys.append(k)
    summ = [{k: r.get(k, "") for k in keys} for r in summ]
    # decision rule for the text key TSMD_tp_matchedvar
    tp = next(r for r in summ if r["family"] == "two_point")
    others = [r for r in summ if r["family"] != "two_point"]
    tp_sd = float(tp["vss2_sd"])
    oth_sd = [float(r["vss2_sd"]) for r in others if r["vss2_sd"] not in ("NA", "")]
    tp_h = float(tp["vss2_half"])
    oth_h = [float(r["vss2_half"]) for r in others if r.get("vss2_half") not in (None, "", "NA", "none", "below_grid")]
    verdict = {
        "two_point_vss2_half": tp_h, "min_other_vss2_half_matched_support": min(oth_h) if oth_h else None,
        "two_point_crosses_first_at_matched_support": int(all(tp_h <= x for x in oth_h)),
        "two_point_vss2_sd": tp_sd, "max_other_vss2_sd": max(oth_sd) if oth_sd else None,
        "two_point_crosses_last_at_matched_sd": int(all(tp_sd >= x for x in oth_sd)),
    }
    verdict["TSMD_tp_matchedvar"] = ("does not support" if verdict["two_point_crosses_last_at_matched_sd"]
                                     else "supports")
    verdict["rule"] = ("'supports' only if, at matched mean and standard deviation, the two-point 2% crossing "
                       "(in sd units) is not larger than every alternative family's; it is reported as "
                       "'does not support' when the two-point family is the last to cross")
    outs = []
    for name, data in (("matched_points.csv", pts_rows), ("matched_summary.csv", summ),
                       ("matched_verdict.csv", [{"key": k, "value": v} for k, v in verdict.items()])):
        p = os.path.join(d, name)
        with open(p, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0]))
            w.writeheader(); w.writerows(data)
        outs.append(p)
    log.write(f"{T.now()} verdict {verdict}\n"); log.close()
    print(verdict)
    T.write_run_json(RUN, "T4 (R1.6): two-point versus uniform and Beta FE yield at matched support and at matched mean/sd",
                     "nice -n 10 python code/tsm_d/r2_matched_var.py" + (" --smoke" if SMOKE else ""),
                     "none (deterministic quantile-midpoint discretisation)", started, t0,
                     "OK" if bad == 0 else "FAILED", T.MODEL_FILES, outs,
                     [os.path.abspath(__file__)] + T.MODEL_FILES,
                     notes=f"non-optimal solves: {bad}")


if __name__ == "__main__":
    main()
