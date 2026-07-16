"""
step3_increase_variability.py
=============================
Step 3: Gradually increase yield uncertainty while keeping everything
else fixed.

Purpose
-------
Step 2 gave us a broad 7x7 grid — a wide scan across many FE and BE
spread combinations.  Step 3 is different: it does a *gradual ramp-up*
of uncertainty, one source at a time, to answer three specific questions:

  Experiment A:  What happens when ONLY Front-End yield uncertainty grows?
  Experiment B:  What happens when ONLY Back-End yield uncertainty grows?
  Experiment C:  What happens when BOTH grow together?

This matches the experimental design from Rashidi et al., who tested
increasing deviation levels for each uncertainty source independently.
Their key finding was that Back-End yield uncertainty and demand
uncertainty hurt expected profit the most, and that %VSS grows with
the level of uncertainty.

Design principles (all from the absorbed materials):
  - Uses the Step 2 FrozenInstance — all costs, capacities, prices,
    demand, and structure are locked.
  - Yield means are held constant at Step 1 baseline values
    (FE mean = 0.875, BE mean = 0.800).
  - Only the yield SPREAD changes, in fine increments from near-zero
    to wide.
  - Each experiment tracks: VSS, %VSS, wafer starts (FE1, FE2),
    outsourcing decisions, expected unmet demand, expected inventory.

Outputs
-------
    step3_rampup_results.csv        All experiment data (3 ramp-ups)
    step3_scenario_decisions.csv    Per-scenario die allocation, outsourcing, inventory (45 × 8 = 360 rows)
    step3_fig1_vss_rampup.png       VSS vs spread for all 3 experiments
    step3_fig2_wafer_allocation.png  How wafer starts shift as uncertainty grows
    step3_fig3_operational_impact.png  Unmet demand and inventory trends

Usage
-----
    python step3_increase_variability.py

Requirements: Python 3.9+, PuLP
              (pip install pulp)
Optional:     matplotlib (pip install matplotlib)
"""

import sys
import csv
from itertools import product as cartesian

# ---- Import from Step 2 frozen framework ----------------------------
# We import FrozenInstance and run_experiment directly from step2.
# If step2 is not importable, we include the necessary pieces inline.

try:
    from step2_freeze_model import (
        FrozenInstance, run_experiment, build_scenarios,
        solve_rp, solve_rp_fixed,
    )
    print("[ok] Imported from step2_freeze_model.py")
except ImportError:
    print("[fallback] Could not import step2_freeze_model.")
    print("           Make sure step2_freeze_model.py is in the same directory.")
    sys.exit(1)

# ---- Matplotlib (optional) ------------------------------------------
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("[warning] matplotlib not installed — skipping figures.")

DEBUG = "--debug" in sys.argv


# ======================================================================
# 1.  EXPERIMENT DESIGN
# ======================================================================
#
# Three ramp-up experiments, each with 15 fine-grained steps.
#
# The spread values go from very tight (0.02) to very wide (0.50).
# At each step, yields are constructed as:
#     lo = mean - spread/2
#     hi = mean + spread/2
# with clamping to keep values in (0, 1].
#
# Baseline means (from Step 1):
#     FE mean = 0.875
#     BE mean = 0.800
#
# Step 1 baseline spreads:
#     FE spread = 0.15  (yields 0.80 to 0.95)
#     BE spread = 0.20  (yields 0.70 to 0.90)

FE_MEAN = (FrozenInstance.STEP1_FE_LO + FrozenInstance.STEP1_FE_HI) / 2  # 0.875
BE_MEAN = (FrozenInstance.STEP1_BE_LO + FrozenInstance.STEP1_BE_HI) / 2  # 0.800

STEP1_FE_SPREAD = FrozenInstance.STEP1_FE_HI - FrozenInstance.STEP1_FE_LO  # 0.15
STEP1_BE_SPREAD = FrozenInstance.STEP1_BE_HI - FrozenInstance.STEP1_BE_LO  # 0.20

# Spread values for the gradual ramp-up: 15 steps
SPREAD_STEPS = [0.02, 0.04, 0.06, 0.08, 0.10,
                0.12, 0.15, 0.18, 0.20, 0.25,
                0.30, 0.35, 0.40, 0.45, 0.50]


def make_yields(mean, spread):
    """Compute (lo, hi) from mean and spread, clamped to (0.01, 1.00)."""
    lo = max(0.01, mean - spread / 2)
    hi = min(1.00, mean + spread / 2)
    return lo, hi


# ======================================================================
# 2.  RUN THE THREE RAMP-UP EXPERIMENTS
# ======================================================================

def run_experiment_a():
    """
    Experiment A: Increase FE yield spread only.
    BE spread is held at the Step 1 baseline (0.20).

    This isolates the effect of Front-End yield uncertainty.
    """
    print(f"\n{'='*60}")
    print(f"  EXPERIMENT A: Increase FE uncertainty only")
    print(f"  (BE spread fixed at {STEP1_BE_SPREAD})")
    print(f"{'='*60}")

    be_lo, be_hi = make_yields(BE_MEAN, STEP1_BE_SPREAD)
    results = []

    for i, fe_sp in enumerate(SPREAD_STEPS):
        fe_lo, fe_hi = make_yields(FE_MEAN, fe_sp)

        fi = FrozenInstance(fe_lo, fe_hi, be_lo, be_hi)
        r = run_experiment(fi, label=f"A_FEsp{fe_sp:.2f}", include_raw=True)
        r["experiment"] = "A_FE_only"
        r["ramp_spread"] = fe_sp  # the spread being ramped
        results.append(r)

        marker = " ◄ Step1 baseline" if abs(fe_sp - STEP1_FE_SPREAD) < 0.001 else ""
        print(f"  [{i+1:>2d}/15] FE_spread={fe_sp:.2f}  "
              f"FE=[{fe_lo:.3f},{fe_hi:.3f}]  "
              f"VSS=${r['vss']:>8.2f}  %VSS={r['pct_vss']:.2f}%  "
              f"RP_starts={r['rp_total_starts']:.1f}  "
              f"EV_starts={r['ev_total_starts']:.1f}{marker}")

    return results


def run_experiment_b():
    """
    Experiment B: Increase BE yield spread only.
    FE spread is held at the Step 1 baseline (0.15).

    This isolates the effect of Back-End yield uncertainty.
    Rashidi et al. found that BE yield uncertainty has a particularly
    large impact because the Back-End is the last stage — there's no
    recourse action left to compensate for bad BE yields.
    """
    print(f"\n{'='*60}")
    print(f"  EXPERIMENT B: Increase BE uncertainty only")
    print(f"  (FE spread fixed at {STEP1_FE_SPREAD})")
    print(f"{'='*60}")

    fe_lo, fe_hi = make_yields(FE_MEAN, STEP1_FE_SPREAD)
    results = []

    for i, be_sp in enumerate(SPREAD_STEPS):
        be_lo, be_hi = make_yields(BE_MEAN, be_sp)

        fi = FrozenInstance(fe_lo, fe_hi, be_lo, be_hi)
        r = run_experiment(fi, label=f"B_BEsp{be_sp:.2f}", include_raw=True)
        r["experiment"] = "B_BE_only"
        r["ramp_spread"] = be_sp
        results.append(r)

        marker = " ◄ Step1 baseline" if abs(be_sp - STEP1_BE_SPREAD) < 0.001 else ""
        print(f"  [{i+1:>2d}/15] BE_spread={be_sp:.2f}  "
              f"BE=[{be_lo:.3f},{be_hi:.3f}]  "
              f"VSS=${r['vss']:>8.2f}  %VSS={r['pct_vss']:.2f}%  "
              f"RP_starts={r['rp_total_starts']:.1f}  "
              f"EV_starts={r['ev_total_starts']:.1f}{marker}")

    return results


def run_experiment_c():
    """
    Experiment C: Increase BOTH FE and BE yield spreads together.

    Both spreads ramp up through the same values simultaneously.
    This shows the combined effect of increasing overall yield
    uncertainty throughout the supply chain.
    """
    print(f"\n{'='*60}")
    print(f"  EXPERIMENT C: Increase BOTH FE and BE uncertainty together")
    print(f"{'='*60}")

    results = []

    for i, sp in enumerate(SPREAD_STEPS):
        fe_lo, fe_hi = make_yields(FE_MEAN, sp)
        be_lo, be_hi = make_yields(BE_MEAN, sp)

        fi = FrozenInstance(fe_lo, fe_hi, be_lo, be_hi)
        r = run_experiment(fi, label=f"C_sp{sp:.2f}", include_raw=True)
        r["experiment"] = "C_both"
        r["ramp_spread"] = sp
        results.append(r)

        is_near_step1 = (abs(sp - STEP1_FE_SPREAD) < 0.001 or
                         abs(sp - STEP1_BE_SPREAD) < 0.001)
        marker = " ◄ near Step1" if is_near_step1 else ""
        print(f"  [{i+1:>2d}/15] spread={sp:.2f}  "
              f"FE=[{fe_lo:.3f},{fe_hi:.3f}]  "
              f"BE=[{be_lo:.3f},{be_hi:.3f}]  "
              f"VSS=${r['vss']:>8.2f}  %VSS={r['pct_vss']:.2f}%  "
              f"RP_starts={r['rp_total_starts']:.1f}  "
              f"EV_starts={r['ev_total_starts']:.1f}{marker}")

    return results


# ======================================================================
# 3.  SAVE RESULTS
# ======================================================================

def save_all_results(all_results, filepath="step3_rampup_results.csv"):
    """Save all three experiments to a single CSV."""
    fieldnames = [
        "experiment", "ramp_spread",
        "label", "fe_yield_lo", "fe_yield_hi", "be_yield_lo", "be_yield_hi",
        "fe_spread", "be_spread", "fe_mean", "be_mean",
        "rp_obj", "eev_obj", "vss", "pct_vss",
        "rp_xf_fe1", "rp_xf_fe2", "ev_xf_fe1", "ev_xf_fe2",
        "rp_total_starts", "ev_total_starts",
        "rp_outsource_fe", "rp_outsource_be",
        "ev_outsource_fe", "ev_outsource_be",
        "rp_exp_unmet", "eev_exp_unmet",
        "rp_exp_inv", "eev_exp_inv",
        "status_rp", "status_eev",
    ]

    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
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


def save_scenario_decisions(all_results, filepath="step3_scenario_decisions.csv"):
    """
    Export per-scenario decision variables for independent verification
    of the hedging claim across 45 experiments.
    Columns: die allocation (X_GK, X_KB, X_AD), outsourcing flows,
    inventory (Z), unmet demand (M), device inventory (W) per scenario.
    """
    rows = []
    for r in all_results:
        if "rp_raw" not in r or "eev_raw" not in r:
            continue
        rp = r["rp_raw"]
        eev = r["eev_raw"]
        S = [s["name"] for s in rp["scenarios"]]
        for s_name in S:
            row = {
                "experiment": r["experiment"],
                "ramp_spread": r["ramp_spread"],
                "label": r["label"],
                "scenario": s_name,
                "rp_X_GK_G1": rp["X_GK"].get((s_name, "G1"), 0) or 0,
                "rp_X_KB_BE1": rp["X_KB"].get((s_name, "BE1"), 0) or 0,
                "rp_X_KB_BE2": rp["X_KB"].get((s_name, "BE2"), 0) or 0,
                "rp_X_AD_A1": rp["X_AD"].get((s_name, "A1"), 0) or 0,
                "rp_Z": rp["Z"].get(s_name, 0) or 0,
                "rp_M": rp["M"].get(s_name, 0) or 0,
                "rp_W": rp["W"].get(s_name, 0) or 0,
                "eev_X_GK_G1": eev["X_GK"].get((s_name, "G1"), 0) or 0,
                "eev_X_KB_BE1": eev["X_KB"].get((s_name, "BE1"), 0) or 0,
                "eev_X_KB_BE2": eev["X_KB"].get((s_name, "BE2"), 0) or 0,
                "eev_X_AD_A1": eev["X_AD"].get((s_name, "A1"), 0) or 0,
                "eev_Z": eev["Z"].get(s_name, 0) or 0,
                "eev_M": eev["M"].get(s_name, 0) or 0,
                "eev_W": eev["W"].get(s_name, 0) or 0,
            }
            rows.append(row)

    if not rows:
        print(f"  [skip] No per-scenario data — run_experiment(include_raw=True) required")
        return

    fieldnames = list(rows[0].keys())
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = {}
            for k, v in row.items():
                out[k] = f"{v:.4f}" if isinstance(v, float) else v
            writer.writerow(out)

    print(f"  [saved] {filepath}  ({len(rows)} rows)")
    print(f"          Columns: die allocation (X_GK, X_KB, X_AD), outsourcing,")
    print(f"          inventory (Z), unmet (M), device inv (W) per scenario")


# ======================================================================
# 4.  VISUALIZATIONS
# ======================================================================

def plot_vss_rampup(results_a, results_b, results_c,
                    filepath="step3_fig1_vss_rampup.png"):
    """
    Figure 1: VSS ($) and %VSS vs yield spread for all three experiments.

    This is the central figure for Step 3. It shows:
    - How VSS changes as each uncertainty source grows
    - Whether FE or BE uncertainty has a larger effect on VSS
    - What the combined effect looks like

    This directly corresponds to Figure 7 in Rashidi et al., which
    shows %VSS increasing with deviation level.
    """
    if not HAS_MPL:
        print("  [skip] No matplotlib.")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

    # Extract data
    sp_a = [r["ramp_spread"] for r in results_a]
    sp_b = [r["ramp_spread"] for r in results_b]
    sp_c = [r["ramp_spread"] for r in results_c]

    vss_a = [r["vss"] for r in results_a]
    vss_b = [r["vss"] for r in results_b]
    vss_c = [r["vss"] for r in results_c]

    pct_a = [r["pct_vss"] for r in results_a]
    pct_b = [r["pct_vss"] for r in results_b]
    pct_c = [r["pct_vss"] for r in results_c]

    # --- Left panel: VSS ($) ------------------------------------------
    ax1.plot(sp_a, vss_a, "o-", color="#2563EB", linewidth=2, markersize=6,
             label="A: FE only (BE fixed at 0.20)")
    ax1.plot(sp_b, vss_b, "s-", color="#DC2626", linewidth=2, markersize=6,
             label="B: BE only (FE fixed at 0.15)")
    ax1.plot(sp_c, vss_c, "D-", color="#059669", linewidth=2, markersize=6,
             label="C: Both FE + BE together")

    # Mark Step 1 baseline
    ax1.axvline(x=STEP1_FE_SPREAD, color="#2563EB", linestyle=":",
                alpha=0.5, linewidth=1)
    ax1.axvline(x=STEP1_BE_SPREAD, color="#DC2626", linestyle=":",
                alpha=0.5, linewidth=1)

    ax1.set_xlabel("Yield Spread (hi - lo)", fontsize=12)
    ax1.set_ylabel("VSS ($)", fontsize=12)
    ax1.set_title("VSS ($) as Yield Uncertainty Increases",
                  fontsize=13, fontweight="bold")
    ax1.legend(fontsize=9, loc="best")
    ax1.grid(True, alpha=0.3)

    # --- Right panel: %VSS --------------------------------------------
    ax2.plot(sp_a, pct_a, "o-", color="#2563EB", linewidth=2, markersize=6,
             label="A: FE only")
    ax2.plot(sp_b, pct_b, "s-", color="#DC2626", linewidth=2, markersize=6,
             label="B: BE only")
    ax2.plot(sp_c, pct_c, "D-", color="#059669", linewidth=2, markersize=6,
             label="C: Both together")

    ax2.axvline(x=STEP1_FE_SPREAD, color="#2563EB", linestyle=":",
                alpha=0.5, linewidth=1)
    ax2.axvline(x=STEP1_BE_SPREAD, color="#DC2626", linestyle=":",
                alpha=0.5, linewidth=1)

    ax2.set_xlabel("Yield Spread (hi - lo)", fontsize=12)
    ax2.set_ylabel("%VSS (as % of RP profit)", fontsize=12)
    ax2.set_title("%VSS as Yield Uncertainty Increases",
                  fontsize=13, fontweight="bold")
    ax2.legend(fontsize=9, loc="best")
    ax2.grid(True, alpha=0.3)

    fig.suptitle("Step 3: Gradual Ramp-Up of Yield Uncertainty\n"
                 "Dotted lines mark Step 1 baseline spread values",
                 fontsize=14, fontweight="bold", y=1.03)
    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [saved] {filepath}")


def plot_wafer_allocation(results_a, results_b, results_c,
                          filepath="step3_fig2_wafer_allocation.png"):
    """
    Figure 2: How wafer allocation (FE1 vs FE2) shifts as uncertainty grows.

    From Step 1 and 2 we know that stochastic planning hedges by starting
    more wafers at FE2. This figure shows how that hedging behavior
    intensifies as uncertainty grows — separately for FE, BE, and both.
    """
    if not HAS_MPL:
        print("  [skip] No matplotlib.")
        return

    fig, axes = plt.subplots(1, 3, figsize=(17, 5), sharey=True)

    datasets = [
        (results_a, "A: FE Uncertainty Only", "#2563EB"),
        (results_b, "B: BE Uncertainty Only", "#DC2626"),
        (results_c, "C: Both Together",       "#059669"),
    ]

    for ax, (results, title, color) in zip(axes, datasets):
        spreads = [r["ramp_spread"] for r in results]

        rp_fe1 = [r["rp_xf_fe1"] for r in results]
        rp_fe2 = [r["rp_xf_fe2"] for r in results]
        ev_fe1 = [r["ev_xf_fe1"] for r in results]
        ev_fe2 = [r["ev_xf_fe2"] for r in results]

        ax.plot(spreads, rp_fe1, "o-", color=color, linewidth=2,
                label="RP: FE1", markersize=5)
        ax.plot(spreads, rp_fe2, "o--", color=color, linewidth=2,
                label="RP: FE2", markersize=5, alpha=0.7)
        ax.plot(spreads, ev_fe1, "s-", color="#F59E0B", linewidth=2,
                label="EV: FE1", markersize=5)
        ax.plot(spreads, ev_fe2, "s--", color="#F59E0B", linewidth=2,
                label="EV: FE2", markersize=5, alpha=0.7)

        ax.set_xlabel("Yield Spread", fontsize=11)
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.legend(fontsize=8, loc="best")
        ax.grid(True, alpha=0.3)

    axes[0].set_ylabel("Wafer Starts", fontsize=12)

    fig.suptitle("Step 3: Wafer Allocation as Yield Uncertainty Grows\n"
                 "RP hedges by shifting production to FE2; "
                 "EV stays relatively flat",
                 fontsize=13, fontweight="bold", y=1.04)
    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [saved] {filepath}")


def plot_operational_impact(results_a, results_b, results_c,
                            filepath="step3_fig3_operational_impact.png"):
    """
    Figure 3: Operational consequences — unmet demand and inventory
    for RP vs EEV as uncertainty grows.

    This shows the SERVICE LEVEL impact: as uncertainty grows, does
    deterministic planning lead to more unmet demand? Does stochastic
    planning manage inventory differently?
    """
    if not HAS_MPL:
        print("  [skip] No matplotlib.")
        return

    fig, axes = plt.subplots(2, 3, figsize=(17, 9), sharex="col")

    datasets = [
        (results_a, "A: FE Only"),
        (results_b, "B: BE Only"),
        (results_c, "C: Both"),
    ]

    for col, (results, title) in enumerate(datasets):
        spreads = [r["ramp_spread"] for r in results]
        rp_unmet  = [r["rp_exp_unmet"]  for r in results]
        eev_unmet = [r["eev_exp_unmet"] for r in results]
        rp_inv    = [r["rp_exp_inv"]    for r in results]
        eev_inv   = [r["eev_exp_inv"]   for r in results]

        # Top row: Expected unmet demand
        ax_top = axes[0, col]
        ax_top.plot(spreads, rp_unmet, "o-", color="#2563EB", linewidth=2,
                    markersize=5, label="Stochastic (RP)")
        ax_top.plot(spreads, eev_unmet, "s-", color="#F59E0B", linewidth=2,
                    markersize=5, label="Deterministic (EEV)")
        ax_top.set_title(title, fontsize=12, fontweight="bold")
        ax_top.legend(fontsize=8)
        ax_top.grid(True, alpha=0.3)
        if col == 0:
            ax_top.set_ylabel("Expected Unmet Demand", fontsize=11)

        # Bottom row: Expected die-bank inventory
        ax_bot = axes[1, col]
        ax_bot.plot(spreads, rp_inv, "o-", color="#2563EB", linewidth=2,
                    markersize=5, label="Stochastic (RP)")
        ax_bot.plot(spreads, eev_inv, "s-", color="#F59E0B", linewidth=2,
                    markersize=5, label="Deterministic (EEV)")
        ax_bot.set_xlabel("Yield Spread", fontsize=11)
        ax_bot.legend(fontsize=8)
        ax_bot.grid(True, alpha=0.3)
        if col == 0:
            ax_bot.set_ylabel("Expected DieBank Inventory", fontsize=11)

    fig.suptitle("Step 3: Operational Impact — Unmet Demand & Inventory\n"
                 "How service levels and inventory change as "
                 "yield uncertainty grows",
                 fontsize=13, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [saved] {filepath}")


# ======================================================================
# 5.  SUMMARY ANALYSIS
# ======================================================================

def print_summary(results_a, results_b, results_c):
    """Print a summary analysis of the three ramp-up experiments."""

    print(f"\n{'='*60}")
    print(f"  STEP 3 SUMMARY ANALYSIS")
    print(f"{'='*60}")

    for label, results, fixed_desc in [
        ("Experiment A (FE only)", results_a,
         f"BE spread fixed at {STEP1_BE_SPREAD}"),
        ("Experiment B (BE only)", results_b,
         f"FE spread fixed at {STEP1_FE_SPREAD}"),
        ("Experiment C (both)",    results_c,
         "FE and BE spread move together"),
    ]:
        vss_vals = [r["vss"] for r in results]
        pct_vals = [r["pct_vss"] for r in results]
        spreads  = [r["ramp_spread"] for r in results]

        min_idx = vss_vals.index(min(vss_vals))
        max_idx = vss_vals.index(max(vss_vals))

        print(f"\n  {label}  ({fixed_desc})")
        print(f"  {'─'*50}")
        print(f"    Spread range tested:  {spreads[0]:.2f} to {spreads[-1]:.2f}")
        print(f"    VSS range:            ${min(vss_vals):.2f} to ${max(vss_vals):.2f}")
        print(f"    %VSS range:           {min(pct_vals):.2f}% to {max(pct_vals):.2f}%")
        print(f"    Min VSS at spread:    {spreads[min_idx]:.2f}  "
              f"(${vss_vals[min_idx]:.2f})")
        print(f"    Max VSS at spread:    {spreads[max_idx]:.2f}  "
              f"(${vss_vals[max_idx]:.2f})")

        # Check monotonicity
        increasing = all(vss_vals[i] <= vss_vals[i+1]
                         for i in range(len(vss_vals)-1))
        decreasing = all(vss_vals[i] >= vss_vals[i+1]
                         for i in range(len(vss_vals)-1))
        if increasing:
            trend = "monotonically increasing"
        elif decreasing:
            trend = "monotonically decreasing"
        else:
            trend = "non-monotonic (has both increases and decreases)"
        print(f"    VSS trend:            {trend}")

        # Wafer start trends
        rp_starts_first = results[0]["rp_total_starts"]
        rp_starts_last  = results[-1]["rp_total_starts"]
        ev_starts_first = results[0]["ev_total_starts"]
        ev_starts_last  = results[-1]["ev_total_starts"]
        print(f"    RP total starts:      {rp_starts_first:.1f} → {rp_starts_last:.1f}  "
              f"(change: {rp_starts_last - rp_starts_first:+.1f})")
        print(f"    EV total starts:      {ev_starts_first:.1f} → {ev_starts_last:.1f}  "
              f"(change: {ev_starts_last - ev_starts_first:+.1f})")

    # --- Cross-experiment comparison ----------------------------------
    print(f"\n  {'='*50}")
    print(f"  CROSS-EXPERIMENT COMPARISON")
    print(f"  {'='*50}")

    # At the Step 1 baseline spread (0.15 for FE, 0.20 for BE)
    # find the VSS for each experiment at that point
    step1_a = [r for r in results_a if abs(r["ramp_spread"] - STEP1_FE_SPREAD) < 0.001]
    step1_b = [r for r in results_b if abs(r["ramp_spread"] - STEP1_BE_SPREAD) < 0.001]

    if step1_a and step1_b:
        print(f"\n  At Step 1 baseline spreads:")
        print(f"    Exp A (FE=0.15, BE=0.20):  VSS = ${step1_a[0]['vss']:.2f}")
        print(f"    Exp B (FE=0.15, BE=0.20):  VSS = ${step1_b[0]['vss']:.2f}")
        print(f"    (These should match since both use baseline spreads)")

    # Compare sensitivity: VSS change per unit spread change
    def sensitivity(results):
        """Average VSS change per 0.01 unit of spread change."""
        if len(results) < 2:
            return 0
        sp_range = results[-1]["ramp_spread"] - results[0]["ramp_spread"]
        vss_range = results[-1]["vss"] - results[0]["vss"]
        return vss_range / sp_range if sp_range != 0 else 0

    sens_a = sensitivity(results_a)
    sens_b = sensitivity(results_b)
    sens_c = sensitivity(results_c)

    print(f"\n  Overall VSS sensitivity ($/unit spread):")
    print(f"    Exp A (FE only):    {sens_a:>8.2f} $/unit-spread")
    print(f"    Exp B (BE only):    {sens_b:>8.2f} $/unit-spread")
    print(f"    Exp C (both):       {sens_c:>8.2f} $/unit-spread")

    if abs(sens_b) > abs(sens_a):
        print(f"\n  → BE uncertainty has a LARGER effect on VSS than FE uncertainty.")
        print(f"    This is consistent with Rashidi et al.'s finding that Back-End")
        print(f"    yield uncertainty is especially impactful because it occurs at")
        print(f"    the last stage where there is no recourse action left.")
    else:
        print(f"\n  → FE uncertainty has a larger effect on VSS than BE uncertainty.")
        print(f"    This differs from Rashidi et al.'s finding — may be due to")
        print(f"    differences in model parameters (capacity, cost ratios).")

    print()


# ======================================================================
# 6.  MAIN
# ======================================================================

def main():
    print("=" * 60)
    print("  step3_increase_variability.py")
    print("  Gradually increase yield uncertainty (3 experiments)")
    print("=" * 60)

    # --- Run the three experiments ------------------------------------
    results_a = run_experiment_a()
    results_b = run_experiment_b()
    results_c = run_experiment_c()

    all_results = results_a + results_b + results_c

    # --- Save CSV -----------------------------------------------------
    print("\n--- Saving results ---")
    save_all_results(all_results)
    save_scenario_decisions(all_results)

    # --- Generate figures ---------------------------------------------
    print("\n--- Generating figures ---")
    plot_vss_rampup(results_a, results_b, results_c)
    plot_wafer_allocation(results_a, results_b, results_c)
    plot_operational_impact(results_a, results_b, results_c)

    # --- Summary analysis ---------------------------------------------
    print_summary(results_a, results_b, results_c)

    # --- Final output list --------------------------------------------
    print(f"{'='*60}")
    print(f"  STEP 3 OUTPUTS")
    print(f"{'='*60}")
    print(f"  step3_rampup_results.csv           (45 experiments: 15 × 3)")
    print(f"  step3_scenario_decisions.csv        (per-scenario die allocation, outsourcing, inventory)")
    print(f"  step3_fig1_vss_rampup.png           VSS vs spread (3 curves)")
    print(f"  step3_fig2_wafer_allocation.png     Wafer starts shifting")
    print(f"  step3_fig3_operational_impact.png    Unmet demand & inventory")
    print(f"\n  Step 3 complete. Ready for Step 4 (compare planning outcomes).")
    print()


if __name__ == "__main__":
    main()
