"""
param_sensitivity_revision.py
=============================
Revision-round experiment: how far do the planning-approach thresholds move
when the frozen instance parameters are changed one factor at a time, and
where does the "0.17-0.18 half-range  <->  ~70% worst-case FE yield"
correspondence come from?

Real solves only (PuLP + CBC, same model as src/step2_freeze_model.py; the
builder in revision_common.py is asserted to reproduce step2's objectives
before anything else runs). Nothing here is hard-coded as a result.

Parts
-----
A. One-factor-at-a-time (OFAT) sweeps. For every level of every factor the
   50-level FE half-range sweep of Step 6 is re-run and the crossings of
   %VSS = 2%, %VSS = 1.5% and service gap = 1 unit are located by linear
   interpolation (same rule as Step 5/6). Factors: holding cost, in-house
   wafer cost, outsourced-die cost, shortage penalty, demand level, demand
   spread, FE capacity, BE capacity, outsourced-FE capacity, FE mean, BE mean.

B. Mean / spread parameterisation study (the 70% mapping). For a range of
   nominal FE means, the crossing is reported as a half-range, as a
   worst-case yield and as the ratio worst-case / realised mean, and each
   crossing is labelled symmetric (upper yield < 1) or clipped (upper yield
   saturated at 1.00). The solver-located onset of the service gap is
   compared with the closed-form condition
        y_lo / mean  <  rho = (N_max - L_G) / N_bar
   where N_bar is the die requirement of the expected-value plan, N_max the
   largest die requirement over (demand, BE yield) and L_G the outsourced
   FE capacity (all three taken from solves, not assumed).

C. Strict three-stage (non-anticipative) variant of Experiments A and B.

D. Load-balancing check: both fabs forced to equal utilisation.

E. Beta (continuous) FE yield: lowest support point at the 2% crossing.

Usage
-----
    PYTHONPATH=src:experiments python experiments/param_sensitivity_revision.py --smoke
    PYTHONPATH=src:experiments python experiments/param_sensitivity_revision.py

Outputs (results/Revision/ParamSensitivity/, or .../smoke/ with --smoke)
    ofat_thresholds.csv, ofat_sweep_points.csv, mean_mapping.csv,
    na_variant.csv, balanced_load_check.csv, beta_tail.csv,
    fig_param_sensitivity.png, fig_mean_mapping.png, summary.txt
"""

import csv
import os
import sys
import time

import numpy as np
from scipy.stats import beta as beta_dist

from revision_common import (FE_MEAN, BE_LO, BE_HI, HALF_GRID, base_inst,
                             two_point, evaluate, evaluate_scenarios, sweep,
                             crossing, self_check, max_die_requirement,
                             solve_model, scenarios_2x2x2)

SMOKE = "--smoke" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "results", "Revision", "ParamSensitivity")
if SMOKE:
    OUT = os.path.join(OUT, "smoke")
os.makedirs(OUT, exist_ok=True)

HALVES = HALF_GRID[1::2] if SMOKE else HALF_GRID      # 0.02 step for the smoke run
BASE = base_inst()
FAILED = []                                           # (part, label) of non-optimal solves


def scaled(d, m):
    return {k: v * m for k, v in d.items()}


def thin(levels):
    """Smoke grid: first, base-nearest and last level only."""
    if not SMOKE or len(levels) <= 3:
        return levels
    return [levels[0], levels[len(levels) // 2], levels[-1]]


# ---------------------------------------------------------------------------
# Part A: OFAT factor definitions.  Each level: (numeric level, overrides,
# fe_mean, (be_lo, be_hi)).  `base` is the value in the frozen instance.
# ---------------------------------------------------------------------------
def factor_table():
    F = []

    def add(key, label, unit, base, levels, make):
        F.append({"key": key, "label": label, "unit": unit, "base": base,
                  "levels": [(lv,) + make(lv) for lv in thin(levels)]})

    std = lambda over: (over, FE_MEAN, (BE_LO, BE_HI))
    add("holding", "Holding cost $c_K=c_D$", "$/unit", 0.05,
        [0.01, 0.025, 0.05, 0.10, 0.25, 0.50],
        lambda v: std({"c_K": v, "c_D": v}))
    add("wafer_cost", "In-house wafer cost $c_F$", "$/wafer", 1.5,
        [0.5, 1.5, 5.0, 15.0, 50.0, 100.0, 150.0],
        lambda v: std({"c_F": v}))
    add("outs_die_cost", "Outsourced die cost $c_G$", "$/die", 1.65,
        [0.5, 1.0, 1.65, 2.5, 4.0],
        lambda v: std({"c_G": v}))
    add("penalty", "Shortage penalty $v_d$", "$/device", 3.0,
        [1.0, 3.0, 5.0, 8.0],
        lambda v: std({"v_d": v}))
    add("demand_level", "Demand level (scale on 600/900)", "x", 1.0,
        [0.80, 0.90, 1.00, 1.10, 1.20],
        lambda m: std({"demand_lo": 600 * m, "demand_hi": 900 * m}))
    add("demand_spread", "Demand half-range around 750", "units", 150.0,
        [0.0, 75.0, 150.0, 225.0, 300.0],
        lambda d: std({"demand_lo": 750 - d, "demand_hi": 750 + d}))
    add("fe_capacity", "FE capacity (scale on 10/8 wafers)", "x", 1.0,
        [0.60, 0.80, 1.00, 1.25, 1.50],
        lambda m: std({"L_F": scaled(BASE["L_F"], m)}))
    add("be_capacity", "BE capacity (scale on 500/400)", "x", 1.0,
        [0.80, 0.90, 1.00, 1.10, 1.25, 1.50],
        lambda m: std({"L_B": scaled(BASE["L_B"], m)}))
    add("outs_fe_capacity", "Outsourced FE capacity $L_G$", "dies", 300.0,
        [0.0, 150.0, 300.0, 450.0, 600.0],
        lambda c: std({"L_G": {"G1": c}}))
    add("fe_mean", "Nominal FE mean yield", "", 0.875,
        [0.70, 0.75, 0.80, 0.82, 0.85, 0.875, 0.90, 0.92],
        lambda m: ({}, m, (BE_LO, BE_HI)))
    add("be_mean", "BE mean yield (spread 0.20)", "", 0.80,
        [0.70, 0.75, 0.80, 0.85, 0.90],
        lambda m: ({}, FE_MEAN, (round(m - 0.10, 4), round(m + 0.10, 4))))
    return F


def fmt(x, nd=4):
    return "NA" if x is None else f"{x:.{nd}f}"


def cross_fields(rows, metric, level, prefix):
    c = crossing(rows, metric, level)
    if c is None:
        return {f"{prefix}_half": "NA", f"{prefix}_ylo": "NA",
                f"{prefix}_truemean": "NA", f"{prefix}_regime": "no_crossing"}
    if c["half"] is None:
        return {f"{prefix}_half": "NA", f"{prefix}_ylo": "NA",
                f"{prefix}_truemean": "NA", f"{prefix}_regime": "above_at_first_grid_point"}
    return {f"{prefix}_half": fmt(c["half"]), f"{prefix}_ylo": fmt(c["y_lo"]),
            f"{prefix}_truemean": fmt(c["true_mean"]),
            f"{prefix}_regime": "clipped" if c["clipped"] else "symmetric"}


def run_ofat():
    thr_rows, pt_rows = [], []
    for fac in factor_table():
        for (lv, over, fe_mean, (bl, bh)) in fac["levels"]:
            inst = base_inst(**over)
            rows = sweep(inst, fe_mean=fe_mean, be_lo=bl, be_hi=bh, halves=HALVES)
            bad = [r for r in rows if not r["ok"]]
            if bad:
                FAILED.append(("ofat", f"{fac['key']}={lv} ({len(bad)} points)"))
            good = [r for r in rows if r["ok"]]
            first = good[0] if good else None
            rec = {"factor": fac["key"], "level": lv, "base_level": fac["base"],
                   "is_base": int(abs(lv - fac["base"]) < 1e-12),
                   "fe_mean_nominal": fe_mean, "n_points": len(good),
                   "pct_vss_at_first_point": fmt(first["pct_vss"]) if first else "NA",
                   "pct_vss_max": fmt(max(r["pct_vss"] for r in good)) if good else "NA",
                   "gap_max": fmt(max(r["unmet_gap"] for r in good)) if good else "NA"}
            rec.update(cross_fields(rows, "pct_vss", 2.0, "vss2"))
            rec.update(cross_fields(rows, "pct_vss", 1.5, "vss15"))
            rec.update(cross_fields(rows, "unmet_gap", 1.0, "gap1"))
            thr_rows.append(rec)
            for r in good:
                pt_rows.append({"factor": fac["key"], "level": lv, "half": r["half"],
                                "fe_lo": fmt(r["fe_lo"]), "fe_hi": fmt(r["fe_hi"]),
                                "clipped": r["clipped"],
                                "rp_obj": fmt(r["rp_obj"], 3), "eev_obj": fmt(r["eev_obj"], 3),
                                "vss": fmt(r["vss"], 3), "pct_vss": fmt(r["pct_vss"]),
                                "unmet_gap": fmt(r["unmet_gap"]),
                                "rp_wafers": fmt(r["rp_fe1"] + r["rp_fe2"]),
                                "ev_wafers": fmt(r["ev_fe1"] + r["ev_fe2"]),
                                "eev_exp_outsourced_dies": fmt(r["eev_exp_outs"], 2),
                                "rp_exp_outsourced_dies": fmt(r["rp_exp_outs"], 2)})
            print(f"  OFAT {fac['key']:>17s} = {lv:<7g}  2%: half={rec['vss2_half']:>6s} "
                  f"ylo={rec['vss2_ylo']:>6s} [{rec['vss2_regime']}]   "
                  f"gap>1: half={rec['gap1_half']:>6s} [{rec['gap1_regime']}]", flush=True)
    return thr_rows, pt_rows


# ---------------------------------------------------------------------------
# Part B: mean / spread parameterisation and the closed-form cliff condition
# ---------------------------------------------------------------------------
def gap_onset(inst, fe_mean, hi_cap=0.50, tol=1e-4):
    """Largest half-range with zero service gap (bisection on real solves)."""
    def gap(h):
        lo, hi = two_point(fe_mean, h)
        return evaluate(inst, lo, hi)["unmet_gap"]
    a, b = 0.0, hi_cap
    if gap(b) <= 1e-6:
        return None
    while b - a > tol:
        m = 0.5 * (a + b)
        if gap(m) > 1e-6:
            b = m
        else:
            a = m
    return 0.5 * (a + b)


def run_mean_mapping():
    inst = BASE
    n_max = max_die_requirement(inst)
    ev = evaluate(inst, FE_MEAN, FE_MEAN)            # zero FE spread: EV die requirement
    n_bar = ev["ev_dies_used"]
    l_g = sum(inst["L_G"].values())
    rho = (n_max - l_g) / n_bar
    means = thin([0.70, 0.75, 0.80, 0.82, 0.85, 0.875, 0.90, 0.92, 0.95])
    out = []
    for m in means:
        rows = sweep(inst, fe_mean=m, halves=HALVES)
        c2 = crossing(rows, "pct_vss", 2.0)
        h_on = gap_onset(inst, m)
        rec = {"fe_mean_nominal": m, "N_bar": fmt(n_bar, 2), "N_max": fmt(n_max, 2),
               "L_G": l_g, "rho": fmt(rho),
               "clip_starts_at_half": fmt(1.0 - m)}
        # solver-located service-gap onset
        if h_on is None:
            rec.update({"onset_half": "NA", "onset_ylo": "NA", "onset_ratio": "NA",
                        "onset_regime": "no_onset"})
        else:
            lo, hi = two_point(m, h_on)
            rec.update({"onset_half": fmt(h_on), "onset_ylo": fmt(lo),
                        "onset_ratio": fmt(lo / ((lo + hi) / 2)),
                        "onset_regime": "clipped" if m + h_on > 1 else "symmetric"})
        # closed-form prediction of the onset
        pred_sym = rho * m                           # y_lo = rho * mean  (upper yield < 1)
        pred_clip = rho / (2.0 - rho)                # y_lo = rho (y_lo + 1) / 2
        symmetric_valid = (m + (m - pred_sym)) <= 1.0 + 1e-12
        rec["pred_onset_ylo"] = fmt(pred_sym if symmetric_valid else pred_clip)
        rec["pred_regime"] = "symmetric" if symmetric_valid else "clipped"
        # %VSS = 2% crossing
        if c2 is None or c2["half"] is None:
            rec.update({"vss2_half": "NA", "vss2_ylo": "NA", "vss2_ratio": "NA",
                        "vss2_regime": "no_crossing" if c2 is None else "above_at_first_grid_point"})
        else:
            rec.update({"vss2_half": fmt(c2["half"]), "vss2_ylo": fmt(c2["y_lo"]),
                        "vss2_ratio": fmt(c2["y_lo"] / c2["true_mean"]),
                        "vss2_regime": "clipped" if c2["clipped"] else "symmetric"})
        out.append(rec)
        print(f"  MEAN {m:.3f}: onset ylo={rec['onset_ylo']} (pred {rec['pred_onset_ylo']}, "
              f"{rec['onset_regime']})  2%: half={rec['vss2_half']} ylo={rec['vss2_ylo']} "
              f"ratio={rec['vss2_ratio']} [{rec['vss2_regime']}]", flush=True)
    return out, {"N_bar": n_bar, "N_max": n_max, "L_G": l_g, "rho": rho}


# ---------------------------------------------------------------------------
# Part C: strict three-stage (non-anticipative) variant
# ---------------------------------------------------------------------------
def run_na_variant():
    out = []
    for na in (False, True):
        tagm = "three_stage_nonanticipative" if na else "as_solved_in_paper"
        rows = sweep(BASE, halves=HALVES, nonanticipative=na)
        for r in rows:
            out.append({"model": tagm, "experiment": "A_FE_sweep", "half": r["half"],
                        "rp_obj": fmt(r["rp_obj"], 3), "eev_obj": fmt(r["eev_obj"], 3),
                        "vss": fmt(r["vss"], 3), "pct_vss": fmt(r["pct_vss"]),
                        "unmet_gap": fmt(r["unmet_gap"]),
                        "rp_wafers": fmt(r["rp_fe1"] + r["rp_fe2"]),
                        "ev_wafers": fmt(r["ev_fe1"] + r["ev_fe2"])})
        cA = {name: crossing(rows, met, lv) for name, met, lv in
              [("vss2", "pct_vss", 2.0), ("vss15", "pct_vss", 1.5),
               ("gap1", "unmet_gap", 1.0), ("gap3", "unmet_gap", 3.0), ("vss150", "vss", 150.0)]}
        print(f"  NA={na}  Exp A crossings (half): " + ", ".join(
            f"{k}={'NA' if c is None else ('below_grid' if c['half'] is None else fmt(c['half']))}"
            for k, c in cA.items()), flush=True)
        # Experiment B: BE half-range sweep at FE 0.80-0.95
        rowsB = []
        for h in HALVES:
            bl, bh = two_point(0.80, h)
            r = evaluate(BASE, 0.80, 0.95, bl, bh, nonanticipative=na)
            r["half"] = h
            r["fe_mean_nominal"] = 0.80          # crossing() uses it only to rebuild (lo, hi)
            rowsB.append(r)
            out.append({"model": tagm, "experiment": "B_BE_sweep", "half": h,
                        "rp_obj": fmt(r["rp_obj"], 3), "eev_obj": fmt(r["eev_obj"], 3),
                        "vss": fmt(r["vss"], 3), "pct_vss": fmt(r["pct_vss"]),
                        "unmet_gap": fmt(r["unmet_gap"]),
                        "rp_wafers": fmt(r["rp_fe1"] + r["rp_fe2"]),
                        "ev_wafers": fmt(r["ev_fe1"] + r["ev_fe2"])})
        pcts = [r["pct_vss"] for r in rowsB]
        cB = crossing(rowsB, "pct_vss", 2.0)
        print(f"  NA={na}  Exp B: %VSS range {min(pcts):.3f}..{max(pcts):.3f}, "
              f"max gap {max(r['unmet_gap'] for r in rowsB):.3f}, 2% crossing BE half = "
              f"{'none' if cB is None else ('below_grid' if cB['half'] is None else fmt(cB['half']))}",
              flush=True)
    return out


# ---------------------------------------------------------------------------
# Part D: load-balancing check
# ---------------------------------------------------------------------------
def run_balance():
    out = []
    for h in ([0.075, 0.25] if SMOKE else [0.01, 0.075, 0.15, 0.178, 0.25, 0.35]):
        lo, hi = two_point(FE_MEAN, h)
        free = evaluate(BASE, lo, hi)
        bal = evaluate(BASE, lo, hi, balance_fe=True)
        lf = BASE["L_F"]
        out.append({
            "half": h,
            "rp_obj_free": fmt(free["rp_obj"], 3), "rp_obj_balanced": fmt(bal["rp_obj"], 3),
            "eev_obj_free": fmt(free["eev_obj"], 3), "eev_obj_balanced": fmt(bal["eev_obj"], 3),
            "rp_util_fe1_free": fmt(free["rp_fe1"] / lf["FE1"]), "rp_util_fe2_free": fmt(free["rp_fe2"] / lf["FE2"]),
            "rp_util_fe1_bal": fmt(bal["rp_fe1"] / lf["FE1"]), "rp_util_fe2_bal": fmt(bal["rp_fe2"] / lf["FE2"]),
            "ev_util_fe1_free": fmt(free["ev_fe1"] / lf["FE1"]), "ev_util_fe2_free": fmt(free["ev_fe2"] / lf["FE2"]),
            "ev_util_fe1_bal": fmt(bal["ev_fe1"] / lf["FE1"]), "ev_util_fe2_bal": fmt(bal["ev_fe2"] / lf["FE2"]),
            "rp_wafers_free": fmt(free["rp_fe1"] + free["rp_fe2"]), "rp_wafers_bal": fmt(bal["rp_fe1"] + bal["rp_fe2"]),
            "pct_vss_free": fmt(free["pct_vss"]), "pct_vss_balanced": fmt(bal["pct_vss"])})
        print(f"  BAL half={h}: RP {free['rp_obj']:.3f} vs balanced {bal['rp_obj']:.3f}; "
              f"EEV {free['eev_obj']:.3f} vs {bal['eev_obj']:.3f}; RP util balanced "
              f"{bal['rp_fe1']/lf['FE1']:.3f}/{bal['rp_fe2']/lf['FE2']:.3f}", flush=True)
    return out


# ---------------------------------------------------------------------------
# Part E: Beta FE yield, lowest support point at the 2% crossing
# ---------------------------------------------------------------------------
def beta_points(mu, sigma, K=7):
    t = mu * (1 - mu) / sigma ** 2 - 1.0
    a, b = mu * t, (1 - mu) * t
    qs = (np.arange(1, K + 1) - 0.5) / K
    return [float(beta_dist.ppf(q, a, b)) for q in qs]


def run_beta_tail(mu=FE_MEAN, K=7):
    out, prev = [], None
    cross_sigma = None
    sig_grid = np.round(np.arange(0.02, 0.2501, 0.02 if SMOKE else 0.005), 4)
    for sigma in sig_grid:
        pts = beta_points(mu, sigma, K)
        sc = [{"name": f"F{i}_{dn}_{bn}", "prob": 0.25 / K, "fe_yield": fv, "demand": dv, "be_yield": bv}
              for i, fv in enumerate(pts)
              for dn, dv in (("Dlo", BASE["demand_lo"]), ("Dhi", BASE["demand_hi"]))
              for bn, bv in (("BElo", BE_LO), ("BEhi", BE_HI))]
        r = evaluate_scenarios(BASE, sc)
        disc_mean = float(np.mean(pts))
        out.append({"sigma": sigma, "equiv_half_range": sigma, "pct_vss": fmt(r["pct_vss"]),
                    "unmet_gap": fmt(r["unmet_gap"]), "lowest_point": fmt(pts[0]),
                    "second_lowest_point": fmt(pts[1]), "highest_point": fmt(pts[-1]),
                    "discretised_mean": fmt(disc_mean),
                    "lowest_over_mean": fmt(pts[0] / disc_mean)})
        if prev is not None and prev[1] < 2.0 <= r["pct_vss"] and cross_sigma is None:
            t = (2.0 - prev[1]) / (r["pct_vss"] - prev[1])
            cross_sigma = prev[0] + t * (sigma - prev[0])
        prev = (sigma, r["pct_vss"])
    info = {}
    if cross_sigma is not None:
        pts = beta_points(mu, cross_sigma, K)
        info = {"cross_sigma": cross_sigma, "lowest_point": pts[0], "second_lowest": pts[1],
                "disc_mean": float(np.mean(pts))}
        print(f"  BETA 2% crossing at sigma={cross_sigma:.4f}: lowest of {K} points = {pts[0]:.4f}, "
              f"second = {pts[1]:.4f}, discretised mean = {np.mean(pts):.4f}", flush=True)
    return out, info


# ---------------------------------------------------------------------------
def write_csv(name, rows):
    if not rows:
        return
    path = os.path.join(OUT, name)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {path} ({len(rows)} rows)")


def num(x):
    return None if x in ("NA", None) else float(x)


def make_figures(thr, mapping, consts):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8,
                         "legend.fontsize": 7.5, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "figure.dpi": 200})
    C2, CG, CB = "#1f5fa8", "#c0392b", "#555555"

    SHORT = {"holding": "Holding cost\n$c_K=c_D$ (\\$/unit)",
             "wafer_cost": "In-house wafer cost\n$c_F$ (\\$/wafer)",
             "outs_die_cost": "Outsourced die cost\n$c_G$ (\\$/die)",
             "penalty": "Shortage penalty\n$v_d$ (\\$/device)",
             "demand_level": "Demand level\n(scale on 600/900)",
             "demand_spread": "Demand half-range\naround 750 (units)",
             "fe_capacity": "In-house FE capacity\n(scale on 10/8 wafers)",
             "be_capacity": "In-house BE capacity\n(scale on 500/400)",
             "outs_fe_capacity": "Outsourced FE capacity\n$L_G$ (dies)",
             "be_mean": "BE mean yield\n(BE spread 0.20)"}
    facs = [f for f in factor_table() if f["key"] not in ("fe_mean",)]
    ncol = 5
    nrow = int(np.ceil(len(facs) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(7.2, 1.95 * nrow + 0.35), sharey=True)
    axes = np.atleast_2d(axes)
    for ax in axes.flat:
        ax.set_visible(False)
    for ax, fac in zip(axes.flat, facs):
        ax.set_visible(True)
        rows = [r for r in thr if r["factor"] == fac["key"]]
        xs = list(range(len(rows)))
        for key, col, mk, lab in (("vss2_half", C2, "o", "%VSS = 2% crossing"),
                                  ("gap1_half", CG, "s", "service gap = 1 unit")):
            ys = [num(r[key]) for r in rows]
            ax.plot([x for x, y in zip(xs, ys) if y is not None],
                    [y for y in ys if y is not None], color=col, marker=mk, ms=3.5, lw=1.1, label=lab)
            for x, r in zip(xs, rows):
                if num(r[key]) is None:
                    reg = r[key.replace("_half", "_regime")]
                    ax.plot([x], [0.012 if reg == "above_at_first_grid_point" else 0.488],
                            color=col, marker="v" if reg == "above_at_first_grid_point" else "^",
                            ms=4.5, mfc="none", ls="none")
        for x, r in zip(xs, rows):
            if r["is_base"]:
                ax.axvline(x, color=CB, lw=0.7, ls=":")
        ax.set_xticks(xs)
        ax.set_xticklabels([f"{r['level']:g}" for r in rows], rotation=45, ha="right", fontsize=7.5)
        ax.set_title(SHORT[fac["key"]], fontsize=7.5)
        ax.set_ylim(0, 0.5)
        ax.grid(alpha=0.25, lw=0.4)
    for r in range(nrow):
        axes[r, 0].set_ylabel("threshold FE half-range")
    h, l = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(0.5, -0.005))
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    p = os.path.join(OUT, "fig_param_sensitivity.png")
    fig.savefig(p, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {p}")

    # --- mean mapping --------------------------------------------------------
    fig, axs = plt.subplots(1, 2, figsize=(3.5, 2.5))
    ms = [r["fe_mean_nominal"] for r in mapping]
    for ax, key_on, key_2, yl in ((axs[0], "onset_half", "vss2_half", "threshold half-range"),
                                  (axs[1], "onset_ylo", "vss2_ylo", "worst-case FE yield at threshold")):
        for key, col, mk in ((key_2, C2, "o"), (key_on, CG, "s")):
            pts = [(m, num(r[key]), r[key.split("_")[0] + "_regime"]) for m, r in zip(ms, mapping)]
            pts = [p_ for p_ in pts if p_[1] is not None]
            ax.plot([p_[0] for p_ in pts], [p_[1] for p_ in pts], color=col, lw=1.0)
            for m, y, reg in pts:
                ax.plot([m], [y], color=col, marker=mk, ms=3.8,
                        mfc=col if reg == "clipped" else "white")
        ax.set_xlabel("nominal FE mean yield")
        ax.set_ylabel(yl, fontsize=7.5)
        ax.tick_params(labelsize=7.5)
        ax.grid(alpha=0.25, lw=0.4)
    mm = np.linspace(min(ms), max(ms), 100)
    rho = consts["rho"]
    axs[0].plot(mm, 1 - mm, color=CB, lw=0.7, ls="--")
    axs[1].plot(mm, rho * mm, color=CB, lw=0.7, ls="-.")
    axs[1].axhline(rho / (2 - rho), color=CB, lw=0.7, ls=":")
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], color=C2, marker="o", ms=3.8, lw=1.0, label="%VSS = 2% crossing"),
               Line2D([], [], color=CG, marker="s", ms=3.8, lw=1.0, label="service-gap onset"),
               Line2D([], [], color="k", marker="o", ms=3.8, mfc="white", ls="none", label="symmetric regime"),
               Line2D([], [], color="k", marker="o", ms=3.8, ls="none", label="upper yield clipped at 1"),
               Line2D([], [], color=CB, lw=0.7, ls="--", label="half-range $=1-$mean"),
               Line2D([], [], color=CB, lw=0.7, ls="-.", label=r"$\rho\,\bar y$"),
               Line2D([], [], color=CB, lw=0.7, ls=":", label=r"$\rho/(2-\rho)$")]
    fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False, fontsize=7,
               bbox_to_anchor=(0.5, -0.01), columnspacing=1.0, handlelength=2.2)
    fig.tight_layout(rect=(0, 0.2, 1, 1))
    p = os.path.join(OUT, "fig_mean_mapping.png")
    fig.savefig(p, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {p}")


def main():
    t0 = time.time()
    print(f"param_sensitivity_revision.py  ({'SMOKE' if SMOKE else 'FULL'} grid)  -> {OUT}")
    dev = self_check()
    print(f"  self-check vs step2_freeze_model: max objective deviation = {dev:.2e}")
    base = evaluate(BASE, 0.80, 0.95)
    print(f"  baseline: RP {base['rp_obj']:.2f}  EEV {base['eev_obj']:.2f}  VSS {base['vss']:.2f}  "
          f"%VSS {base['pct_vss']:.2f}")

    print("[A] one-factor-at-a-time sweeps")
    thr, pts = run_ofat()
    print("[B] mean / spread parameterisation (70% mapping)")
    mapping, consts = run_mean_mapping()
    print("[C] strict three-stage (non-anticipative) variant")
    na = run_na_variant()
    print("[D] load-balancing check")
    bal = run_balance()
    print("[E] Beta lowest support point at the crossing")
    beta_rows, beta_info = run_beta_tail()

    write_csv("ofat_thresholds.csv", thr)
    write_csv("ofat_sweep_points.csv", pts)
    write_csv("mean_mapping.csv", mapping)
    write_csv("na_variant.csv", na)
    write_csv("balanced_load_check.csv", bal)
    write_csv("beta_tail.csv", beta_rows)
    try:
        make_figures(thr, mapping, consts)
    except Exception as exc:                                  # figures are optional
        print(f"  [warning] figure generation failed: {exc!r}")

    n_solves = 3 * (len(pts))
    with open(os.path.join(OUT, "summary.txt"), "w") as fh:
        fh.write(f"grid: {'smoke' if SMOKE else 'full'}; OFAT sweep points: {len(pts)} "
                 f"(~{n_solves} solves); wall time {time.time()-t0:.0f} s\n")
        fh.write(f"self-check max deviation vs step2: {dev:.3e}\n")
        fh.write(f"N_bar={consts['N_bar']:.3f} N_max={consts['N_max']:.3f} L_G={consts['L_G']} "
                 f"rho={consts['rho']:.5f} rho/(2-rho)={consts['rho']/(2-consts['rho']):.5f}\n")
        if beta_info:
            fh.write("beta crossing: " + ", ".join(f"{k}={v:.5f}" for k, v in beta_info.items()) + "\n")
        fh.write(f"non-optimal solves: {FAILED if FAILED else 'none'}\n")
    print(f"  non-optimal solves: {FAILED if FAILED else 'none'}")
    print(f"done in {time.time()-t0:.0f} s")


if __name__ == "__main__":
    main()
