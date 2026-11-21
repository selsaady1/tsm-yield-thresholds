#!/usr/bin/env python3
"""Regenerates three base-instance figures for the revised manuscript.

No optimisation is run here. Each figure is drawn from result files that are
already in the repository, with the in-image titles and labels of the
submitted versions replaced by neutral ones:

  fig_service_cliff_rev.png   expected unmet demand of the two plans versus FE
                              full-range spread (Experiment A, 50-level Step 5
                              data), with the spread at which the gap opens
  fig_beta_vs_twopoint_rev.png  %VSS under the seven-point Beta discretisation
                              (experiments/beta_results.csv), no title
  fig_decision_map_rev.png    Step 6 thresholds by shortage penalty, zones
                              labelled by criterion, marked "base instance"

Run from the repository root:
    python experiments/revision_figs.py
Outputs go to results/Revision/Figures/.
"""
import csv
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "results", "Revision", "Figures")
SERIF = {"font.family": "serif", "mathtext.fontset": "dejavuserif"}


def read_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def crossing(xs, ys, level):
    """First upward crossing of `level` by linear interpolation.

    Returns (x, started_above). If the series is already at or above the level
    at its first point, the crossing returned is the first re-crossing after
    the series has dipped below (or None), and started_above is True.
    """
    started_above = ys[0] >= level
    for i in range(1, len(xs)):
        if ys[i - 1] < level <= ys[i]:
            fr = (level - ys[i - 1]) / (ys[i] - ys[i - 1])
            return xs[i - 1] + fr * (xs[i] - xs[i - 1]), started_above
    return None, started_above


def fig_service_cliff():
    rows = [r for r in read_csv(os.path.join(ROOT, "results", "Step5", "step5_failure_data.csv"))
            if r["experiment"] == "A_FE_only"]
    rows.sort(key=lambda r: float(r["ramp_spread"]))
    x = [float(r["ramp_spread"]) for r in rows]
    rp = [float(r["rp_exp_unmet"]) for r in rows]
    ev = [float(r["eev_exp_unmet"]) for r in rows]
    gap = [float(r["unmet_gap"]) for r in rows]
    last_zero = max(xi for xi, g in zip(x, gap) if abs(g) < 1e-9)
    # closed-form onset for the base instance: half-range 0.1607, full-range 0.3214
    onset_full = 2 * (0.875 - (5 / 6) / (2 - 5 / 6))
    assert last_zero <= onset_full <= last_zero + 0.01 + 1e-9, (last_zero, onset_full)

    with plt.rc_context(SERIF):
        fig, ax = plt.subplots(figsize=(6.9, 3.3))
        ax.plot(x, ev, "s-", color="#F59E0B", lw=1.8, ms=4, label="Deterministic")
        ax.plot(x, rp, "o-", color="#2563EB", lw=1.8, ms=4, label="Stochastic")
        ax.fill_between(x, rp, ev, color="#DC2626", alpha=0.18, label="Service gap")
        ax.axvline(onset_full, color="k", ls="--", lw=1.3)
        ax.text(onset_full - 0.008, 33.2, "gap opens\nat 0.32", ha="right", va="center", fontsize=11)
        ax.set_xlabel("FE Yield Spread (high $-$ low)", fontsize=12)
        ax.set_ylabel("Expected Unmet Demand", fontsize=12)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper left", fontsize=10)
        fig.tight_layout()
        out = os.path.join(OUT, "fig_service_cliff_rev.png")
        fig.savefig(out, dpi=150)
        plt.close(fig)
    print(f"[service cliff] last zero-gap spread {last_zero:.2f}, closed-form onset {onset_full:.4f} -> {out}")


def fig_beta():
    rows = read_csv(os.path.join(HERE, "beta_results.csv"))
    xs = [float(r["equiv_full_spread"]) for r in rows]
    ys = [float(r["pct_vss"]) for r in rows]
    beta_full, _ = crossing(xs, ys, 2.0)
    two_point_full = 0.3556  # Step 5, Experiment A, %VSS > 2%

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(xs, ys, "o-", color="#1f3b73", lw=2.0, ms=6, label="Seven-point Beta FE yield")
    ax.axhline(2.0, color="0.5", ls=":", lw=1.2)
    ax.axvline(beta_full, color="#c0392b", ls="--", lw=1.8,
               label=f"Beta crossing (full {beta_full:.3f} / half {beta_full / 2:.3f})")
    ax.axvline(two_point_full, color="#2e7d32", ls="--", lw=1.8,
               label=f"Two-point crossing (full {two_point_full:.3f} / half {two_point_full / 2:.3f})")
    ax.set_xlabel("Equivalent full-range FE yield spread ($2\\sigma$)", fontsize=12)
    ax.set_ylabel("%VSS", fontsize=12)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=10)
    fig.tight_layout()
    out = os.path.join(OUT, "fig_beta_vs_twopoint_rev.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"[beta] crossing full {beta_full:.4f} half {beta_full / 2:.4f} -> {out}")


def fig_decision_map():
    rows = read_csv(os.path.join(ROOT, "results", "Step6", "step6_robustness_results.csv"))
    penalties = sorted({float(r["v_d"]) for r in rows})
    warn, crit, svc, warn_started_above = [], [], [], []
    for v in penalties:
        sub = sorted((r for r in rows if float(r["v_d"]) == v), key=lambda r: float(r["fe_spread"]))
        h = [float(r["fe_spread"]) for r in sub]
        pv = [float(r["pct_vss"]) for r in sub]
        gp = [float(r["unmet_gap"]) for r in sub]
        w, above = crossing(h, pv, 1.5)
        warn.append(w)
        warn_started_above.append(above)
        crit.append(crossing(h, pv, 2.0)[0])
        svc.append(crossing(h, gp, 1.0)[0])
    print("[decision map] penalties", penalties)
    print("  %VSS>1.5%:", [round(w, 4) for w in warn], "already above at first point:", warn_started_above)
    print("  %VSS>2%  :", [round(c, 4) for c in crit])
    print("  gap>1    :", [round(s, 4) for s in svc])

    g_end, y_end = min(warn) - 0.005, max(crit) + 0.005
    with plt.rc_context(SERIF):
        fig, ax = plt.subplots(figsize=(6.8, 4.0))
        ax.axvspan(0.0, g_end, color="#22C55E", alpha=0.18)
        ax.axvspan(g_end, y_end, color="#F59E0B", alpha=0.15)
        ax.axvspan(y_end, 0.28, color="#EF4444", alpha=0.17)
        for w, v, above in zip(warn, penalties, warn_started_above):
            ax.plot([w], [v], "o", color="#F59E0B", ms=8, mfc="white" if above else "#F59E0B", mew=1.8, zorder=5)
        ax.plot(warn, penalties, "--", color="#F59E0B", lw=2, zorder=4)
        ax.plot([], [], "o--", color="#F59E0B", ms=8, lw=2, label="%VSS > 1.5%")
        ax.plot(crit, penalties, "s-", color="#DC2626", lw=2.2, ms=7, label="%VSS > 2%", zorder=5)
        ax.plot(svc, penalties, "^:", color="#4F5BD5", lw=2, ms=8, label="Service gap > 1", zorder=5)
        ax.text(g_end / 2, 8.45, "below 1.5%", color="#15803D", fontsize=11, fontweight="bold", ha="center", va="center")
        ax.text((g_end + y_end) / 2, 8.45, "1.5% to 2%", color="#B45309", fontsize=11, fontweight="bold", ha="center", va="center")
        ax.text((y_end + 0.28) / 2, 8.45, "above 2%,\nservice gap", color="#B91C1C", fontsize=11, fontweight="bold",
                ha="center", va="center")
        ax.text(0.004, 0.25, "base instance only", fontsize=9, style="italic", color="0.25", ha="left", va="bottom")
        ax.set_xlim(0.0, 0.28)
        ax.set_ylim(0.0, 9.0)
        ax.set_xlabel("Front-End Yield Spread (half-range)", fontsize=11)
        ax.set_ylabel("Shortage Penalty ($/device)", fontsize=11)
        ax2 = ax.twinx()
        ax2.set_ylim(0.0, 90.0)
        ax2.set_ylabel("Penalty/Price (%)", fontsize=11, color="0.4")
        ax2.tick_params(axis="y", labelcolor="0.4")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="lower right", fontsize=9, framealpha=0.95)
        fig.tight_layout()
        out = os.path.join(OUT, "fig_decision_map_rev.png")
        fig.savefig(out, dpi=150)
        plt.close(fig)
    print(f"  -> {out}")


def fig_vss_vs_spread():
    """%VSS versus swept half-range for Experiments A, B, C (Step 5, 50 levels each).

    The swept half-range is ramp_spread / 2 (ramp_spread is the nominal full
    range high - low before clipping; fe_spread in the CSV is the realized,
    clipped range and is not used). Single-column vector PDF for the article.
    """
    rows = read_csv(os.path.join(ROOT, "results", "Step5", "step5_failure_data.csv"))
    series = {}
    for exp in ("A_FE_only", "B_BE_only", "C_both"):
        sub = sorted((r for r in rows if r["experiment"] == exp), key=lambda r: float(r["ramp_spread"]))
        series[exp] = ([float(r["ramp_spread"]) / 2 for r in sub], [float(r["pct_vss"]) for r in sub])
    xa, ya = series["A_FE_only"]
    cross_a, above = crossing(xa, ya, 2.0)
    assert not above and abs(cross_a - 0.178) < 0.0005, cross_a  # Table II, $3 column: 0.178
    style = {"font.family": "serif", "font.serif": ["Times New Roman", "Times", "Nimbus Roman", "DejaVu Serif"],
             "mathtext.fontset": "stix", "font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 8,
             "ytick.labelsize": 8, "legend.fontsize": 8, "pdf.fonttype": 42}
    okabe = {"A_FE_only": ("#0072B2", "o", "A: FE only"), "B_BE_only": ("#E69F00", "s", "B: BE only"),
             "C_both": ("#009E73", "^", "C: both")}
    with plt.rc_context(style):
        fig, ax = plt.subplots(figsize=(3.5, 1.4))
        for exp, (xs, ys) in series.items():
            col, mk, lab = okabe[exp]
            ax.plot(xs, ys, "-", color=col, lw=1.1, marker=mk, ms=2.6, markevery=4, label=lab)
        ax.axhline(2.0, color="0.35", ls=":", lw=0.9)
        ax.axvline(cross_a, color="#D55E00", ls="--", lw=0.9)
        ax.annotate(f"2% at {cross_a:.3f}", xy=(cross_a, 2.0), xytext=(cross_a - 0.012, 2.75),
                    ha="right", va="center", fontsize=8, color="#D55E00")
        ax.set_xlabel("Swept yield half-range")
        ax.set_ylabel("%VSS")
        ax.set_xlim(0, 0.25)
        ax.grid(True, alpha=0.25, lw=0.5)
        ax.legend(loc="upper left", frameon=False, handlelength=1.6, borderaxespad=0.2, labelspacing=0.2)
        fig.tight_layout(pad=0.2)
        out = os.path.join(OUT, "fig_vss_vs_spread.pdf")
        fig.savefig(out)
        plt.close(fig)
    print(f"[vss vs spread] A crosses 2% at half-range {cross_a:.4f} -> {out}")


# ---------------------------------------------------------------------------
# Column-width vector versions (Nov 9, 2026, final revise pass). Same data as
# the PNG versions above; only size, font size (>= 7 pt printed), and format
# change, so that every printed label is legible in the two-column layout.
# ---------------------------------------------------------------------------
COL = {"font.family": "serif", "font.serif": ["Times New Roman", "Times", "Nimbus Roman", "DejaVu Serif"],
       "mathtext.fontset": "stix", "font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 7.5,
       "ytick.labelsize": 7.5, "legend.fontsize": 7.5, "pdf.fonttype": 42}


def fig_service_cliff_col():
    rows = [r for r in read_csv(os.path.join(ROOT, "results", "Step5", "step5_failure_data.csv"))
            if r["experiment"] == "A_FE_only"]
    rows.sort(key=lambda r: float(r["ramp_spread"]))
    x = [float(r["ramp_spread"]) for r in rows]
    rp = [float(r["rp_exp_unmet"]) for r in rows]
    ev = [float(r["eev_exp_unmet"]) for r in rows]
    onset_full = 2 * (0.875 - (5 / 6) / (2 - 5 / 6))
    with plt.rc_context(COL):
        fig, ax = plt.subplots(figsize=(3.5, 1.45))
        ax.plot(x, ev, "s-", color="#E69F00", lw=1.1, ms=2.4, markevery=3, label="Deterministic")
        ax.plot(x, rp, "o-", color="#0072B2", lw=1.1, ms=2.4, markevery=3, label="Stochastic")
        ax.fill_between(x, rp, ev, color="#D55E00", alpha=0.18, label="Service gap")
        ax.axvline(onset_full, color="k", ls="--", lw=0.9)
        ax.text(onset_full - 0.008, 32.6, "gap opens\nat 0.32", ha="right", va="center", fontsize=8)
        ax.set_xlabel("FE yield spread $2h$ (full range)")
        ax.set_ylabel("Expected unmet demand")
        ax.grid(True, alpha=0.25, lw=0.5)
        ax.legend(loc="upper left", frameon=False, handlelength=1.6, labelspacing=0.2, borderaxespad=0.2)
        fig.tight_layout(pad=0.2)
        out = os.path.join(OUT, "fig_service_cliff_col.pdf")
        fig.savefig(out)
        plt.close(fig)
    print(f"[service cliff col] -> {out}")


def fig_failure_zones_col():
    """Fig. S1: %VSS and service gap versus full-range spread for A, B, C, with
    warning (1.5%, 1 unit) to critical (2%, 3 units) zones shaded. Replaces the
    150-dpi Step 5 PNG; same CSV (results/Step5/step5_failure_data.csv)."""
    rows = read_csv(os.path.join(ROOT, "results", "Step5", "step5_failure_data.csv"))
    exps = [("A_FE_only", "A: FE only", "#0072B2"), ("B_BE_only", "B: BE only", "#E69F00"),
            ("C_both", "C: both", "#009E73")]
    with plt.rc_context(COL):
        fig, axs = plt.subplots(3, 2, figsize=(3.5, 4.3), sharex=True)
        for i, (exp, lab, col) in enumerate(exps):
            sub = sorted((r for r in rows if r["experiment"] == exp), key=lambda r: float(r["ramp_spread"]))
            x = [float(r["ramp_spread"]) for r in sub]
            for j, (key, warn, crit) in enumerate((("pct_vss", 1.5, 2.0), ("unmet_gap", 1.0, 3.0))):
                ax = axs[i, j]
                y = [float(r[key]) for r in sub]
                w, w_above = crossing(x, y, warn)
                c, c_above = crossing(x, y, crit)
                w0 = x[0] if w_above else w
                if w0 is not None:
                    ax.axvspan(w0, c if c is not None else x[-1], color="#F0E442", alpha=0.25, lw=0)
                if c is not None or c_above:
                    ax.axvspan(x[0] if c_above else c, x[-1], color="#D55E00", alpha=0.15, lw=0)
                ax.axhline(warn, color="#E69F00", ls="--", lw=0.7)
                ax.axhline(crit, color="#D55E00", ls="--", lw=0.7)
                ax.plot(x, y, color=col, lw=1.2)
                ax.set_xlim(0, 0.5)
                ax.grid(True, alpha=0.25, lw=0.5)
                ax.set_ylabel("%VSS" if j == 0 else "gap (units)")
                if i == 0:
                    ax.set_title("%VSS" if j == 0 else "Service gap", fontsize=8)
                if j == 0:
                    ax.text(0.03, 0.9, lab, transform=ax.transAxes, fontsize=7.5, va="top")
            axs[2, 0].set_xlabel("Yield spread (full range)")
            axs[2, 1].set_xlabel("Yield spread (full range)")
        fig.tight_layout(pad=0.2, h_pad=0.4, w_pad=0.6)
        out = os.path.join(OUT, "fig_failure_zones_col.pdf")
        fig.savefig(out)
        plt.close(fig)
    print(f"[failure zones col] -> {out}")


def fig_beta_col():
    rows = read_csv(os.path.join(HERE, "beta_results.csv"))
    xs = [float(r["equiv_full_spread"]) for r in rows]
    ys = [float(r["pct_vss"]) for r in rows]
    beta_full, _ = crossing(xs, ys, 2.0)
    two_point_full = 0.3556  # Step 5, Experiment A, %VSS > 2%
    with plt.rc_context(COL):
        fig, ax = plt.subplots(figsize=(3.5, 2.3))
        ax.plot(xs, ys, "o-", color="#0072B2", lw=1.2, ms=3, label="Seven-point Beta FE yield")
        ax.axhline(2.0, color="0.4", ls=":", lw=0.8)
        ax.axvline(beta_full, color="#D55E00", ls="--", lw=1.0,
                   label=f"Beta crossing (full {beta_full:.3f} / half {beta_full / 2:.3f})")
        ax.axvline(two_point_full, color="#009E73", ls="-.", lw=1.0,
                   label=f"Two-point crossing (full {two_point_full:.3f} / half {two_point_full / 2:.3f})")
        ax.set_xlabel(r"Equivalent full-range FE yield spread ($2\sigma$)")
        ax.set_ylabel("%VSS")
        ax.grid(True, alpha=0.25, lw=0.5)
        ax.legend(loc="upper left", frameon=False, handlelength=1.8, labelspacing=0.2, borderaxespad=0.2)
        fig.tight_layout(pad=0.2)
        out = os.path.join(OUT, "fig_beta_vs_twopoint_col.pdf")
        fig.savefig(out)
        plt.close(fig)
    print(f"[beta col] crossing full {beta_full:.4f} -> {out}")


def fig_decision_map_col():
    rows = read_csv(os.path.join(ROOT, "results", "Step6", "step6_robustness_results.csv"))
    penalties = sorted({float(r["v_d"]) for r in rows})
    warn, crit, svc, above_l = [], [], [], []
    for v in penalties:
        sub = sorted((r for r in rows if float(r["v_d"]) == v), key=lambda r: float(r["fe_spread"]))
        h = [float(r["fe_spread"]) for r in sub]
        pv = [float(r["pct_vss"]) for r in sub]
        gp = [float(r["unmet_gap"]) for r in sub]
        w, above = crossing(h, pv, 1.5)
        warn.append(w); above_l.append(above)
        crit.append(crossing(h, pv, 2.0)[0])
        svc.append(crossing(h, gp, 1.0)[0])
    g_end, y_end = min(warn) - 0.005, max(crit) + 0.005
    with plt.rc_context(COL):
        fig, ax = plt.subplots(figsize=(3.5, 2.75))
        ax.axvspan(0.0, g_end, color="#009E73", alpha=0.15)
        ax.axvspan(g_end, y_end, color="#F0E442", alpha=0.30)
        ax.axvspan(y_end, 0.28, color="#D55E00", alpha=0.15)
        for w, v, above in zip(warn, penalties, above_l):
            ax.plot([w], [v], "o", color="#E69F00", ms=5, mfc="white" if above else "#E69F00", mew=1.2, zorder=5)
        ax.plot(warn, penalties, "--", color="#E69F00", lw=1.2, zorder=4)
        ax.plot([], [], "o--", color="#E69F00", ms=5, lw=1.2, label="%VSS > 1.5%")
        ax.plot(crit, penalties, "s-", color="#D55E00", lw=1.3, ms=4.5, label="%VSS > 2%", zorder=5)
        ax.plot(svc, penalties, "^:", color="#0072B2", lw=1.2, ms=5, label="Service gap > 1", zorder=5)
        ax.text(g_end / 2, 8.4, "below\n1.5%", fontsize=7.5, ha="center", va="center")
        ax.text((g_end + y_end) / 2, 8.4, "1.5%\nto 2%", fontsize=7.5, ha="center", va="center")
        ax.text((y_end + 0.28) / 2, 8.4, "above 2%,\nservice gap", fontsize=7.5, ha="center", va="center")
        ax.text(0.004, 0.25, "base instance only", fontsize=7.5, style="italic", color="0.25", ha="left", va="bottom")
        ax.set_xlim(0.0, 0.28)
        ax.set_ylim(0.0, 9.0)
        ax.set_xlabel("FE yield spread (half-range)")
        ax.set_ylabel("Shortage penalty ($/device)")
        ax2 = ax.twinx()
        ax2.set_ylim(0.0, 90.0)
        ax2.set_ylabel("Penalty/price (%)", color="0.35")
        ax2.tick_params(axis="y", labelcolor="0.35")
        ax.grid(True, alpha=0.25, lw=0.5)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3, frameon=False, fontsize=7.5,
                  handlelength=1.8, columnspacing=0.9)
        fig.tight_layout(pad=0.2)
        out = os.path.join(OUT, "fig_decision_map_col.pdf")
        fig.savefig(out)
        plt.close(fig)
    print(f"[decision map col] warn {[round(w, 4) for w in warn]} crit {[round(c, 4) for c in crit]} "
          f"svc {[round(s_, 4) for s_ in svc]} -> {out}")


def replot_capacity_and_sensitivity():
    """Re-draw fig_capacity_cliff.png, fig_param_sensitivity.png and
    fig_mean_mapping.png from their saved CSVs (no solves), with the raised
    font sizes now set in the two experiment scripts."""
    import capacity_cliff_sweep as cc
    import param_sensitivity_revision as ps
    cdir = os.path.join(ROOT, "results", "Revision", "CapacityCliff")
    curves = read_csv(os.path.join(cdir, "cliff_curves.csv"))
    for r in curves:
        r["level"] = float(r["level"]); r["half"] = float(r["half"])
    onsets = read_csv(os.path.join(cdir, "cliff_onsets.csv"))
    cc.make_figure(curves, onsets)
    pdir = os.path.join(ROOT, "results", "Revision", "ParamSensitivity")
    thr = read_csv(os.path.join(pdir, "ofat_thresholds.csv"))
    for r in thr:
        r["level"] = float(r["level"]); r["is_base"] = int(r["is_base"])
    mapping = read_csv(os.path.join(pdir, "mean_mapping.csv"))
    for r in mapping:
        r["fe_mean_nominal"] = float(r["fe_mean_nominal"])
    rho = float(mapping[0]["N_max"]) - float(mapping[0]["L_G"])
    rho = rho / float(mapping[0]["N_bar"])          # (N_max - L_G) / N_bar, same for every mean
    ps.make_figures(thr, mapping, {"rho": rho})
    print(f"[replot] capacity, sensitivity, mean mapping (rho = {rho:.5f})")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    fig_vss_vs_spread()
    fig_service_cliff()
    fig_beta()
    fig_decision_map()
