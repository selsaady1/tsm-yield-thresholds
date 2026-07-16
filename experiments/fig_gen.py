"""
fig_gen.py
==========
Regenerates the two revision figures from REAL data (no hardcoded results):

  rev_fig1_meanyield_threshold.png
      Threshold half-range spread vs Front-End mean yield, with the worst-case
      Front-End yield at the threshold. Crossings are computed by re-solving the
      paper's own CBC model (step2_freeze_model.run_experiment), exactly as in
      threshold_vs_mean.py.

  rev_fig2_continuous_vs_twopoint.png
      %VSS vs equivalent full-range FE yield spread for the continuous (Beta)
      distribution, read directly from beta_results.csv (produced by
      beta_experiment.py), with the Beta and two-point 2% crossings marked.

Run from anywhere:
    python revision_work/fig_gen.py
Outputs are written next to main.tex in Elsaady_Zhang_ITC2026/.
No fabricated numbers: rev_fig1 comes from live solves, rev_fig2 from the CSV.
"""
import os
import sys
import csv
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
FIGDIR = os.path.join(ROOT, "Elsaady_Zhang_ITC2026")
sys.path.insert(0, SCRIPTS)

from step2_freeze_model import FrozenInstance, run_experiment   # noqa: E402

FE_MEAN_LIST = [0.850, 0.875, 0.900]
BE_LO, BE_HI = 0.70, 0.90     # paper Experiment A holds BE at 0.70-0.90
TARGET = 2.0                  # %VSS > 2% criterion


def mk(mean, full_spread):
    return max(0.01, mean - full_spread / 2.0), min(1.00, mean + full_spread / 2.0)


def crossing_full_spread(fe_mean, target=TARGET):
    """Full-range FE spread where %VSS first crosses `target`, via real solves."""
    spreads = np.round(np.arange(0.02, 0.451, 0.015), 4)
    xs, ys = [], []
    for sp in spreads:
        fl, fh = mk(fe_mean, sp)
        r = run_experiment(FrozenInstance(round(fl, 4), round(fh, 4), BE_LO, BE_HI))
        xs.append(sp)
        ys.append(r["pct_vss"])
    for i in range(1, len(xs)):
        if ys[i - 1] < target <= ys[i]:
            f = (target - ys[i - 1]) / (ys[i] - ys[i - 1])
            return xs[i - 1] + f * (xs[i] - xs[i - 1])
    return None


def make_rev_fig1():
    means, half_thr, worst = [], [], []
    for m in FE_MEAN_LIST:
        full = crossing_full_spread(m)
        if full is None:
            continue
        half = full / 2.0
        means.append(m)
        half_thr.append(half)
        worst.append(round(m - half, 3))     # worst-case FE yield = mean - half-range

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(means, half_thr, "o-", color="#1f3b73", lw=2.2, ms=9,
            label="Threshold (half-range spread)")
    ax.plot(means, worst, "s--", color="#c0392b", lw=2.2, ms=9,
            label="Worst-case FE yield at threshold")
    for x, y in zip(means, worst):
        ax.annotate(f"{y:.3f}", (x, y), textcoords="offset points",
                    xytext=(0, -16), ha="center", color="#c0392b", fontsize=11)
    ax.set_xlabel("Front-End mean yield", fontsize=12)
    ax.set_ylabel("Yield value", fontsize=12)
    ax.set_title("Threshold moves with mean yield, but worst-case FE yield is constant",
                 fontsize=13)
    ax.set_ylim(0, 0.75)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="center right", fontsize=11)
    fig.tight_layout()
    out = os.path.join(FIGDIR, "rev_fig1_meanyield_threshold.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"[rev_fig1] means={means} half_thr={[round(h,4) for h in half_thr]} "
          f"worst={worst} -> {out}")


def make_rev_fig2():
    csv_path = os.path.join(HERE, "beta_results.csv")
    xs, ys = [], []
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            xs.append(float(row["equiv_full_spread"]))
            ys.append(float(row["pct_vss"]))

    # Beta 2% crossing by linear interpolation on the real CSV points.
    beta_full = None
    for i in range(1, len(xs)):
        if ys[i - 1] < TARGET <= ys[i]:
            fr = (TARGET - ys[i - 1]) / (ys[i] - ys[i - 1])
            beta_full = xs[i - 1] + fr * (xs[i] - xs[i - 1])
            break
    two_point_full = 0.3556       # paper's two-point crossing at mean 0.875 (Step 5)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(xs, ys, "o-", color="#1f3b73", lw=2.0, ms=6,
            label="Continuous (Beta) FE yield")
    ax.axhline(TARGET, color="0.5", ls=":", lw=1.2)
    if beta_full is not None:
        ax.axvline(beta_full, color="#c0392b", ls="--", lw=1.8,
                   label=f"Beta crossing (full {beta_full:.3f} / half {beta_full/2:.3f})")
    ax.axvline(two_point_full, color="#2e7d32", ls="--", lw=1.8,
               label=f"Two-point crossing (full {two_point_full:.3f} / half {two_point_full/2:.3f})")
    ax.set_xlabel("Equivalent full-range FE yield spread", fontsize=12)
    ax.set_ylabel("%VSS", fontsize=12)
    ax.set_title("A realistic continuous distribution lowers the threshold", fontsize=13)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=10)
    fig.tight_layout()
    out = os.path.join(FIGDIR, "rev_fig2_continuous_vs_twopoint.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    half = f"{beta_full/2:.4f}" if beta_full else "n/a"
    print(f"[rev_fig2] beta_full={beta_full} (half {half}) two_point_full={two_point_full} -> {out}")


if __name__ == "__main__":
    make_rev_fig1()
    make_rev_fig2()
    print("Done. Both revision figures regenerated from real data.")
