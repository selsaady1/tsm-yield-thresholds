"""r4_randinst.py (T6; R2.4, R1.2, supports R1.0a): out-of-sample check on
random instances drawn by Latin hypercube over the Step 8 (Table S-IV) ranges.

Sampling (scipy.stats.qmc.LatinHypercube, seed 20261113, one stratum per
instance in every dimension):
  c_K = c_D        log-uniform [0.01, 0.50]   ($/unit)
  c_F              log-uniform [0.5, 150]     ($/wafer)
  c_G              uniform     [0.5, 4.0]     ($/die)
  v                uniform     [1, 8]         ($/device)
  demand scale s   uniform     [0.8, 1.2]     (on the 750 mean)
  demand half dd   uniform     [0, 300]       (demand = s*(750 -/+ dd))
  FE capacity      uniform     [0.6, 1.5] x (10, 8) wafers
  BE capacity      uniform     [0.8, 1.5] x (500, 400) dies
  L_G              uniform     [0, 600]       dies
  FE mean ybar     uniform     [0.70, 0.95]
  BE mean          uniform     [0.70, 0.90], BE half-range 0.10
Other data (n, p, c_B, c_A, L_A, 2x2x2 equiprobable scenarios) as in the base.
Log-uniform is used for the two factors whose Step 8 range spans more than an
order of magnitude.

Per instance:
  rho        = (N_max - L_G)/N_bar from solves (N_max: repo max_die_requirement;
               N_bar = n * ybar * W_EV of the zero-spread expected-value plan);
  pred_onset = closed form of eq. (cliff): (1-rho)*ybar in the symmetric regime,
               ybar - rho/(2-rho) once the upper yield is clipped at 1;
  sweep      = FE half-range 0.01..0.50 (step 0.01), RP vs EEV (the paper's grid);
  thr2       = %VSS = 2% crossing: first grid bracket, then bisection to 1e-4;
  onset      = service gap > 1e-6: first grid bracket, then bisection to 1e-5.
Instance 0 is the base instance (sanity check, not counted in the 200).

    nice -n 10 python code/tsm_d/r4_randinst.py --n 200 --workers 2 [--smoke]
"""
import argparse, csv, json, math, os, sys, time
from multiprocessing import Pool
import numpy as np
from scipy.stats import qmc
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tsmd_common as T
rc = T.rc
T.patch_clamp_fixed_first_stage()

SEED = 20261113
GAP_TOL = 1e-6
HALVES = rc.HALF_GRID                      # 0.01 .. 0.50
BASE = rc.base_inst()
NAMES = ["hold", "c_F", "c_G", "v", "dem_scale", "dem_half", "fe_cap", "be_cap", "L_G", "fe_mean", "be_mean"]


def sample(n, seed=SEED):
    u = qmc.LatinHypercube(d=len(NAMES), seed=seed).random(n)
    logu = lambda x, a, b: float(math.exp(math.log(a) + x * (math.log(b) - math.log(a))))
    lin = lambda x, a, b: float(a + x * (b - a))
    out = []
    for i, r in enumerate(u, start=1):
        out.append({"id": i, "hold": logu(r[0], 0.01, 0.50), "c_F": logu(r[1], 0.5, 150.0),
                    "c_G": lin(r[2], 0.5, 4.0), "v": lin(r[3], 1.0, 8.0),
                    "dem_scale": lin(r[4], 0.8, 1.2), "dem_half": lin(r[5], 0.0, 300.0),
                    "fe_cap": lin(r[6], 0.6, 1.5), "be_cap": lin(r[7], 0.8, 1.5),
                    "L_G": lin(r[8], 0.0, 600.0), "fe_mean": lin(r[9], 0.70, 0.95),
                    "be_mean": lin(r[10], 0.70, 0.90)})
    return out


def base_params():
    return {"id": 0, "hold": 0.05, "c_F": 1.5, "c_G": 1.65, "v": 3.0, "dem_scale": 1.0, "dem_half": 150.0,
            "fe_cap": 1.0, "be_cap": 1.0, "L_G": 300.0, "fe_mean": rc.FE_MEAN, "be_mean": 0.80}


def build(p):
    inst = rc.base_inst(c_K=p["hold"], c_D=p["hold"], c_F=p["c_F"], c_G=p["c_G"], v_d=p["v"],
                        demand_lo=p["dem_scale"] * (750 - p["dem_half"]),
                        demand_hi=p["dem_scale"] * (750 + p["dem_half"]),
                        L_F={k: v * p["fe_cap"] for k, v in BASE["L_F"].items()},
                        L_B={k: v * p["be_cap"] for k, v in BASE["L_B"].items()},
                        L_G={"G1": p["L_G"]})
    return inst, p["fe_mean"], round(p["be_mean"] - 0.10, 6), round(p["be_mean"] + 0.10, 6)


def bisect(f, a, b, tol):
    """f(a) False, f(b) True -> boundary."""
    while b - a > tol:
        m = 0.5 * (a + b)
        if f(m):
            b = m
        else:
            a = m
    return 0.5 * (a + b)


def run_instance(p):
    t0 = time.time()
    inst, ybar, bl, bh = build(p)
    nonopt = 0
    ev_ = lambda h: rc.evaluate(inst, *rc.two_point(ybar, h), bl, bh)
    # rho from the zero-spread deterministic plan
    n_max = rc.max_die_requirement(inst, bl, bh)
    ev0 = rc.evaluate(inst, ybar, ybar, bl, bh)
    nonopt += 0 if ev0["ok"] else 1
    w_ev = ev0["ev_fe1"] + ev0["ev_fe2"]
    n_bar = inst["n_f_i"] * ybar * w_ev
    l_g = p["L_G"]
    rho = (n_max - l_g) / n_bar if n_bar > 1e-9 else float("inf")
    if rho <= 0:
        pred_h, pred_ylo, preg = None, None, "none_rho_le_0"
    elif not math.isfinite(rho):
        pred_h, pred_ylo, preg = None, None, "none_no_inhouse_wafers"
    elif (1 - rho) * ybar <= 1 - ybar + 1e-12:
        pred_ylo, preg = rho * ybar, "symmetric"
        pred_h = max(0.0, ybar - pred_ylo)
    else:
        pred_ylo, preg = rho / (2 - rho), "clipped"
        pred_h = max(0.0, ybar - pred_ylo)
    # sweep on the paper grid
    rows = []
    for h in HALVES:
        r = ev_(h)
        nonopt += 0 if r["ok"] else 1
        rows.append((h, r["pct_vss"], r["unmet_gap"], r["rp_obj"], r["vss"], r["eev_unmet"],
                     r["rp_fe1"] + r["rp_fe2"] - r["ev_fe1"] - r["ev_fe2"]))
    pct = [x[1] for x in rows]
    n_cross = sum(1 for a, b in zip(pct, pct[1:]) if (a < 2.0) != (b < 2.0))
    # 2 % threshold
    if pct[0] >= 2.0:
        thr_cls, thr, thr_lin = "always", None, None
    else:
        thr_cls, thr, thr_lin = "never", None, None
        for (h0, p0, *_), (h1, p1, *_) in zip(rows, rows[1:]):
            if p0 < 2.0 <= p1:
                thr_cls = "threshold"
                thr_lin = h0 + (2.0 - p0) / (p1 - p0) * (h1 - h0)
                thr = bisect(lambda h: ev_(h)["pct_vss"] >= 2.0, h0, h1, 1e-4)
                break
    # service-gap onset
    onset, prev = None, 0.0
    for h, _, g, *_ in rows:
        if g > GAP_TOL:
            onset = bisect(lambda x: ev_(x)["unmet_gap"] > GAP_TOL, prev, h, 1e-5)
            break
        prev = h
    # onset of the deterministic plan's own extra loss of sales (what eq. (cliff) states)
    eev0 = ev0["eev_unmet"]
    eev_loss, prev = None, 0.0
    for h, _, _, _, _, eu, _ in rows:
        if eu > eev0 + GAP_TOL:
            eev_loss = bisect(lambda x: ev_(x)["eev_unmet"] > eev0 + GAP_TOL, prev, h, 1e-5)
            break
        prev = h
    hedge = {round(x[0], 2): x[6] for x in rows}
    rec = dict(p)
    rec.update({"ybar": ybar, "be_lo": bl, "be_hi": bh,
                "demand_lo": inst["demand_lo"], "demand_hi": inst["demand_hi"],
                "N_max": n_max, "N_bar": n_bar, "W_EV": w_ev, "rho": rho,
                "pred_onset_half": pred_h, "pred_onset_ylo": pred_ylo, "pred_regime": preg,
                "solved_onset_half": onset, "eev_loss_onset_half": eev_loss,
                "rp_hedge_wafers_at_0.01": hedge[0.01], "rp_hedge_wafers_at_0.25": hedge[0.25],
                "solved_onset_ylo": None if onset is None else rc.two_point(ybar, onset)[0],
                "thr2_class": thr_cls, "thr2_half": thr, "thr2_half_linear": thr_lin,
                "thr2_ylo": None if thr is None else rc.two_point(ybar, thr)[0],
                "n_crossings_2pct": n_cross,
                "pct_vss_at_0.01": pct[0], "pct_vss_at_0.50": pct[-1], "pct_vss_max": max(pct),
                "gap_at_0.50": rows[-1][2], "min_rp_obj": min(x[3] for x in rows),
                "nonoptimal": nonopt, "runtime_s": round(time.time() - t0, 2)})
    return rec


def fmt(v):
    if v is None:
        return "NA"
    if isinstance(v, float):
        return "inf" if v == float("inf") else f"{v:.6f}"
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    run = "tsmd_r4_randinst" + ("_smoke" if a.smoke else "")
    t0, started = time.time(), T.now()
    d = T.run_dir(run)
    params = sample(a.n)
    todo = [base_params()] + (params[:3] if a.smoke else params)
    with open(os.path.join(d, "instances_sampled.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["id"] + NAMES)
        w.writeheader(); w.writerows(todo)
    log = open(os.path.join(d, "progress.log"), "w")
    log.write(f"{T.now()} start: {len(todo)} instances, {a.workers} workers, seed {SEED}\n"); log.flush()
    recs = []
    jl = open(os.path.join(d, "instances_results.jsonl"), "w")
    with Pool(a.workers) as pool:
        for k, rec in enumerate(pool.imap_unordered(run_instance, todo), start=1):
            recs.append(rec)
            jl.write(json.dumps({kk: (None if (isinstance(vv, float) and not math.isfinite(vv)) else vv)
                                 for kk, vv in rec.items()}) + "\n"); jl.flush()
            log.write(f"{T.now()} {k}/{len(todo)} id={rec['id']} rho={rec['rho']:.4f} "
                      f"pred={fmt(rec['pred_onset_half'])} onset={fmt(rec['solved_onset_half'])} "
                      f"thr2={rec['thr2_class']}:{fmt(rec['thr2_half'])} ({rec['runtime_s']} s)\n")
            log.flush()
    jl.close()
    recs.sort(key=lambda r: r["id"])
    p_csv = os.path.join(d, "instances_results.csv")
    with open(p_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(recs[0]))
        w.writeheader()
        for r in recs:
            w.writerow({k: fmt(v) for k, v in r.items()})
    nonopt = sum(r["nonoptimal"] for r in recs)
    log.write(f"{T.now()} done; non-optimal solves {nonopt}\n"); log.close()
    T.write_run_json(run, "T6 (R2.4, R1.2, R1.0a): random instances by Latin hypercube; rho cliff check and 2% threshold per instance",
                     f"nice -n 10 python code/tsm_d/r4_randinst.py --n {a.n} --workers {a.workers}" + (" --smoke" if a.smoke else ""),
                     SEED, started, t0, "OK" if nonopt == 0 else "PARTIAL", T.MODEL_FILES,
                     [os.path.join(d, "instances_sampled.csv"), p_csv, os.path.join(d, "instances_results.jsonl")],
                     [os.path.abspath(__file__)] + T.MODEL_FILES,
                     notes=f"instance 0 = base instance (sanity check, excluded from the {a.n}); non-optimal solves: {nonopt}; "
                           "EEV first stage clamped to [0, L_F] before fixing (tsmd_common.patch_clamp_fixed_first_stage) because PuLP reads "
                           "CBC solutions at limited precision and fractional capacities otherwise made EEV infeasible in an earlier attempt (842 non-optimal solves, superseded)")


if __name__ == "__main__":
    main()
