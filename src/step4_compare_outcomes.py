"""
step4_compare_outcomes.py
=========================
Step 4: Compare planning outcomes — Measure profit, inventory, and service
differences between average-yield (EV/EEV) and stochastic (RP) planning.

Purpose
-------
Steps 2 and 3 generated experimental data across 94 experiments (49 from
Step 2's grid + 45 from Step 3's ramp-ups).  Step 4 takes that data and
formally compares the two planning approaches across three outcome
dimensions:

    1. PROFIT:    Expected profit (RP vs EEV) and VSS across conditions
    2. SERVICE:   Expected unmet demand (RP vs EEV) — the customer impact
    3. INVENTORY:  Expected die-bank inventory (RP vs EEV) — the buffer usage
    4. DECISIONS:  First-stage wafer allocation and outsourcing differences

This step does NOT run new optimization models.  It re-runs the Step 3
experiments (which are the cleanest, controlled ramp-ups) and produces
structured comparison tables and figures that quantify how much WORSE
the deterministic plan performs, and WHERE that gap comes from.

Connection to the literature:
    - Rashidi et al. (Table 5, Figures 4-7) present similar comparisons:
      expected profit, wafer starts, outsourcing, and unmet demand across
      uncertainty levels.  Our comparisons follow the same structure but
      focus specifically on RP-vs-EEV differences (which Rashidi reports
      as %VSS in Figure 7).
    - Escudero et al. define VSS = RP - EEV as the formal measure of
      planning quality loss, which we adopt throughout.

Outputs
-------
    step4_comparison_table.csv         Structured comparison across all experiments
    step4_fig1_profit_gap.png          Profit difference (RP - EEV) by uncertainty
    step4_fig2_service_gap.png         Unmet demand difference by uncertainty
    step4_fig3_decision_divergence.png Wafer allocation divergence by uncertainty
    step4_fig4_combined_dashboard.png  Four-panel dashboard summarizing all outcomes
    step4_summary_report.txt           Plain-language summary of findings

Usage
-----
    python step4_compare_outcomes.py

Requirements: Python 3.9+, PuLP  (pip install pulp)
Optional:     matplotlib         (pip install matplotlib)
"""

import sys
import csv
import os
import datetime
from itertools import product as cartesian

# ---- Import from Step 2 frozen framework ----------------------------
try:
    from step2_freeze_model import (
        FrozenInstance, run_experiment, build_scenarios,
        solve_rp, solve_rp_fixed,
    )
    print("[ok] Imported from step2_freeze_model.py")
except ImportError:
    print("[error] Could not import step2_freeze_model.")
    print("        Make sure step2_freeze_model.py is in the same directory.")
    sys.exit(1)

# ---- Matplotlib (optional) ------------------------------------------
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("[warning] matplotlib not installed — skipping figures.")


# ======================================================================
# 1.  CONSTANTS — Same experimental design as Step 3
# ======================================================================

FE_MEAN = (FrozenInstance.STEP1_FE_LO + FrozenInstance.STEP1_FE_HI) / 2  # 0.875
BE_MEAN = (FrozenInstance.STEP1_BE_LO + FrozenInstance.STEP1_BE_HI) / 2  # 0.800

STEP1_FE_SPREAD = FrozenInstance.STEP1_FE_HI - FrozenInstance.STEP1_FE_LO  # 0.15
STEP1_BE_SPREAD = FrozenInstance.STEP1_BE_HI - FrozenInstance.STEP1_BE_LO  # 0.20

# Same 15 spread levels as Step 3
SPREAD_STEPS = [0.02, 0.04, 0.06, 0.08, 0.10,
                0.12, 0.15, 0.18, 0.20, 0.25,
                0.30, 0.35, 0.40, 0.45, 0.50]


def make_yields(mean, spread):
    """Compute (lo, hi) from mean and spread, clamped to (0.01, 1.00)."""
    lo = max(0.01, mean - spread / 2)
    hi = min(1.00, mean + spread / 2)
    return lo, hi


# ======================================================================
# 2.  RE-RUN STEP 3 EXPERIMENTS WITH EXTENDED METRICS
# ======================================================================
#
# We re-run the same three ramp-ups from Step 3.  The run_experiment()
# function from Step 2 already returns all the metrics we need:
#   - rp_obj, eev_obj, vss, pct_vss        (profit)
#   - rp_exp_unmet, eev_exp_unmet           (service)
#   - rp_exp_inv, eev_exp_inv               (inventory)
#   - rp_xf_fe1, rp_xf_fe2, ev_xf_fe1, ev_xf_fe2  (wafer allocation)
#   - rp_outsource_fe, ev_outsource_fe      (outsourcing)
#   - rp_outsource_be, ev_outsource_be
#
# Step 4 adds derived COMPARISON metrics to each result:
#   - profit_gap       = rp_obj - eev_obj       (= VSS, $ better off with RP)
#   - unmet_gap        = eev_exp_unmet - rp_exp_unmet  (extra unmet under EV)
#   - inv_gap          = rp_exp_inv - eev_exp_inv      (RP vs EEV inventory)
#   - fe2_gap          = rp_xf_fe2 - ev_xf_fe2  (extra FE2 hedging under RP)
#   - total_starts_gap = rp_total_starts - ev_total_starts

def enrich_with_comparisons(r):
    """
    Add derived comparison metrics to an experiment result dict.

    These metrics directly answer the Step 4 question: "How do the two
    planning approaches differ in their outcomes?"

    Positive values mean RP is doing MORE of something than EV:
      - profit_gap > 0:  RP earns more profit (this is the VSS)
      - unmet_gap > 0:   EV has MORE unmet demand than RP (RP serves better)
      - inv_gap:         Difference in die-bank inventory
      - fe2_gap > 0:     RP starts MORE wafers at FE2 (hedging)
      - total_starts_gap > 0: RP starts MORE total wafers (insurance)
    """
    r["profit_gap"]       = r["vss"]  # Same as rp_obj - eev_obj
    r["unmet_gap"]        = r["eev_exp_unmet"] - r["rp_exp_unmet"]
    r["inv_gap"]          = r["rp_exp_inv"] - r["eev_exp_inv"]
    r["fe2_gap"]          = r["rp_xf_fe2"] - r["ev_xf_fe2"]
    r["total_starts_gap"] = r["rp_total_starts"] - r["ev_total_starts"]

    # Service fill rate proxy:  what fraction of expected demand is met?
    # Expected demand = 0.5 * 600 + 0.5 * 900 = 750
    exp_demand = 750.0
    r["rp_fill_rate"]  = 100.0 * (1.0 - r["rp_exp_unmet"] / exp_demand)
    r["eev_fill_rate"] = 100.0 * (1.0 - r["eev_exp_unmet"] / exp_demand)
    r["fill_rate_gap"] = r["rp_fill_rate"] - r["eev_fill_rate"]

    return r


def run_all_experiments():
    """
    Re-run the three Step 3 ramp-up experiments and enrich each result
    with comparison metrics.

    Returns three lists of enriched result dicts.
    """
    print(f"\n{'='*60}")
    print(f"  STEP 4: Running experiments for outcome comparison")
    print(f"{'='*60}")

    results_a = []  # FE only
    results_b = []  # BE only
    results_c = []  # Both

    # --- Experiment A: FE uncertainty ramp-up --------------------------
    print(f"\n  Experiment A: FE uncertainty only (BE fixed at {STEP1_BE_SPREAD})")
    be_lo, be_hi = make_yields(BE_MEAN, STEP1_BE_SPREAD)
    for i, fe_sp in enumerate(SPREAD_STEPS):
        fe_lo, fe_hi = make_yields(FE_MEAN, fe_sp)
        fi = FrozenInstance(fe_lo, fe_hi, be_lo, be_hi)
        r = run_experiment(fi, label=f"A_FEsp{fe_sp:.2f}")
        r["experiment"] = "A_FE_only"
        r["ramp_spread"] = fe_sp
        r = enrich_with_comparisons(r)
        results_a.append(r)
        print(f"    [{i+1:>2d}/15] spread={fe_sp:.2f}  "
              f"VSS=${r['vss']:>7.2f}  "
              f"unmet_gap={r['unmet_gap']:>6.2f}  "
              f"FE2_gap={r['fe2_gap']:>5.2f}")

    # --- Experiment B: BE uncertainty ramp-up --------------------------
    print(f"\n  Experiment B: BE uncertainty only (FE fixed at {STEP1_FE_SPREAD})")
    fe_lo, fe_hi = make_yields(FE_MEAN, STEP1_FE_SPREAD)
    for i, be_sp in enumerate(SPREAD_STEPS):
        be_lo, be_hi = make_yields(BE_MEAN, be_sp)
        fi = FrozenInstance(fe_lo, fe_hi, be_lo, be_hi)
        r = run_experiment(fi, label=f"B_BEsp{be_sp:.2f}")
        r["experiment"] = "B_BE_only"
        r["ramp_spread"] = be_sp
        r = enrich_with_comparisons(r)
        results_b.append(r)
        print(f"    [{i+1:>2d}/15] spread={be_sp:.2f}  "
              f"VSS=${r['vss']:>7.2f}  "
              f"unmet_gap={r['unmet_gap']:>6.2f}  "
              f"FE2_gap={r['fe2_gap']:>5.2f}")

    # --- Experiment C: Both uncertainty ramp-up ------------------------
    print(f"\n  Experiment C: Both FE and BE uncertainty together")
    for i, sp in enumerate(SPREAD_STEPS):
        fe_lo, fe_hi = make_yields(FE_MEAN, sp)
        be_lo, be_hi = make_yields(BE_MEAN, sp)
        fi = FrozenInstance(fe_lo, fe_hi, be_lo, be_hi)
        r = run_experiment(fi, label=f"C_sp{sp:.2f}")
        r["experiment"] = "C_both"
        r["ramp_spread"] = sp
        r = enrich_with_comparisons(r)
        results_c.append(r)
        print(f"    [{i+1:>2d}/15] spread={sp:.2f}  "
              f"VSS=${r['vss']:>7.2f}  "
              f"unmet_gap={r['unmet_gap']:>6.2f}  "
              f"FE2_gap={r['fe2_gap']:>5.2f}")

    return results_a, results_b, results_c


# ======================================================================
# 3.  SAVE COMPARISON TABLE (CSV)
# ======================================================================

def save_comparison_csv(results_a, results_b, results_c,
                        filepath="step4_comparison_table.csv"):
    """
    Save the full comparison table.  Each row is one experiment.

    The columns are organized into groups:
      [Experiment ID]  experiment, ramp_spread
      [Yield Config]   fe_spread, be_spread, fe_mean, be_mean
      [Profit]         rp_obj, eev_obj, profit_gap (=VSS), pct_vss
      [Service]        rp_exp_unmet, eev_exp_unmet, unmet_gap,
                       rp_fill_rate, eev_fill_rate, fill_rate_gap
      [Inventory]      rp_exp_inv, eev_exp_inv, inv_gap
      [Decisions]      rp_xf_fe1, rp_xf_fe2, ev_xf_fe1, ev_xf_fe2,
                       fe2_gap, total_starts_gap,
                       rp_outsource_fe, ev_outsource_fe,
                       rp_outsource_be, ev_outsource_be
    """
    all_results = results_a + results_b + results_c

    fieldnames = [
        # Experiment ID
        "experiment", "ramp_spread",
        # Yield configuration
        "fe_spread", "be_spread", "fe_mean", "be_mean",
        # Profit comparison
        "rp_obj", "eev_obj", "profit_gap", "pct_vss",
        # Service comparison
        "rp_exp_unmet", "eev_exp_unmet", "unmet_gap",
        "rp_fill_rate", "eev_fill_rate", "fill_rate_gap",
        # Inventory comparison
        "rp_exp_inv", "eev_exp_inv", "inv_gap",
        # Decision comparison
        "rp_xf_fe1", "rp_xf_fe2", "ev_xf_fe1", "ev_xf_fe2",
        "fe2_gap", "total_starts_gap",
        "rp_outsource_fe", "ev_outsource_fe",
        "rp_outsource_be", "ev_outsource_be",
    ]

    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames,
                                extrasaction="ignore")
        writer.writeheader()
        for r in all_results:
            row = {}
            for k in fieldnames:
                v = r.get(k, "")
                if isinstance(v, float):
                    row[k] = f"{v:.4f}"
                else:
                    row[k] = v
            writer.writerow(row)

    print(f"\n  [saved] {filepath}  ({len(all_results)} rows)")


# ======================================================================
# 4.  VISUALIZATIONS
# ======================================================================

def plot_profit_gap(results_a, results_b, results_c,
                    filepath="step4_fig1_profit_gap.png"):
    """
    Figure 1: Profit Gap (VSS) — How much more profit does stochastic
    planning earn compared to deterministic planning?

    This is the central economic comparison.  It directly answers:
    "If I switch from average-yield planning to stochastic planning,
     how much additional profit do I capture?"

    Connection to literature: This corresponds to Rashidi et al. Figure 7
    (%VSS vs deviation level) and Escudero et al.'s VSS definition.
    """
    if not HAS_MPL:
        print("  [skip] No matplotlib.")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

    for results, label, color, marker in [
        (results_a, "A: FE only", "#2563EB", "o"),
        (results_b, "B: BE only", "#DC2626", "s"),
        (results_c, "C: Both",    "#059669", "D"),
    ]:
        sp = [r["ramp_spread"] for r in results]
        vss = [r["profit_gap"] for r in results]
        pct = [r["pct_vss"] for r in results]

        ax1.plot(sp, vss, f"{marker}-", color=color, linewidth=2,
                 markersize=6, label=label)
        ax2.plot(sp, pct, f"{marker}-", color=color, linewidth=2,
                 markersize=6, label=label)

    # Mark Step 1 baseline
    for ax in [ax1, ax2]:
        ax.axvline(x=STEP1_FE_SPREAD, color="#2563EB", linestyle=":",
                   alpha=0.4, linewidth=1, label="_nolegend_")
        ax.axvline(x=STEP1_BE_SPREAD, color="#DC2626", linestyle=":",
                   alpha=0.4, linewidth=1, label="_nolegend_")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=10)

    ax1.set_xlabel("Yield Spread (hi - lo)", fontsize=12)
    ax1.set_ylabel("Profit Gap: RP − EEV ($)", fontsize=12)
    ax1.set_title("Profit Advantage of Stochastic Planning ($)",
                  fontsize=13, fontweight="bold")

    ax2.set_xlabel("Yield Spread (hi - lo)", fontsize=12)
    ax2.set_ylabel("%VSS (profit gap as % of RP profit)", fontsize=12)
    ax2.set_title("Profit Advantage as % of Total Profit",
                  fontsize=13, fontweight="bold")

    fig.suptitle("Step 4 — Profit Comparison: Stochastic vs Deterministic Planning\n"
                 "How much profit is left on the table by ignoring uncertainty?",
                 fontsize=14, fontweight="bold", y=1.03)
    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [saved] {filepath}")


def plot_service_gap(results_a, results_b, results_c,
                     filepath="step4_fig2_service_gap.png"):
    """
    Figure 2: Service Level Gap — How many more customer orders go unfilled
    under deterministic planning?

    Two panels:
      Left:  Absolute unmet demand for RP vs EEV
      Right: The GAP (EEV unmet - RP unmet) — extra unfilled orders from
             using the simpler approach

    Connection to literature: Rashidi et al. (Table 5) report "Average
    Unmet Demand" columns, showing how unmet demand changes with
    uncertainty levels.  Our comparison goes further by isolating the
    DIFFERENCE attributable to the planning approach choice.
    """
    if not HAS_MPL:
        print("  [skip] No matplotlib.")
        return

    fig, axes = plt.subplots(1, 3, figsize=(17, 5.5))

    datasets = [
        (results_a, "A: FE Uncertainty Only", "#2563EB"),
        (results_b, "B: BE Uncertainty Only", "#DC2626"),
        (results_c, "C: Both Together",       "#059669"),
    ]

    for ax, (results, title, color) in zip(axes, datasets):
        sp = [r["ramp_spread"] for r in results]
        rp_unmet  = [r["rp_exp_unmet"] for r in results]
        eev_unmet = [r["eev_exp_unmet"] for r in results]
        gap       = [r["unmet_gap"] for r in results]

        ax.plot(sp, eev_unmet, "s-", color="#F59E0B", linewidth=2,
                markersize=5, label="Deterministic (EEV)")
        ax.plot(sp, rp_unmet, "o-", color=color, linewidth=2,
                markersize=5, label="Stochastic (RP)")

        # Shade the gap region
        ax.fill_between(sp, rp_unmet, eev_unmet, alpha=0.15,
                        color=color, label="Service gap (EEV − RP)")

        ax.set_xlabel("Yield Spread", fontsize=11)
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.legend(fontsize=8, loc="best")
        ax.grid(True, alpha=0.3)

    axes[0].set_ylabel("Expected Unmet Demand (units)", fontsize=11)

    fig.suptitle("Step 4 — Service Level Comparison\n"
                 "Shaded area = additional customer orders lost by "
                 "using deterministic planning",
                 fontsize=13, fontweight="bold", y=1.04)
    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [saved] {filepath}")


def plot_decision_divergence(results_a, results_b, results_c,
                             filepath="step4_fig3_decision_divergence.png"):
    """
    Figure 3: Decision Divergence — How differently do the two planning
    approaches allocate resources?

    Tracks the FE2 wafer start gap (RP_FE2 - EV_FE2) and total wafer
    start gap across experiments.

    This shows the MECHANISM behind the profit and service differences:
    RP allocates more wafers to the backup facility as insurance.

    Connection to literature: Rashidi et al. (Figure 5) show how wafer
    starts change with uncertainty.  Our figure focuses specifically on
    the DIVERGENCE between RP and EV decisions, which is the operational
    consequence of the planning approach choice.
    """
    if not HAS_MPL:
        print("  [skip] No matplotlib.")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

    for results, label, color, marker in [
        (results_a, "A: FE only", "#2563EB", "o"),
        (results_b, "B: BE only", "#DC2626", "s"),
        (results_c, "C: Both",    "#059669", "D"),
    ]:
        sp = [r["ramp_spread"] for r in results]
        fe2_gap = [r["fe2_gap"] for r in results]
        total_gap = [r["total_starts_gap"] for r in results]

        ax1.plot(sp, fe2_gap, f"{marker}-", color=color, linewidth=2,
                 markersize=6, label=label)
        ax2.plot(sp, total_gap, f"{marker}-", color=color, linewidth=2,
                 markersize=6, label=label)

    for ax in [ax1, ax2]:
        ax.axhline(y=0, color="gray", linestyle="-", alpha=0.3)
        ax.axvline(x=STEP1_FE_SPREAD, color="#2563EB", linestyle=":",
                   alpha=0.4, linewidth=1)
        ax.axvline(x=STEP1_BE_SPREAD, color="#DC2626", linestyle=":",
                   alpha=0.4, linewidth=1)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=10)

    ax1.set_xlabel("Yield Spread", fontsize=12)
    ax1.set_ylabel("FE2 Wafer Start Gap (RP − EV)", fontsize=12)
    ax1.set_title("Backup Facility (FE2) Hedging Gap\n"
                  "How many MORE wafers does RP start at FE2?",
                  fontsize=12, fontweight="bold")

    ax2.set_xlabel("Yield Spread", fontsize=12)
    ax2.set_ylabel("Total Wafer Start Gap (RP − EV)", fontsize=12)
    ax2.set_title("Total Production Hedging Gap\n"
                  "How many MORE total wafers does RP start?",
                  fontsize=12, fontweight="bold")

    fig.suptitle("Step 4 — Decision Divergence: "
                 "How Differently Do the Two Approaches Plan?",
                 fontsize=14, fontweight="bold", y=1.03)
    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [saved] {filepath}")


def plot_combined_dashboard(results_a, results_b, results_c,
                            filepath="step4_fig4_combined_dashboard.png"):
    """
    Figure 4: Combined Dashboard — All four comparison dimensions in
    one figure, using Experiment A (FE uncertainty only) as the
    primary illustration.

    This is the "at a glance" figure.  Four panels:
      Top-left:     Profit gap (VSS)
      Top-right:    Service gap (extra unmet demand under EV)
      Bottom-left:  Decision divergence (FE2 hedging gap)
      Bottom-right: Absolute RP profit vs EEV profit

    Why Experiment A?  Because FE uncertainty is the primary driver
    of the planning approach difference (as established in Step 3).
    Experiment A gives the clearest illustration.
    """
    if not HAS_MPL:
        print("  [skip] No matplotlib.")
        return

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    sp = [r["ramp_spread"] for r in results_a]

    color_rp  = "#2563EB"
    color_eev = "#F59E0B"
    color_gap = "#059669"

    # --- Top-left: VSS ($) -------------------------------------------
    ax = axes[0, 0]
    vss = [r["profit_gap"] for r in results_a]
    ax.bar(sp, vss, width=0.018, color=color_gap, alpha=0.8, edgecolor="white")
    ax.set_ylabel("VSS ($)", fontsize=11)
    ax.set_title("Profit Gap (RP − EEV)", fontsize=12, fontweight="bold")
    ax.grid(True, axis="y", alpha=0.3)
    # Annotate max
    max_idx = vss.index(max(vss))
    ax.annotate(f"${vss[max_idx]:.0f}", xy=(sp[max_idx], vss[max_idx]),
                xytext=(sp[max_idx]+0.03, vss[max_idx]+5),
                fontsize=9, fontweight="bold", color=color_gap)

    # --- Top-right: Unmet demand gap ---------------------------------
    ax = axes[0, 1]
    rp_unmet  = [r["rp_exp_unmet"] for r in results_a]
    eev_unmet = [r["eev_exp_unmet"] for r in results_a]
    ax.plot(sp, eev_unmet, "s-", color=color_eev, linewidth=2,
            markersize=5, label="Deterministic (EEV)")
    ax.plot(sp, rp_unmet, "o-", color=color_rp, linewidth=2,
            markersize=5, label="Stochastic (RP)")
    ax.fill_between(sp, rp_unmet, eev_unmet, alpha=0.15, color="#DC2626")
    ax.set_ylabel("Expected Unmet Demand", fontsize=11)
    ax.set_title("Service Level Gap", fontsize=12, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    # --- Bottom-left: FE2 hedging gap --------------------------------
    ax = axes[1, 0]
    rp_fe2 = [r["rp_xf_fe2"] for r in results_a]
    ev_fe2 = [r["ev_xf_fe2"] for r in results_a]
    ax.plot(sp, rp_fe2, "o-", color=color_rp, linewidth=2,
            markersize=5, label="RP: FE2 starts")
    ax.plot(sp, ev_fe2, "s-", color=color_eev, linewidth=2,
            markersize=5, label="EV: FE2 starts")
    ax.fill_between(sp, ev_fe2, rp_fe2, alpha=0.15, color=color_rp)
    ax.set_xlabel("FE Yield Spread", fontsize=11)
    ax.set_ylabel("Wafer Starts at FE2", fontsize=11)
    ax.set_title("FE2 Hedging: RP vs EV", fontsize=12, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    # --- Bottom-right: Absolute profits ------------------------------
    ax = axes[1, 1]
    rp_profit  = [r["rp_obj"] for r in results_a]
    eev_profit = [r["eev_obj"] for r in results_a]
    ax.plot(sp, rp_profit, "o-", color=color_rp, linewidth=2,
            markersize=5, label="Stochastic (RP)")
    ax.plot(sp, eev_profit, "s-", color=color_eev, linewidth=2,
            markersize=5, label="Deterministic (EEV)")
    ax.fill_between(sp, eev_profit, rp_profit, alpha=0.1, color=color_gap)
    ax.set_xlabel("FE Yield Spread", fontsize=11)
    ax.set_ylabel("Expected Profit ($)", fontsize=11)
    ax.set_title("Absolute Expected Profit", fontsize=12, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    fig.suptitle("Step 4 — Outcome Comparison Dashboard (Experiment A: FE Uncertainty)\n"
                 "Four dimensions of the planning approach difference",
                 fontsize=14, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [saved] {filepath}")


def plot_motivation_service_cliff(results_a,
                                  filepath="motivation_service_cliff.png"):
    """
    Motivation Figure:
    Clean FE-only service cliff showing deterministic failure region.

    - Uses Experiment A only (FE uncertainty only)
    - Shows service gap visually
    - Adds threshold marker (full-range ≈ 0.35)
    - Generates a separate new figure
    """

    if not HAS_MPL:
        print("  [skip] No matplotlib.")
        return

    fig, ax = plt.subplots(figsize=(8, 5))

    # Extract FE-only data
    sp = [r["ramp_spread"] for r in results_a]
    rp_unmet  = [r["rp_exp_unmet"] for r in results_a]
    eev_unmet = [r["eev_exp_unmet"] for r in results_a]

    # Plot deterministic and stochastic
    ax.plot(sp, eev_unmet, "s-", color="#F59E0B",
            linewidth=2.5, markersize=6, label="Deterministic (EEV)")
    ax.plot(sp, rp_unmet, "o-", color="#2563EB",
            linewidth=2.5, markersize=6, label="Stochastic (RP)")

    # Shade service gap
    ax.fill_between(sp, rp_unmet, eev_unmet,
                    alpha=0.2, color="#DC2626",
                    label="Service gap")

    # Add threshold line (full-range ≈ 0.35)
    threshold_full_range = 0.35
    ax.axvline(x=threshold_full_range,
               linestyle="--",
               linewidth=2,
               color="black")

    ax.text(threshold_full_range + 0.01,
            max(eev_unmet) - 1,
            "Planning Threshold\n≈ 0.35 (full-range)",
            fontsize=9,
            verticalalignment="top")

    # Labels
    ax.set_xlabel("Yield Spread (high − low)", fontsize=12)
    ax.set_ylabel("Expected Unmet Demand (units)", fontsize=12)
    ax.set_title("Deterministic Planning Service \"Cliff\" Effect",
                 fontsize=13, fontweight="bold")

    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(filepath, dpi=300, bbox_inches="tight")
    plt.close(fig)

    print(f"  [saved] {filepath}")


# ======================================================================
# 5.  SUMMARY REPORT — Plain language findings
# ======================================================================

def generate_summary_report(results_a, results_b, results_c,
                            filepath="step4_summary_report.txt"):
    """
    Generate a structured plain-language report summarizing the
    Step 4 comparison findings.

    This report is written so it can be directly referenced when
    writing the ITC 2026 paper.
    """

    lines = []
    lines.append("=" * 70)
    lines.append("  STEP 4: PLANNING OUTCOME COMPARISON — SUMMARY REPORT")
    lines.append(f"  Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 70)

    # --- Section 1: Profit Comparison ---------------------------------
    lines.append("")
    lines.append("1. PROFIT COMPARISON (RP vs EEV)")
    lines.append("-" * 50)

    for label, results, desc in [
        ("Exp A (FE only)", results_a, "BE spread fixed at 0.20"),
        ("Exp B (BE only)", results_b, "FE spread fixed at 0.15"),
        ("Exp C (both)",    results_c, "FE and BE spread move together"),
    ]:
        vss_vals = [r["profit_gap"] for r in results]
        pct_vals = [r["pct_vss"] for r in results]
        spreads  = [r["ramp_spread"] for r in results]

        lines.append(f"\n  {label}  ({desc})")
        lines.append(f"    Spread range:        {spreads[0]:.2f} to {spreads[-1]:.2f}")
        lines.append(f"    VSS range:           ${min(vss_vals):.2f} to ${max(vss_vals):.2f}")
        lines.append(f"    %VSS range:          {min(pct_vals):.2f}% to {max(pct_vals):.2f}%")
        lines.append(f"    Max VSS at spread:   {spreads[vss_vals.index(max(vss_vals))]:.2f}")

        # Profit levels
        rp_min = min(r["rp_obj"] for r in results)
        rp_max = max(r["rp_obj"] for r in results)
        eev_min = min(r["eev_obj"] for r in results)
        eev_max = max(r["eev_obj"] for r in results)
        lines.append(f"    RP profit range:     ${rp_min:.2f} to ${rp_max:.2f}")
        lines.append(f"    EEV profit range:    ${eev_min:.2f} to ${eev_max:.2f}")

    # --- Section 2: Service Level Comparison --------------------------
    lines.append("")
    lines.append("")
    lines.append("2. SERVICE LEVEL COMPARISON (Unmet Demand)")
    lines.append("-" * 50)

    for label, results, desc in [
        ("Exp A (FE only)", results_a, "BE spread fixed at 0.20"),
        ("Exp B (BE only)", results_b, "FE spread fixed at 0.15"),
        ("Exp C (both)",    results_c, "FE and BE spread move together"),
    ]:
        gaps = [r["unmet_gap"] for r in results]
        spreads = [r["ramp_spread"] for r in results]
        rp_unmet_range = (min(r["rp_exp_unmet"] for r in results),
                          max(r["rp_exp_unmet"] for r in results))
        eev_unmet_range = (min(r["eev_exp_unmet"] for r in results),
                           max(r["eev_exp_unmet"] for r in results))

        lines.append(f"\n  {label}  ({desc})")
        lines.append(f"    RP unmet demand:     {rp_unmet_range[0]:.2f} to "
                     f"{rp_unmet_range[1]:.2f} units")
        lines.append(f"    EEV unmet demand:    {eev_unmet_range[0]:.2f} to "
                     f"{eev_unmet_range[1]:.2f} units")
        lines.append(f"    Service gap range:   {min(gaps):.2f} to {max(gaps):.2f} "
                     f"extra units unmet under EV")

        # Fill rate comparison
        rp_fr = [r["rp_fill_rate"] for r in results]
        eev_fr = [r["eev_fill_rate"] for r in results]
        lines.append(f"    RP fill rate:        {min(rp_fr):.1f}% to {max(rp_fr):.1f}%")
        lines.append(f"    EEV fill rate:       {min(eev_fr):.1f}% to {max(eev_fr):.1f}%")

        # Where does the gap emerge?
        threshold_idx = None
        for i in range(len(gaps)):
            if gaps[i] > 0.5:  # More than 0.5 units difference
                threshold_idx = i
                break
        if threshold_idx is not None:
            lines.append(f"    Gap first exceeds 0.5 units at spread = "
                         f"{spreads[threshold_idx]:.2f}")
        else:
            lines.append(f"    Gap stays below 0.5 units across all spreads")

    # --- Section 3: Inventory Comparison ------------------------------
    lines.append("")
    lines.append("")
    lines.append("3. INVENTORY COMPARISON (Die-Bank)")
    lines.append("-" * 50)

    all_inv_gaps = ([r["inv_gap"] for r in results_a] +
                    [r["inv_gap"] for r in results_b] +
                    [r["inv_gap"] for r in results_c])
    rp_invs = ([r["rp_exp_inv"] for r in results_a] +
               [r["rp_exp_inv"] for r in results_b] +
               [r["rp_exp_inv"] for r in results_c])
    eev_invs = ([r["eev_exp_inv"] for r in results_a] +
                [r["eev_exp_inv"] for r in results_b] +
                [r["eev_exp_inv"] for r in results_c])

    lines.append(f"  Across all 45 experiments:")
    lines.append(f"    RP die-bank inventory range:   {min(rp_invs):.2f} to "
                 f"{max(rp_invs):.2f}")
    lines.append(f"    EEV die-bank inventory range:  {min(eev_invs):.2f} to "
                 f"{max(eev_invs):.2f}")
    lines.append(f"    Inventory gap range:           {min(all_inv_gaps):.2f} to "
                 f"{max(all_inv_gaps):.2f}")
    lines.append(f"")
    lines.append(f"  Interpretation: With the current cost structure (shortage")
    lines.append(f"  penalty $3/unit vs inventory holding $0.05/unit, a 60:1 ratio),")
    lines.append(f"  neither planning approach holds significant die-bank inventory.")
    lines.append(f"  The Die Bank functions as a pass-through, not a strategic buffer.")
    lines.append(f"  Hedging occurs at the wafer start level, not the inventory level.")

    # --- Section 4: Decision Divergence -------------------------------
    lines.append("")
    lines.append("")
    lines.append("4. DECISION DIVERGENCE (Wafer Allocation)")
    lines.append("-" * 50)

    for label, results, desc in [
        ("Exp A (FE only)", results_a, "BE spread fixed at 0.20"),
        ("Exp B (BE only)", results_b, "FE spread fixed at 0.15"),
        ("Exp C (both)",    results_c, "FE and BE spread move together"),
    ]:
        fe2_gaps = [r["fe2_gap"] for r in results]
        total_gaps = [r["total_starts_gap"] for r in results]
        spreads = [r["ramp_spread"] for r in results]

        lines.append(f"\n  {label}  ({desc})")
        lines.append(f"    FE2 gap range:       {min(fe2_gaps):.2f} to "
                     f"{max(fe2_gaps):.2f} extra wafers at FE2 under RP")
        lines.append(f"    Total starts gap:    {min(total_gaps):.2f} to "
                     f"{max(total_gaps):.2f} extra total wafers under RP")

        # Hedging cost
        extra_cost_min = min(total_gaps) * FrozenInstance.C_F
        extra_cost_max = max(total_gaps) * FrozenInstance.C_F
        lines.append(f"    Hedging cost range:  ${extra_cost_min:.2f} to "
                     f"${extra_cost_max:.2f} in extra FE wafer costs")

    # --- Section 5: Cross-cutting findings ----------------------------
    lines.append("")
    lines.append("")
    lines.append("5. CROSS-CUTTING FINDINGS")
    lines.append("-" * 50)

    # Compare sensitivities across experiments
    def avg_sensitivity(results, metric_key):
        """Average change in metric per unit spread."""
        if len(results) < 2:
            return 0
        sp_range = results[-1]["ramp_spread"] - results[0]["ramp_spread"]
        metric_range = results[-1][metric_key] - results[0][metric_key]
        return metric_range / sp_range if sp_range != 0 else 0

    lines.append("")
    lines.append("  VSS sensitivity ($ per unit of spread):")
    s_a = avg_sensitivity(results_a, "profit_gap")
    s_b = avg_sensitivity(results_b, "profit_gap")
    s_c = avg_sensitivity(results_c, "profit_gap")
    lines.append(f"    Exp A (FE only):  {s_a:>8.2f} $/unit-spread")
    lines.append(f"    Exp B (BE only):  {s_b:>8.2f} $/unit-spread")
    lines.append(f"    Exp C (both):     {s_c:>8.2f} $/unit-spread")

    lines.append("")
    lines.append("  Unmet demand sensitivity (units per unit of spread):")
    u_a = avg_sensitivity(results_a, "unmet_gap")
    u_b = avg_sensitivity(results_b, "unmet_gap")
    u_c = avg_sensitivity(results_c, "unmet_gap")
    lines.append(f"    Exp A (FE only):  {u_a:>8.2f} units/unit-spread")
    lines.append(f"    Exp B (BE only):  {u_b:>8.2f} units/unit-spread")
    lines.append(f"    Exp C (both):     {u_c:>8.2f} units/unit-spread")

    lines.append("")
    lines.append("  FE2 hedging sensitivity (wafers per unit of spread):")
    h_a = avg_sensitivity(results_a, "fe2_gap")
    h_b = avg_sensitivity(results_b, "fe2_gap")
    h_c = avg_sensitivity(results_c, "fe2_gap")
    lines.append(f"    Exp A (FE only):  {h_a:>8.2f} wafers/unit-spread")
    lines.append(f"    Exp B (BE only):  {h_b:>8.2f} wafers/unit-spread")
    lines.append(f"    Exp C (both):     {h_c:>8.2f} wafers/unit-spread")

    # --- Section 6: Key takeaways ------------------------------------
    lines.append("")
    lines.append("")
    lines.append("6. KEY TAKEAWAYS FOR STEP 5")
    lines.append("-" * 50)
    lines.append("")
    lines.append("  a) Profit gap (VSS) grows primarily with FE uncertainty.")
    lines.append("     FE spread drives the economic case for stochastic planning.")
    lines.append("")
    lines.append("  b) Service level gap (unmet demand) follows a similar pattern:")
    lines.append("     deterministic planning falls behind on service primarily")
    lines.append("     when FE uncertainty grows.  BE uncertainty hurts both")
    lines.append("     approaches equally (the 'no recourse' effect).")
    lines.append("")
    lines.append("  c) Die-bank inventory is near zero for both approaches")
    lines.append("     across all experiments.  The hedging mechanism operates")
    lines.append("     through wafer allocation (more FE2 starts), not through")
    lines.append("     inventory buffering.  This is driven by the 60:1 ratio")
    lines.append("     of shortage penalty to inventory holding cost.")
    lines.append("")
    lines.append("  d) Decision divergence (how differently the two approaches")
    lines.append("     plan) scales with FE uncertainty.  The FE2 hedging gap")
    lines.append("     widens steadily as FE spread increases, which is the")
    lines.append("     operational mechanism that produces the profit and")
    lines.append("     service advantages.")
    lines.append("")
    lines.append("  e) These results set up Step 5 (failure point identification):")
    lines.append("     the service gap data from Experiment A shows a breakpoint")
    lines.append("     where deterministic planning's service level starts")
    lines.append("     degrading faster, which will be formally quantified")
    lines.append("     in the next step.")
    lines.append("")
    lines.append("  Connection to Rashidi et al.:")
    lines.append("    - Rashidi found BE yield and demand uncertainty hurt profit most.")
    lines.append("    - Our results are consistent: BE uncertainty does hurt absolute")
    lines.append("      profit significantly (both RP and EEV profit decline).")
    lines.append("    - However, the DIFFERENCE between RP and EEV (which is what")
    lines.append("      VSS measures) is driven by FE uncertainty, because FE is")
    lines.append("      where recourse actions (hedging via wafer allocation) exist.")
    lines.append("    - This is a nuanced finding that extends the literature: the")
    lines.append("      question 'what hurts profit?' has a different answer from")
    lines.append("      'what makes your planning approach matter?'")
    lines.append("")

    # Write to file
    report_text = "\n".join(lines)
    with open(filepath, "w") as f:
        f.write(report_text)

    # Also print to console
    print(report_text)
    print(f"\n  [saved] {filepath}")


# ======================================================================
# 6.  MAIN
# ======================================================================

def main():
    print("=" * 60)
    print("  step4_compare_outcomes.py")
    print("  Compare planning outcomes: profit, service, inventory")
    print("=" * 60)

    # --- Run experiments with comparison metrics ----------------------
    results_a, results_b, results_c = run_all_experiments()

    # --- Save comparison table ----------------------------------------
    print("\n--- Saving comparison table ---")
    save_comparison_csv(results_a, results_b, results_c)

    # --- Generate figures ---------------------------------------------
    print("\n--- Generating comparison figures ---")
    plot_profit_gap(results_a, results_b, results_c)
    plot_service_gap(results_a, results_b, results_c)
    plot_decision_divergence(results_a, results_b, results_c)
    plot_combined_dashboard(results_a, results_b, results_c)
    plot_motivation_service_cliff(results_a)

    # --- Generate summary report --------------------------------------
    print("\n--- Generating summary report ---")
    generate_summary_report(results_a, results_b, results_c)

    # --- Final output list --------------------------------------------
    print(f"\n{'='*60}")
    print(f"  STEP 4 OUTPUTS")
    print(f"{'='*60}")
    print(f"  step4_comparison_table.csv            (45 experiments, full metrics)")
    print(f"  step4_fig1_profit_gap.png             Profit difference by uncertainty")
    print(f"  step4_fig2_service_gap.png            Service level difference")
    print(f"  step4_fig3_decision_divergence.png    Wafer allocation divergence")
    print(f"  step4_fig4_combined_dashboard.png     Four-panel summary dashboard")
    print(f"  step4_summary_report.txt              Plain-language findings")
    print(f"\n  Step 4 complete. Ready for Step 5 (identify failure points).")
    print()


if __name__ == "__main__":
    main()
