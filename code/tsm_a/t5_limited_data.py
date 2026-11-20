"""
t5_limited_data.py  (TSM-A, reviewer item R1.1)   run_id: t5_limited_data
===========================================================================
How accurate is the stochastic plan when the FE-yield distribution is
estimated from limited data?

Truth. The FE yield is Beta-distributed with mean 0.875 and standard
deviation sigma, the continuous family the paper already uses (Section VI-H,
experiments/beta_experiment.py: beta_ab, same moment matching). Two truths:
sigma = 0.075 (the base two-point instance 0.80/0.95 has this standard
deviation) and sigma = 0.15 (beyond the Beta %VSS = 2% crossing of the paper).
Demand (600/900) and BE yield (0.70/0.90) keep the paper's two-point levels
and are treated as known; only the FE-yield distribution is estimated.

Data and plans. n in {5, 10, 20, 50, 100} historical lot yields are drawn
from the truth, R = 200 replications per (sigma, n), seed
SeedSequence([20261113, sigma index, n, r]).
  * SAA plan: the n observed yields as equiprobable FE scenarios (x the 2 x 2
    demand / BE levels): RP over 4n scenarios.
  * Deterministic plan: expected-value problem with the sample-mean FE yield.
  * Bootstrap (Efron and Tibshirani 1993): B = 20 resamples of the n yields
    with replacement; the SAA plan of each resample; the bagged plan is the
    average of their wafer starts; the same resamples give the bootstrap
    estimate of the optimism of the in-sample VSS (Efron's optimism
    correction): o = mean_b[(VSS of resample b on b) - (same plans on the
    original sample)], bias-corrected VSS = in-sample VSS - o.
  * Optimality gap of the SAA plan: exact (truth known) and the Mak, Morton
    and Wood (1999) multiple-replication estimate a fab could compute:
    M = 20 batches of size n, gap_m = (batch optimum) - (SAA plan on the
    batch), one-sided 95% upper bound mean + t_{0.95,19} s / sqrt(20).
    Batches drawn (i) from the truth (the MMW setting) and (ii) as bootstrap
    resamples of the data (all a fab has). Coverage = share of replications
    whose exact gap lies below the bound.
Out-of-sample evaluation under the truth is EXACT: the recourse value of the
dies received, Q(D; demand, BE yield), is concave piecewise linear in D;
it is tabulated with the paper's builder (PuLP + CBC, one solve per integer D
in [0, 1800] for each of the four demand / BE-yield pairs and for the
expected-value pair), its pieces are recovered and validated against direct
solves at random non-integer D, and E[Q(n X Y)] is integrated in closed form
against the Beta density (regularised incomplete beta function). The SAA and
expected-value problems are then maximised exactly over total wafer starts
X in [0, 18] (the objective is piecewise linear in X; all breakpoints are
enumerated). Both are cross-checked against direct CBC solves of the full
model (solve_plan) and against the paper's baseline and the 7-point Beta
result in experiments/beta_experiment.py / beta_results.csv.

Not run: the optional Wasserstein DRO plan (see README).

    cd tsm-yield-thresholds && .venv/bin/python code/tsm_a/t5_limited_data.py [--smoke]
Outputs: results/tsm_a/t5_limited_data/{replications.csv, summary.csv, truth.csv,
         validation.csv, qtables.npz, run.json, log.txt}
"""
import csv
import os
import sys
import time

import numpy as np
from scipy.stats import beta as beta_dist
from scipy.stats import t as t_dist
from scipy.optimize import minimize_scalar

from tsa_common import (RESULTS, REPO, base_inst, scenarios_2x2x2, solve_plan, evaluate_plan,
                        ev_scenario, self_check, write_run_json)

SMOKE = "--smoke" in sys.argv
RUN_ID = "t5_limited_data"
SEED = 20261113
OUT = os.path.join(RESULTS, RUN_ID + ("_smoke" if SMOKE else ""))
SIGMAS = [0.075, 0.15]
NS = [5, 20] if SMOKE else [5, 10, 20, 50, 100]
R = 5 if SMOKE else 200
B = 20          # bootstrap resamples (bagging and optimism correction)
M_BATCH = 20    # MMW batches
MU = 0.875
INST = base_inst()
NDIE = INST["n_f_i"]
CF = INST["c_F"]
XCAP = sum(INST["L_F"].values())          # 18 wafers
DMAX = int(NDIE * XCAP)                    # 1800 dies
COMBOS = [(600.0, 0.70), (600.0, 0.90), (900.0, 0.70), (900.0, 0.90)]
EVCOMBO = (750.0, 0.80)


def beta_ab(mu, sigma):          # identical to experiments/beta_experiment.py
    t = mu * (1 - mu) / (sigma ** 2) - 1.0
    return mu * t, (1 - mu) * t


# ---------------------------------------------------------------------------
# recourse value tables
# ---------------------------------------------------------------------------
FIX = {"FE1": 10.0, "FE2": 8.0}


def q_direct(D, q, yb):
    """Recourse value of D in-house dies, by a direct CBC solve of the model."""
    sc = [{"name": "s", "prob": 1.0, "fe_yield": D / DMAX, "demand": q, "be_yield": yb}]
    r = solve_plan(INST, sc, fix_x=FIX, tag="Q")
    assert r["status"] == "Optimal"
    return r["obj"] + CF * XCAP


def build_table(q, yb):
    grid = np.arange(0, DMAX + 1, dtype=float)
    vals = np.array([q_direct(d, q, yb) for d in grid])
    sl = np.diff(vals)
    # group cells with equal slope; cells forming a run of >= 2 are pieces
    lines, k = [], 0
    while k < len(sl):
        j = k
        while j + 1 < len(sl) and abs(sl[j + 1] - sl[k]) < 1e-7:
            j += 1
        if j > k or k in (0, len(sl) - 1):
            lines.append((vals[k] - sl[k] * grid[k], sl[k]))
        k = j + 1
    # lower envelope breakpoints of min over lines on [0, DMAX]
    lines = sorted(lines, key=lambda t: -t[1])
    merged = []
    for a, s in lines:                      # one line per piece (slopes equal to 1e-6)
        if merged and abs(merged[-1][1] - s) < 1e-6:
            continue
        merged.append((a, s))
    lines = merged
    fine = np.linspace(0, DMAX, 72001)
    act = np.argmin(np.array([a + s * fine for a, s in lines]), axis=0)
    bx = [0.0]
    for i in range(1, len(fine)):
        if act[i] != act[i - 1]:
            (a1, s1), (a2, s2) = lines[act[i - 1]], lines[act[i]]
            bx.append((a2 - a1) / (s1 - s2))
    bx.append(float(DMAX))
    bx = np.array(sorted(set(min(max(x, 0.0), float(DMAX)) for x in bx)))
    by = np.array([min(a + s * d for a, s in lines) for d in bx])
    return bx, by, vals


def q_eval(table, D):
    bx, by = table
    return np.interp(D, bx, by)


# ---------------------------------------------------------------------------
# objectives
# ---------------------------------------------------------------------------
def saa_obj(tables, y, X):
    """F_n(X) for an array of X and a sample y (equal weights)."""
    D = NDIE * np.outer(X, y)
    tot = np.zeros(len(X))
    for c in COMBOS:
        tot += 0.25 * q_eval(tables[c], D).mean(axis=1)
    return -CF * X + tot


def candidates(tables, y):
    br = np.unique(np.concatenate([tables[c][0] for c in COMBOS]))
    yy = y[y > 0]
    cand = (br[None, :] / (NDIE * yy[:, None])).ravel()
    cand = cand[(cand >= 0) & (cand <= XCAP)]
    return np.unique(np.concatenate([cand, [0.0, XCAP]]))


def saa_solve(tables, y):
    X = candidates(tables, y)
    f = saa_obj(tables, y, X)
    i = int(np.flatnonzero(f >= f.max() - 1e-9)[0])
    return X[i], f[i]


def ev_solve(tables, ybar):
    bx, by = tables[EVCOMBO]
    X = np.unique(np.concatenate([bx / (NDIE * ybar), [0.0, XCAP]]))
    X = X[(X >= 0) & (X <= XCAP)]
    f = -CF * X + q_eval(tables[EVCOMBO], NDIE * ybar * X)
    i = int(np.flatnonzero(f >= f.max() - 1e-9)[0])
    return X[i]


def true_obj(tables, a, b, X):
    """F(X) = -c_F X + E[sum 0.25 Q(n X Y)], Y ~ Beta(a, b), exact."""
    if X <= 0:
        return sum(0.25 * q_eval(tables[c], 0.0) for c in COMBOS)
    mu = a / (a + b)
    c_ = NDIE * X
    tot = 0.0
    for cmb in COMBOS:
        bx, by = tables[cmb]
        yb = np.clip(bx / c_, 0, 1)
        F0 = beta_dist.cdf(yb, a, b)
        F1 = beta_dist.cdf(yb, a + 1, b)
        sl = np.diff(by) / np.diff(bx)
        icp = by[:-1] - sl * bx[:-1]
        tot += 0.25 * float(np.sum(icp * np.diff(F0) + sl * c_ * mu * np.diff(F1)))
    return -CF * X + tot


def summarize(v):
    v = np.asarray(v, dtype=float)
    m, s = v.mean(), v.std(ddof=1)
    h = 1.96 * s / np.sqrt(len(v))
    return m, m - h, m + h, np.percentile(v, 2.5), np.percentile(v, 97.5)


def main():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    log = open(os.path.join(OUT, "log.txt"), "w")

    def say(msg):
        print(msg, flush=True)
        log.write(msg + "\n")

    say(f"t5_limited_data ({'SMOKE' if SMOKE else 'FULL'}) -> {OUT}")
    say(f"self-check: max |dev| = {self_check():.2e}")

    # ---- tables ----------------------------------------------------------
    tables, raw = {}, {}
    for c in COMBOS + [EVCOMBO]:
        bx, by, vals = build_table(*c)
        tables[c] = (bx, by)
        raw[c] = vals
        say(f"Q table demand={c[0]:g} BE={c[1]:g}: {len(bx)} breakpoints at D = "
            + ", ".join(f"{x:.4f}" for x in bx))
    np.savez(os.path.join(OUT, "qtables.npz"),
             **{f"bx_{int(c[0])}_{c[1]:.2f}": tables[c][0] for c in tables},
             **{f"by_{int(c[0])}_{c[1]:.2f}": tables[c][1] for c in tables},
             **{f"grid_{int(c[0])}_{c[1]:.2f}": raw[c] for c in raw})

    # ---- validation ------------------------------------------------------
    val = []
    rng = np.random.default_rng(SEED)
    worst = 0.0
    for c in COMBOS + [EVCOMBO]:
        for D in rng.uniform(0, DMAX, 60 if SMOKE else 300):
            d = abs(q_eval(tables[c], D) - q_direct(D, *c))
            worst = max(worst, d)
    val.append(["pwl_table_vs_direct_cbc_max_abs", f"{worst:.3e}"])
    # paper baseline with the two-point FE sample {0.80, 0.95}
    y2 = np.array([0.80, 0.95])
    xs, zs = saa_solve(tables, y2)
    xd = ev_solve(tables, y2.mean())
    zd = saa_obj(tables, y2, np.array([xd]))[0]
    val += [["baseline_rp_obj", f"{zs:.2f}"], ["baseline_eev_obj", f"{zd:.2f}"],
            ["baseline_vss", f"{zs - zd:.2f}"], ["baseline_rp_wafers", f"{xs:.4f}"],
            ["baseline_ev_wafers", f"{xd:.4f}"]]
    # paper's 7-point Beta at sigma = 0.07 (beta_results.csv row equiv_full_spread 0.14)
    a7, b7 = beta_ab(MU, 0.07)
    y7 = np.array([beta_dist.ppf((k - 0.5) / 7, a7, b7) for k in range(1, 8)])
    x7, z7 = saa_solve(tables, y7)
    x7d = ev_solve(tables, y7.mean())
    v7 = z7 - saa_obj(tables, y7, np.array([x7d]))[0]
    val.append(["beta7_sigma0.07_vss (beta_results.csv: 92.0)", f"{v7:.3f}"])
    # SAA and EEV versus a direct CBC solve of the full model on random samples
    dev = 0.0
    for n in ([5, 20] if SMOKE else [5, 20, 100]):
        for r in range(2 if SMOKE else 3):
            a, b = beta_ab(MU, 0.15)
            y = np.random.default_rng([SEED, 99, n, r]).beta(a, b, n)
            xs_, zs_ = saa_solve(tables, y)
            sc = [{"name": f"y{j}_{q:g}_{yb:g}", "prob": 0.25 / n, "fe_yield": float(yv),
                   "demand": q, "be_yield": yb} for j, yv in enumerate(y) for (q, yb) in COMBOS]
            rp = solve_plan(INST, sc, tag="SAAchk")
            xd_ = ev_solve(tables, y.mean())
            ev = solve_plan(INST, ev_scenario(sc), tag="EVchk")
            eev = evaluate_plan(INST, sc, ev["X_F"])
            zd_ = saa_obj(tables, y, np.array([xd_]))[0]
            dev = max(dev, abs(rp["obj"] - zs_), abs(eev["exp_profit"] - zd_))
    val.append(["saa_and_eev_vs_full_cbc_max_abs", f"{dev:.3e}"])
    with open(os.path.join(OUT, "validation.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["check", "value"])
        w.writerows(val)
    for k, v in val:
        say(f"  VALIDATION {k} = {v}")
    if worst > 1e-3 or dev > 1e-3:   # CBC objective noise is ~1e-5; reported precision is $0.01
        say("VALIDATION FAILED")
        sys.exit(1)

    # ---- truth -----------------------------------------------------------
    truth_rows, truth = [], {}
    for si, sg in enumerate(SIGMAS):
        a, b = beta_ab(MU, sg)
        res = minimize_scalar(lambda X: -true_obj(tables, a, b, X), bounds=(0, XCAP),
                              method="bounded", options={"xatol": 1e-9})
        xstar, fstar = res.x, -res.fun
        # guard against a boundary optimum missed by the bounded search
        for xb in (0.0, XCAP):
            if true_obj(tables, a, b, xb) > fstar:
                xstar, fstar = xb, true_obj(tables, a, b, xb)
        xdstar = ev_solve(tables, MU)
        fd = true_obj(tables, a, b, xdstar)
        # Monte Carlo cross-check of the exact integral
        yy = np.random.default_rng([SEED, 7, si]).beta(a, b, 200000)
        mc = saa_obj(tables, yy, np.array([xstar]))[0]
        truth[sg] = (a, b, xstar, fstar, xdstar, fd)
        truth_rows.append({"sigma": sg, "beta_a": f"{a:.6f}", "beta_b": f"{b:.6f}",
                           "x_star_wafers": f"{xstar:.6f}", "F_star": f"{fstar:.4f}",
                           "x_det_true_mean": f"{xdstar:.6f}", "F_det": f"{fd:.4f}",
                           "true_vss": f"{fstar - fd:.4f}",
                           "true_pct_vss": f"{100 * (fstar - fd) / fstar:.4f}",
                           "mc200k_F_at_x_star": f"{mc:.4f}"})
        say(f"TRUTH sigma={sg}: x*={xstar:.4f} F*={fstar:.4f} x_det={xdstar:.4f} F_det={fd:.4f} "
            f"VSS*={fstar - fd:.4f} ({100 * (fstar - fd) / fstar:.3f}%), MC check {mc:.4f}")
    with open(os.path.join(OUT, "truth.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(truth_rows[0].keys()))
        w.writeheader()
        w.writerows(truth_rows)

    # ---- replications ----------------------------------------------------
    reps, summ = [], []
    tcrit = t_dist.ppf(0.95, M_BATCH - 1)
    for si, sg in enumerate(SIGMAS):
        a, b, xstar, fstar, xdstar, fd = truth[sg]
        for n in NS:
            tn = time.time()
            for r in range(R):
                rng = np.random.default_rng([SEED, si, n, r])
                y = rng.beta(a, b, n)
                xs, zs = saa_solve(tables, y)
                xd = ev_solve(tables, y.mean())
                zd = saa_obj(tables, y, np.array([xd]))[0]
                fs, fdd = true_obj(tables, a, b, xs), true_obj(tables, a, b, xd)
                # bootstrap: bagging + optimism of the in-sample VSS + MMW-bootstrap
                xb_list, opt_list, gb = [], [], []
                for _ in range(B):
                    yb = y[rng.integers(0, n, n)]
                    xb, zb = saa_solve(tables, yb)
                    xdb = ev_solve(tables, yb.mean())
                    zdb = saa_obj(tables, yb, np.array([xdb]))[0]
                    on_orig = saa_obj(tables, y, np.array([xb, xdb]))
                    opt_list.append((zb - zdb) - (on_orig[0] - on_orig[1]))
                    xb_list.append(xb)
                    gb.append(zb - saa_obj(tables, yb, np.array([xs]))[0])
                xbag = float(np.mean(xb_list))
                fbag = true_obj(tables, a, b, xbag)
                # MMW with batches from the truth
                gm = []
                for _ in range(M_BATCH):
                    ym = rng.beta(a, b, n)
                    _, zm = saa_solve(tables, ym)
                    gm.append(zm - saa_obj(tables, ym, np.array([xs]))[0])
                gm, gb = np.array(gm), np.array(gb)
                ub_m = gm.mean() + tcrit * gm.std(ddof=1) / np.sqrt(M_BATCH)
                ub_b = gb.mean() + tcrit * gb.std(ddof=1) / np.sqrt(B)
                gap = fstar - fs
                vss_in, vss_real = zs - zd, fs - fdd
                o_hat = float(np.mean(opt_list))
                reps.append({"sigma": sg, "n": n, "rep": r, "sample_mean": y.mean(),
                             "sample_sd": y.std(ddof=1),
                             "x_saa": xs, "x_det": xd, "x_bag": xbag,
                             "insample_rp": zs, "insample_eev": zd, "vss_in": vss_in,
                             "F_true_saa": fs, "F_true_det": fdd, "F_true_bag": fbag,
                             "vss_real": vss_real, "vss_real_bag": fbag - fdd,
                             "optimism_obj": zs - fs, "optimism_vss": vss_in - vss_real,
                             "boot_optimism_vss": o_hat, "vss_boot_corrected": vss_in - o_hat,
                             "gap_saa_exact": gap, "gap_det_exact": fstar - fdd,
                             "gap_bag_exact": fstar - fbag,
                             "mmw_truth_gap_mean": gm.mean(), "mmw_truth_ub95": ub_m,
                             "mmw_truth_covers": int(gap <= ub_m + 1e-9),
                             "mmw_boot_gap_mean": gb.mean(), "mmw_boot_ub95": ub_b,
                             "mmw_boot_covers": int(gap <= ub_b + 1e-9)})
            rows = [x for x in reps if x["sigma"] == sg and x["n"] == n]
            rec = {"sigma": sg, "n": n, "R": len(rows),
                   "true_vss": fstar - fd, "true_pct_vss": 100 * (fstar - fd) / fstar}
            for key in ("vss_in", "vss_real", "vss_real_bag", "vss_boot_corrected", "optimism_obj",
                        "optimism_vss", "gap_saa_exact", "gap_det_exact", "gap_bag_exact",
                        "mmw_truth_ub95", "mmw_boot_ub95", "x_saa"):
                m, lo, hi, p2, p97 = summarize([x[key] for x in rows])
                rec[f"{key}_mean"], rec[f"{key}_ci_lo"], rec[f"{key}_ci_hi"] = m, lo, hi
                rec[f"{key}_p2.5"], rec[f"{key}_p97.5"] = p2, p97
            rec["share_vss_real_negative"] = float(np.mean([x["vss_real"] < 0 for x in rows]))
            rec["share_vss_in_gt_2pct"] = float(np.mean([x["vss_in"] / x["insample_rp"] > 0.02 for x in rows]))
            rec["share_vss_real_gt_2pct"] = float(np.mean([x["vss_real"] / x["F_true_saa"] > 0.02 for x in rows]))
            rec["mmw_truth_coverage"] = float(np.mean([x["mmw_truth_covers"] for x in rows]))
            rec["mmw_boot_coverage"] = float(np.mean([x["mmw_boot_covers"] for x in rows]))
            summ.append(rec)
            say(f"  sigma={sg} n={n:>3d}: VSS*={rec['true_vss']:.2f} in-sample {rec['vss_in_mean']:.2f} "
                f"realized {rec['vss_real_mean']:.2f} [{rec['vss_real_ci_lo']:.2f},{rec['vss_real_ci_hi']:.2f}] "
                f"bagged {rec['vss_real_bag_mean']:.2f} boot-corr {rec['vss_boot_corrected_mean']:.2f} "
                f"gap_saa {rec['gap_saa_exact_mean']:.2f} gap_det {rec['gap_det_exact_mean']:.2f} "
                f"P(real<0)={rec['share_vss_real_negative']:.3f} cover MMW {rec['mmw_truth_coverage']:.3f} "
                f"boot {rec['mmw_boot_coverage']:.3f}  ({time.time() - tn:.0f} s)")

    with open(os.path.join(OUT, "replications.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(reps[0].keys()))
        w.writeheader()
        for x in reps:
            w.writerow({k: (f"{v:.6f}" if isinstance(v, float) else v) for k, v in x.items()})
    with open(os.path.join(OUT, "summary.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summ[0].keys()))
        w.writeheader()
        for x in summ:
            w.writerow({k: (f"{v:.6f}" if isinstance(v, float) else v) for k, v in x.items()})
    say(f"done in {time.time() - t0:.0f} s")
    log.close()
    write_run_json(OUT, RUN_ID + ("_smoke" if SMOKE else ""),
                   "cd tsm-yield-thresholds && .venv/bin/python code/tsm_a/t5_limited_data.py"
                   + (" --smoke" if SMOKE else ""), SEED, t0, time.time(),
                   {"R": R, "B": B, "M_batches": M_BATCH, "sigmas": SIGMAS, "n_values": NS,
                    "evaluation": "exact integration of the piecewise-linear recourse value against the Beta density"})


if __name__ == "__main__":
    main()
