"""
capacity_cliff_sweep.py
=======================
Revision-round experiment: is the service "cliff" a capacity effect?

For each capacity configuration the fine FE half-range grid of Step 5/6 is
re-run and the expected unmet demand of the stochastic plan (RP) and of the
deterministic plan evaluated under uncertainty (EEV) are recorded
separately, together with wafer starts and outsourced-die usage.

Configurations (one factor at a time around the frozen instance)
    outsourced FE capacity L_G   : 0 .. 600 dies      (base 300)
    in-house FE capacity         : x0.5 .. x1.5       (base 10 / 8 wafers)
    in-house BE capacity         : x0.8 .. x1.25      (base 500 / 400)

Per configuration the script reports
    * onset of the deterministic plan's service gap (bisection on real solves),
    * the half-range at which the gap crosses 1 unit (interpolated),
    * the half-range at which the stochastic plan's wafer starts reach the
      FE capacity (it can no longer add in-house hedge),
    * the half-range at which the stochastic plan's own expected unmet
      demand first rises above its small-spread level (it can no longer
      protect service at all),
    * a prediction of the gap onset computed from the *deterministic* plan
      alone: the first half-range at which
            n * y_lo * W_EV + L_G  <  N_max
      (worst-case in-house dies of the expected-value plan plus the whole
      outsourced FE capacity fall short of the largest die requirement).
      W_EV comes from the expected-value solve and N_max from a solve with
      FE supply made non-binding; nothing is assumed.

Real solves only (PuLP + CBC). Rows whose solve is not optimal are dropped
and listed; no value is invented.

Usage
-----
    PYTHONPATH=src:experiments python experiments/capacity_cliff_sweep.py --smoke
    PYTHONPATH=src:experiments python experiments/capacity_cliff_sweep.py

Outputs (results/Revision/CapacityCliff/, or .../smoke/ with --smoke)
    cliff_curves.csv, cliff_onsets.csv, fig_capacity_cliff.png, summary.txt
"""

import csv
import os
import sys
import time

import numpy as np

from revision_common import (FE_MEAN, HALF_GRID, base_inst, two_point, evaluate,
                             sweep, crossing, self_check, max_die_requirement,
                             solve_model)

SMOKE = "--smoke" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "results", "Revision", "CapacityCliff")
if SMOKE:
    OUT = os.path.join(OUT, "smoke")
os.makedirs(OUT, exist_ok=True)

HALVES = HALF_GRID[1::2] if SMOKE else HALF_GRID
BASE = base_inst()
EPS = 1e-6


def scaled(d, m):
    return {k: v * m for k, v in d.items()}


def configs():
    lg = [0, 300, 600] if SMOKE else [0, 100, 200, 300, 400, 500, 600]
    fe = [0.5, 1.0, 1.5] if SMOKE else [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.25, 1.5]
    be = [0.9, 1.0, 1.1] if SMOKE else [0.8, 0.9, 1.0, 1.1, 1.25]
    out = []
    for c in lg:
        out.append(("outs_fe_capacity", float(c), {"L_G": {"G1": float(c)}}))
    for m in fe:
        out.append(("fe_capacity_mult", m, {"L_F": scaled(BASE["L_F"], m)}))
    for m in be:
        out.append(("be_capacity_mult", m, {"L_B": scaled(BASE["L_B"], m)}))
    return out


def ev_wafers(inst, lo, hi):
    """Wafer starts of the expected-value plan for a two-point FE yield (lo, hi)."""
    sc = [{"name": "EV", "prob": 1.0, "fe_yield": (lo + hi) / 2,
           "demand": (inst["demand_lo"] + inst["demand_hi"]) / 2, "be_yield": 0.80}]
    r = solve_model(inst, sc, tag="EVonly")
    return sum(r["X_F"].values())


def bisect_first(f, a=0.0, b=0.50, tol=1e-4):
    """Smallest h in (a, b] with f(h) True, assuming f is monotone; None if never."""
    if not f(b):
        return None
    if f(a + tol):
        return a + tol
    while b - a > tol:
        m = 0.5 * (a + b)
        if f(m):
            b = m
        else:
            a = m
    return 0.5 * (a + b)


def fmt(x, nd=4):
    return "NA" if x is None else f"{x:.{nd}f}"


def main():
    t0 = time.time()
    print(f"capacity_cliff_sweep.py  ({'SMOKE' if SMOKE else 'FULL'} grid)  -> {OUT}")
    print(f"  self-check vs step2_freeze_model: max objective deviation = {self_check():.2e}")

    curves, onsets, failed = [], [], []
    for (factor, level, over) in configs():
        inst = base_inst(**over)
        n = inst["n_f_i"]
        l_g = sum(inst["L_G"].values())
        fe_cap = sum(inst["L_F"].values())
        n_max = max_die_requirement(inst)
        rows = sweep(inst, halves=HALVES)
        bad = [r for r in rows if not r["ok"]]
        if bad:
            failed.append((factor, level, len(bad)))
        rows = [r for r in rows if r["ok"]]
        if not rows:
            continue
        rp0 = rows[0]["rp_unmet"]                     # RP unmet at the smallest spread
        for r in rows:
            curves.append({
                "factor": factor, "level": level, "half": r["half"],
                "fe_lo": fmt(r["fe_lo"]), "fe_hi": fmt(r["fe_hi"]), "clipped": r["clipped"],
                "rp_unmet": fmt(r["rp_unmet"]), "eev_unmet": fmt(r["eev_unmet"]),
                "unmet_gap": fmt(r["unmet_gap"]), "pct_vss": fmt(r["pct_vss"]),
                "vss": fmt(r["vss"], 3),
                "rp_wafers": fmt(r["rp_fe1"] + r["rp_fe2"]),
                "ev_wafers": fmt(r["ev_fe1"] + r["ev_fe2"]), "fe_capacity_wafers": fmt(fe_cap, 2),
                "rp_exp_outsourced_dies": fmt(r["rp_exp_outs"], 2),
                "eev_exp_outsourced_dies": fmt(r["eev_exp_outs"], 2),
                "eev_max_outsourced_dies": fmt(r["eev_max_outs"], 2)})

        # --- solver-located events -------------------------------------------------
        def ev_at(h):
            lo, hi = two_point(FE_MEAN, h)
            return evaluate(inst, lo, hi)

        # The gap need not be monotone (it closes again once the stochastic plan
        # is capacity-bound too), so bracket the onset on the grid first and
        # bisect only inside the bracketing interval.
        first = next((r["half"] for r in rows if r["unmet_gap"] > EPS), None)
        if first is None:
            h_gap = None
        else:
            prev = max([r["half"] for r in rows if r["half"] < first], default=0.0)
            h_gap = bisect_first(lambda h: ev_at(h)["unmet_gap"] > EPS, a=prev, b=first)
        c1 = crossing(rows, "unmet_gap", 1.0)
        c2 = crossing(rows, "pct_vss", 2.0)
        h_rp_sat = bisect_first(lambda h: (lambda r: r["rp_fe1"] + r["rp_fe2"])(ev_at(h)) >= fe_cap - 1e-4)
        h_rp_unmet = bisect_first(lambda h: ev_at(h)["rp_unmet"] > rp0 + 1e-4)

        # --- prediction from the deterministic plan alone --------------------------
        def short(h):
            lo, hi = two_point(FE_MEAN, h)
            return n * lo * ev_wafers(inst, lo, hi) + l_g < n_max - 1e-6
        h_pred = bisect_first(short)

        def ylo(h):
            return None if h is None else two_point(FE_MEAN, h)[0]

        def cfield(c, key):
            if c is None:
                return "no_crossing"
            if c["half"] is None:
                return "above_at_first_grid_point"
            return fmt(c[key])

        onsets.append({
            "factor": factor, "level": level, "N_max": fmt(n_max, 2), "L_G": l_g,
            "fe_capacity_wafers": fmt(fe_cap, 2),
            "gap_onset_half": fmt(h_gap), "gap_onset_ylo": fmt(ylo(h_gap)),
            "pred_onset_half": fmt(h_pred), "pred_onset_ylo": fmt(ylo(h_pred)),
            "gap1_half": cfield(c1, "half"), "gap1_ylo": cfield(c1, "y_lo"),
            "vss2_half": cfield(c2, "half"), "vss2_ylo": cfield(c2, "y_lo"),
            "rp_fe_saturation_half": fmt(h_rp_sat), "rp_fe_saturation_ylo": fmt(ylo(h_rp_sat)),
            "rp_unmet_rise_half": fmt(h_rp_unmet), "rp_unmet_rise_ylo": fmt(ylo(h_rp_unmet)),
            "rp_unmet_small_spread": fmt(rp0), "gap_at_half_0.50": fmt(rows[-1]["unmet_gap"]),
            "rp_unmet_at_half_0.50": fmt(rows[-1]["rp_unmet"]),
            "eev_unmet_at_half_0.50": fmt(rows[-1]["eev_unmet"])})
        o = onsets[-1]
        print(f"  {factor:>17s}={level:<6g} gap onset half={o['gap_onset_half']} (pred {o['pred_onset_half']})"
              f"  gap>1 at {o['gap1_half']}  RP saturates FE at {o['rp_fe_saturation_half']}"
              f"  RP unmet rises at {o['rp_unmet_rise_half']}", flush=True)

    for name, rows in (("cliff_curves.csv", curves), ("cliff_onsets.csv", onsets)):
        path = os.path.join(OUT, name)
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"  wrote {path} ({len(rows)} rows)")

    try:
        make_figure(curves, onsets)
    except Exception as exc:
        print(f"  [warning] figure generation failed: {exc!r}")

    with open(os.path.join(OUT, "summary.txt"), "w") as fh:
        fh.write(f"grid: {'smoke' if SMOKE else 'full'}; sweep points: {len(curves)}; "
                 f"wall time {time.time()-t0:.0f} s\n")
        fh.write(f"non-optimal solves dropped: {failed if failed else 'none'}\n")
    print(f"  non-optimal solves dropped: {failed if failed else 'none'}")
    print(f"done in {time.time()-t0:.0f} s")


def make_figure(curves, onsets):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8,
                         "legend.fontsize": 7.5, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "figure.dpi": 200})
    f = lambda x: None if x in ("NA", "no_crossing", "above_at_first_grid_point") else float(x)
    seq = plt.get_cmap("viridis")

    def series(factor, level, key):
        rows = [r for r in curves if r["factor"] == factor and abs(r["level"] - level) < 1e-9]
        return [r["half"] for r in rows], [float(r[key]) for r in rows]

    fig, axs = plt.subplots(1, 3, figsize=(7.2, 2.2))

    # (a) deterministic plan's service gap vs outsourced FE capacity
    lv = sorted({r["level"] for r in curves if r["factor"] == "outs_fe_capacity"})
    for i, c in enumerate(lv):
        x, y = series("outs_fe_capacity", c, "unmet_gap")
        axs[0].plot(x, y, color=seq(i / max(1, len(lv) - 1) * 0.9), lw=1.1, label=f"$L_G$={c:g}")
    axs[0].set_title("(a) Service gap vs. $L_G$")
    axs[0].set_ylabel("service gap (units)")
    axs[0].legend(frameon=False, ncol=2, fontsize=7.5, loc="upper left", columnspacing=0.8, handlelength=1.4)
    axs[0].set_ylim(-4, 140)

    # (b) RP and EEV unmet demand vs in-house FE capacity
    lv = sorted({r["level"] for r in curves if r["factor"] == "fe_capacity_mult"})
    show = [m for m in lv if m in (0.5, 0.7, 1.0, 1.5)] or lv
    for i, m in enumerate(show):
        col = seq(i / max(1, len(show) - 1) * 0.9)
        x, y = series("fe_capacity_mult", m, "eev_unmet")
        axs[1].plot(x, y, color=col, lw=1.1, label=f"FE cap. $\\times${m:g}")
        x, y = series("fe_capacity_mult", m, "rp_unmet")
        axs[1].plot(x, y, color=col, lw=1.1, ls="--")
    axs[1].plot([], [], color="k", lw=1.1, label="deterministic (EEV)")
    axs[1].plot([], [], color="k", lw=1.1, ls="--", label="stochastic (RP)")
    axs[1].set_title("(b) Unmet demand vs. FE capacity")
    axs[1].set_ylabel("expected unmet demand (units)")
    axs[1].legend(frameon=False, fontsize=7.5, loc="upper left", handlelength=1.6)

    # (c) predicted vs solver-located onset
    mk = {"outs_fe_capacity": ("o", "#1f5fa8", "$L_G$ varied"),
          "fe_capacity_mult": ("s", "#c0392b", "FE capacity varied"),
          "be_capacity_mult": ("^", "#2e8b57", "BE capacity varied")}
    allv = []
    for fac, (m, col, lab) in mk.items():
        pts = [(f(o["pred_onset_ylo"]), f(o["gap_onset_ylo"])) for o in onsets if o["factor"] == fac]
        pts = [p for p in pts if p[0] is not None and p[1] is not None]
        if pts:
            axs[2].plot([p[0] for p in pts], [p[1] for p in pts], marker=m, color=col, ls="none",
                        ms=4.5, mfc="none", label=lab)
            allv += [v for p in pts for v in p]
    if allv:
        lo, hi = min(allv) - 0.03, max(allv) + 0.03
        axs[2].plot([lo, hi], [lo, hi], color="#555555", lw=0.7, ls=":")
        axs[2].set_xlim(lo, hi)
        axs[2].set_ylim(lo, hi)
    axs[2].set_title("(c) Gap onset: predicted vs. solved")
    axs[2].set_xlabel("predicted worst-case FE yield")
    axs[2].set_ylabel("solved worst-case FE yield")
    axs[2].legend(frameon=False, fontsize=7.5, loc="upper left")

    for ax in axs[:2]:
        ax.set_xlabel("FE yield half-range")
        ax.set_xlim(0, 0.5)
    for ax in axs:
        ax.grid(alpha=0.25, lw=0.4)
    fig.tight_layout()
    p = os.path.join(OUT, "fig_capacity_cliff.png")
    fig.savefig(p, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {p}")


if __name__ == "__main__":
    main()
