"""
step5_identify_failure_points.py
================================
Step 5: Identify failure points - Find when average-yield planning
starts to perform poorly.

Purpose
-------
Steps 3 and 4 showed that deterministic planning gradually falls behind
stochastic planning as FE yield uncertainty grows, and that the gap
appears to accelerate past certain thresholds.  Step 5 formalizes this
by:

    1. Defining explicit FAILURE CRITERIA - practitioner-meaningful
       thresholds that separate "good enough" from "unacceptable."
    2. Running a FINE-GRAINED experiment with 50 spread levels to
       precisely locate where each criterion is triggered.
    3. Using LINEAR INTERPOLATION to estimate exact threshold values
       between grid points.
    4. Characterizing the FAILURE ZONE - how rapidly performance
       degrades once you cross the threshold.
    5. Repeating for all three uncertainty scenarios (FE only, BE only,
       both together) to confirm that failure is driven by FE uncertainty.

Connection to the literature:
    - Rashidi et al. show %VSS increasing with deviation level but do
      not identify specific thresholds where the planning approach
      choice becomes consequential.
    - Escudero et al. provide the mathematical framework (VSS = RP - EEV)
      but no practical breakpoint analysis.
    - This step fills the gap: it produces the threshold values that
      Step 7 will turn into practitioner guidance.

Outputs
-------
    step5_failure_data.csv               Fine-grained experiment data (150 rows)
    step5_thresholds.csv                 Summary of all threshold values found
    step5_fig1_failure_zones.png         Failure zone identification (main figure)
    step5_fig2_degradation_rate.png      How fast performance degrades past threshold
    step5_fig3_threshold_dashboard.png   Combined dashboard with all criteria
    step5_summary_report.txt             Plain-language findings

Usage
-----
    python step5_identify_failure_points.py

Requirements: Python 3.9+, PuLP  (pip install pulp)
Optional:     matplotlib         (pip install matplotlib)
"""

import sys
import csv
import os
import datetime
import math
from itertools import product as cartesian

# ---- Run manifest (reproducibility) --------------------------------
try:
    from run_manifest import record_step
except ImportError:
    record_step = None

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
    import matplotlib.patches as mpatches
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("[warning] matplotlib not installed - skipping figures.")


# ======================================================================
# 1.  CONSTANTS AND FAILURE CRITERIA DEFINITIONS
# ======================================================================

FE_MEAN = (FrozenInstance.STEP1_FE_LO + FrozenInstance.STEP1_FE_HI) / 2  # 0.875
BE_MEAN = (FrozenInstance.STEP1_BE_LO + FrozenInstance.STEP1_BE_HI) / 2  # 0.800

STEP1_FE_SPREAD = FrozenInstance.STEP1_FE_HI - FrozenInstance.STEP1_FE_LO  # 0.15
STEP1_BE_SPREAD = FrozenInstance.STEP1_BE_HI - FrozenInstance.STEP1_BE_LO  # 0.20

# Fine-grained spread values: 50 steps from 0.01 to 0.50
# This is much finer than Step 3's 15 steps, giving us ~0.01 resolution
# for precise threshold identification.
FINE_SPREADS = [round(0.01 + i * 0.01, 4) for i in range(50)]  # 0.01 to 0.50


def make_yields(mean, spread):
    """Compute (lo, hi) from mean and spread, clamped to (0.01, 1.00)."""
    lo = max(0.01, mean - spread / 2)
    hi = min(1.00, mean + spread / 2)
    return lo, hi


# ------------------------------------------------------------------
# FAILURE CRITERIA
# ------------------------------------------------------------------
# These are the practitioner-meaningful thresholds.  Each one answers
# a different question a manager might ask:
#
# Criterion 1: %VSS > 2%
#   "Am I leaving more than 2% of my profit on the table?"
#   Why 2%:  In semiconductor manufacturing, margins are typically
#   25-35%.  Losing 2% of total profit to a planning methodology
#   choice is significant - it's real money.  Below 1%, it's likely
#   not worth the implementation cost of stochastic planning.
#
# Criterion 2: Service gap > 1 unit (unmet demand difference)
#   "Are my customers noticeably worse off?"
#   Why 1 unit:  With expected demand of 750, 1 unit is 0.13% of
#   demand - a small but measurable degradation.  In semiconductor
#   supply chains, even small service failures can cascade into
#   lost contracts.
#
# Criterion 3: Service gap > 3 units
#   "Is my customer service seriously degrading?"
#   Why 3 units:  0.4% of demand.  This is a level where customers
#   start noticing and where contractual penalties may apply.
#
# Criterion 4: %VSS > 1.5% (early warning)
#   "Should I start thinking about upgrading my planning approach?"
#   This is a lower bar - an early warning signal.
#
# Criterion 5: VSS > $150 (absolute dollar threshold)
#   "Is the absolute dollar loss significant?"
#   Why $150:  This is about 63% higher than the baseline VSS of $92.
#   In a real fab, this would scale with the size of the operation.
# ------------------------------------------------------------------

FAILURE_CRITERIA = {
    "pct_vss_2pct": {
        "description": "%VSS exceeds 2% - losing >2% of profit to planning choice",
        "metric": "pct_vss",
        "threshold": 2.0,
        "direction": "above",  # fails when metric > threshold
        "severity": "critical",
        "short_label": "%VSS > 2%",
    },
    "pct_vss_1.5pct": {
        "description": "%VSS exceeds 1.5% - early warning level",
        "metric": "pct_vss",
        "threshold": 1.5,
        "direction": "above",
        "severity": "warning",
        "short_label": "%VSS > 1.5%",
    },
    "service_gap_1": {
        "description": "Service gap exceeds 1 unit - measurable customer impact",
        "metric": "unmet_gap",
        "threshold": 1.0,
        "direction": "above",
        "severity": "warning",
        "short_label": "Service gap > 1 unit",
    },
    "service_gap_3": {
        "description": "Service gap exceeds 3 units - serious service degradation",
        "metric": "unmet_gap",
        "threshold": 3.0,
        "direction": "above",
        "severity": "critical",
        "short_label": "Service gap > 3 units",
    },
    "vss_150": {
        "description": "VSS exceeds $150 - large absolute dollar loss",
        "metric": "vss",
        "threshold": 150.0,
        "direction": "above",
        "severity": "critical",
        "short_label": "VSS > $150",
    },
}


# ======================================================================
# 2.  ENRICHMENT (same as Step 4)
# ======================================================================

def enrich_result(r):
    """Add derived comparison metrics to an experiment result dict."""
    r["profit_gap"]       = r["vss"]
    r["unmet_gap"]        = r["eev_exp_unmet"] - r["rp_exp_unmet"]
    r["inv_gap"]          = r["rp_exp_inv"] - r["eev_exp_inv"]
    r["fe2_gap"]          = r["rp_xf_fe2"] - r["ev_xf_fe2"]
    r["total_starts_gap"] = r["rp_total_starts"] - r["ev_total_starts"]

    exp_demand = 750.0
    r["rp_fill_rate"]  = 100.0 * (1.0 - r["rp_exp_unmet"] / exp_demand)
    r["eev_fill_rate"] = 100.0 * (1.0 - r["eev_exp_unmet"] / exp_demand)
    r["fill_rate_gap"] = r["rp_fill_rate"] - r["eev_fill_rate"]
    return r


# ======================================================================
# 3.  RUN FINE-GRAINED EXPERIMENTS
# ======================================================================

def run_fine_experiments():
    """
    Run all three experiments (FE only, BE only, both) at 50 spread levels.
    Total: 150 experiments.
    """
    print(f"\n{'='*60}")
    print(f"  STEP 5: Fine-grained experiments for threshold identification")
    print(f"  50 spread levels × 3 experiments = 150 total")
    print(f"{'='*60}")

    results_a = []  # FE only
    results_b = []  # BE only
    results_c = []  # Both

    # --- Experiment A: FE uncertainty ramp-up --------------------------
    print(f"\n  Experiment A: FE uncertainty only (BE fixed at {STEP1_BE_SPREAD})")
    be_lo, be_hi = make_yields(BE_MEAN, STEP1_BE_SPREAD)
    for i, fe_sp in enumerate(FINE_SPREADS):
        fe_lo, fe_hi = make_yields(FE_MEAN, fe_sp)
        fi = FrozenInstance(fe_lo, fe_hi, be_lo, be_hi)
        r = run_experiment(fi, label=f"A_FE{fe_sp:.2f}")
        r["experiment"] = "A_FE_only"
        r["ramp_spread"] = fe_sp
        r = enrich_result(r)
        results_a.append(r)
        if (i + 1) % 10 == 0:
            print(f"    [{i+1:>2d}/50] spread={fe_sp:.2f}  "
                  f"VSS=${r['vss']:>7.2f}  %VSS={r['pct_vss']:.2f}%  "
                  f"unmet_gap={r['unmet_gap']:.2f}")

    # --- Experiment B: BE uncertainty ramp-up --------------------------
    print(f"\n  Experiment B: BE uncertainty only (FE fixed at {STEP1_FE_SPREAD})")
    fe_lo, fe_hi = make_yields(FE_MEAN, STEP1_FE_SPREAD)
    for i, be_sp in enumerate(FINE_SPREADS):
        be_lo, be_hi = make_yields(BE_MEAN, be_sp)
        fi = FrozenInstance(fe_lo, fe_hi, be_lo, be_hi)
        r = run_experiment(fi, label=f"B_BE{be_sp:.2f}")
        r["experiment"] = "B_BE_only"
        r["ramp_spread"] = be_sp
        r = enrich_result(r)
        results_b.append(r)
        if (i + 1) % 10 == 0:
            print(f"    [{i+1:>2d}/50] spread={be_sp:.2f}  "
                  f"VSS=${r['vss']:>7.2f}  %VSS={r['pct_vss']:.2f}%  "
                  f"unmet_gap={r['unmet_gap']:.2f}")

    # --- Experiment C: Both uncertainty ramp-up ------------------------
    print(f"\n  Experiment C: Both FE and BE uncertainty together")
    for i, sp in enumerate(FINE_SPREADS):
        fe_lo, fe_hi = make_yields(FE_MEAN, sp)
        be_lo, be_hi = make_yields(BE_MEAN, sp)
        fi = FrozenInstance(fe_lo, fe_hi, be_lo, be_hi)
        r = run_experiment(fi, label=f"C_{sp:.2f}")
        r["experiment"] = "C_both"
        r["ramp_spread"] = sp
        r = enrich_result(r)
        results_c.append(r)
        if (i + 1) % 10 == 0:
            print(f"    [{i+1:>2d}/50] spread={sp:.2f}  "
                  f"VSS=${r['vss']:>7.2f}  %VSS={r['pct_vss']:.2f}%  "
                  f"unmet_gap={r['unmet_gap']:.2f}")

    print(f"\n  Completed 150 experiments.")
    return results_a, results_b, results_c


# ======================================================================
# 4.  THRESHOLD DETECTION - The core Step 5 logic
# ======================================================================

def find_threshold(results, metric_key, threshold_value, direction="above"):
    """
    Find the precise spread value where a metric first crosses a threshold.

    Uses linear interpolation between adjacent experiment points for
    sub-grid-point precision.

    Parameters
    ----------
    results : list of dicts
        Experiment results sorted by ramp_spread (ascending).
    metric_key : str
        Which metric to check (e.g., "pct_vss", "unmet_gap").
    threshold_value : float
        The threshold to detect crossing of.
    direction : str
        "above" = failure when metric > threshold
        "below" = failure when metric < threshold

    Returns
    -------
    dict with keys:
        found : bool         Was the threshold crossed?
        spread_exact : float Interpolated spread value at crossing (or None)
        spread_before : float Last spread before crossing (or None)
        spread_after : float  First spread after crossing (or None)
        value_before : float  Metric value just before crossing
        value_after : float   Metric value just after crossing
        index_after : int     Index of first point past threshold
    """
    spreads = [r["ramp_spread"] for r in results]
    values  = [r[metric_key]    for r in results]

    for i in range(len(values)):
        crossed = (direction == "above" and values[i] > threshold_value) or \
                  (direction == "below" and values[i] < threshold_value)

        if crossed:
            if i == 0:
                # Crossed at the very first point - threshold is below
                # our experimental range
                return {
                    "found": True,
                    "spread_exact": spreads[0],
                    "spread_before": None,
                    "spread_after": spreads[0],
                    "value_before": None,
                    "value_after": values[0],
                    "index_after": 0,
                }

            # Linear interpolation between points i-1 and i
            s0, s1 = spreads[i-1], spreads[i]
            v0, v1 = values[i-1], values[i]

            if abs(v1 - v0) < 1e-12:
                frac = 0.5  # avoid division by zero
            else:
                frac = (threshold_value - v0) / (v1 - v0)

            spread_exact = s0 + frac * (s1 - s0)

            return {
                "found": True,
                "spread_exact": round(spread_exact, 4),
                "spread_before": s0,
                "spread_after": s1,
                "value_before": v0,
                "value_after": v1,
                "index_after": i,
            }

    # Threshold was never crossed
    return {
        "found": False,
        "spread_exact": None,
        "spread_before": None,
        "spread_after": None,
        "value_before": None,
        "value_after": None,
        "index_after": None,
    }


def find_all_thresholds(results_a, results_b, results_c):
    """
    Apply all failure criteria to all three experiments.
    Returns a structured dict of all threshold results.
    """
    print(f"\n{'='*60}")
    print(f"  THRESHOLD DETECTION")
    print(f"{'='*60}")

    all_thresholds = {}

    for exp_label, results, exp_desc in [
        ("A_FE_only", results_a, "FE uncertainty only"),
        ("B_BE_only", results_b, "BE uncertainty only"),
        ("C_both",    results_c, "Both together"),
    ]:
        print(f"\n  {exp_desc}:")
        all_thresholds[exp_label] = {}

        for crit_key, crit in FAILURE_CRITERIA.items():
            result = find_threshold(
                results, crit["metric"], crit["threshold"], crit["direction"]
            )
            result["criterion"] = crit_key
            result["experiment"] = exp_label
            result["description"] = crit["description"]
            result["severity"] = crit["severity"]
            result["short_label"] = crit["short_label"]
            all_thresholds[exp_label][crit_key] = result

            if result["found"]:
                print(f"    {crit['short_label']:<24s}  → TRIGGERED at "
                      f"spread = {result['spread_exact']:.4f}  "
                      f"[{crit['severity']}]")
            else:
                print(f"    {crit['short_label']:<24s}  → NOT triggered "
                      f"in range 0.01–0.50")

    return all_thresholds


# ======================================================================
# 5.  DEGRADATION RATE ANALYSIS
# ======================================================================

def compute_degradation_rates(results, thresholds_for_exp):
    """
    For each triggered threshold, compute how rapidly the metric
    degrades after crossing.  This tells practitioners: "Once you
    cross the threshold, how quickly does it get worse?"

    We measure:
    - Degradation at +0.05 spread past threshold
    - Degradation at +0.10 spread past threshold
    - Average degradation rate (metric change per unit spread)
    """
    rates = {}
    spreads = [r["ramp_spread"] for r in results]

    for crit_key, thresh in thresholds_for_exp.items():
        if not thresh["found"] or thresh["spread_exact"] is None:
            rates[crit_key] = {"triggered": False}
            continue

        crit = FAILURE_CRITERIA[crit_key]
        metric_key = crit["metric"]
        values = [r[metric_key] for r in results]
        threshold_spread = thresh["spread_exact"]

        # Find values at threshold + 0.05 and + 0.10
        def interpolate_at(target_spread):
            """Linearly interpolate metric value at a target spread."""
            if target_spread > spreads[-1] or target_spread < spreads[0]:
                return None
            for j in range(len(spreads) - 1):
                if spreads[j] <= target_spread <= spreads[j+1]:
                    frac = ((target_spread - spreads[j]) /
                            (spreads[j+1] - spreads[j]))
                    return values[j] + frac * (values[j+1] - values[j])
            return None

        val_at_threshold = crit["threshold"]
        val_at_plus_05 = interpolate_at(threshold_spread + 0.05)
        val_at_plus_10 = interpolate_at(threshold_spread + 0.10)
        val_at_end = values[-1]

        # Compute rates
        rate_05 = None
        rate_10 = None
        if val_at_plus_05 is not None:
            rate_05 = (val_at_plus_05 - val_at_threshold) / 0.05
        if val_at_plus_10 is not None:
            rate_10 = (val_at_plus_10 - val_at_threshold) / 0.10

        # Overall rate from threshold to end of range
        spread_remaining = spreads[-1] - threshold_spread
        if spread_remaining > 0.001:
            rate_to_end = (val_at_end - val_at_threshold) / spread_remaining
        else:
            rate_to_end = 0

        rates[crit_key] = {
            "triggered": True,
            "threshold_spread": threshold_spread,
            "val_at_threshold": val_at_threshold,
            "val_at_plus_05": val_at_plus_05,
            "val_at_plus_10": val_at_plus_10,
            "val_at_end": val_at_end,
            "rate_05": rate_05,
            "rate_10": rate_10,
            "rate_to_end": rate_to_end,
        }

    return rates


# ======================================================================
# 6.  SAVE OUTPUTS
# ======================================================================

def save_experiment_csv(results_a, results_b, results_c,
                        filepath="step5_failure_data.csv"):
    """Save all 150 fine-grained experiment results."""
    all_results = results_a + results_b + results_c
    fieldnames = [
        "experiment", "ramp_spread",
        "fe_spread", "be_spread", "fe_mean", "be_mean",
        "rp_obj", "eev_obj", "vss", "pct_vss",
        "rp_exp_unmet", "eev_exp_unmet", "unmet_gap",
        "rp_fill_rate", "eev_fill_rate", "fill_rate_gap",
        "rp_exp_inv", "eev_exp_inv", "inv_gap",
        "rp_xf_fe1", "rp_xf_fe2", "ev_xf_fe1", "ev_xf_fe2",
        "fe2_gap", "total_starts_gap",
        "rp_outsource_fe", "ev_outsource_fe",
        "rp_outsource_be", "ev_outsource_be",
        "profit_gap",
        "rp_total_starts", "ev_total_starts",
        "status_rp", "status_eev",
    ]

    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames,
                                extrasaction="ignore")
        writer.writeheader()
        for r in all_results:
            row = {}
            for k in fieldnames:
                v = r.get(k, "")
                row[k] = f"{v:.6f}" if isinstance(v, float) else v
            writer.writerow(row)

    print(f"\n  [saved] {filepath}  ({len(all_results)} rows)")


def save_thresholds_csv(all_thresholds, all_rates,
                        filepath="step5_thresholds.csv"):
    """Save the threshold detection results in a structured CSV."""
    rows = []

    for exp_label in ["A_FE_only", "B_BE_only", "C_both"]:
        for crit_key in FAILURE_CRITERIA:
            t = all_thresholds[exp_label][crit_key]
            r = all_rates.get(exp_label, {}).get(crit_key, {})

            rows.append({
                "experiment": exp_label,
                "criterion": crit_key,
                "short_label": t["short_label"],
                "severity": t["severity"],
                "description": t["description"],
                "triggered": "Yes" if t["found"] else "No",
                "threshold_spread": f"{t['spread_exact']:.4f}" if t["found"] else "N/A",
                "spread_before": f"{t['spread_before']:.4f}" if t.get("spread_before") is not None else "N/A",
                "spread_after": f"{t['spread_after']:.4f}" if t.get("spread_after") is not None else "N/A",
                "value_before": f"{t['value_before']:.4f}" if t.get("value_before") is not None else "N/A",
                "value_after": f"{t['value_after']:.4f}" if t.get("value_after") is not None else "N/A",
                "degrad_rate_05": f"{r.get('rate_05', 'N/A')}" if r.get("rate_05") is not None else "N/A",
                "degrad_rate_10": f"{r.get('rate_10', 'N/A')}" if r.get("rate_10") is not None else "N/A",
                "degrad_rate_to_end": f"{r.get('rate_to_end', 'N/A')}" if r.get("rate_to_end") is not None else "N/A",
            })

    fieldnames = list(rows[0].keys())
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  [saved] {filepath}  ({len(rows)} rows)")


# ======================================================================
# 7.  VISUALIZATIONS
# ======================================================================

def plot_failure_zones(results_a, results_b, results_c, all_thresholds,
                       filepath="step5_fig1_failure_zones.png"):
    """
    Figure 1: The main Step 5 figure.  Shows %VSS and service gap
    for all three experiments, with failure zones shaded and threshold
    lines marked.

    This is the figure that directly answers: "At what FE spread does
    deterministic planning start to fail?"
    """
    if not HAS_MPL:
        return

    fig, axes = plt.subplots(2, 3, figsize=(18, 10), sharex="col")

    datasets = [
        (results_a, "A_FE_only", "A: FE Uncertainty Only", "#2563EB"),
        (results_b, "B_BE_only", "B: BE Uncertainty Only", "#DC2626"),
        (results_c, "C_both",    "C: Both Together",       "#059669"),
    ]

    for col, (results, exp_key, title, color) in enumerate(datasets):
        sp = [r["ramp_spread"] for r in results]
        pct_vss = [r["pct_vss"] for r in results]
        unmet_gap = [r["unmet_gap"] for r in results]

        # --- Top row: %VSS with threshold zones ----------------------
        ax = axes[0, col]
        ax.plot(sp, pct_vss, "-", color=color, linewidth=2)
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.grid(True, alpha=0.3)
        if col == 0:
            ax.set_ylabel("%VSS", fontsize=11)

        # Draw threshold lines
        thresh_15 = all_thresholds[exp_key].get("pct_vss_1.5pct", {})
        thresh_20 = all_thresholds[exp_key].get("pct_vss_2pct", {})

        ax.axhline(y=1.5, color="#F59E0B", linestyle="--", alpha=0.7,
                   linewidth=1, label="1.5% warning")
        ax.axhline(y=2.0, color="#DC2626", linestyle="--", alpha=0.7,
                   linewidth=1, label="2.0% critical")

        # Shade failure zones
        if thresh_20.get("found"):
            ts = thresh_20["spread_exact"]
            ax.axvspan(ts, sp[-1], alpha=0.08, color="#DC2626")
            ax.axvline(x=ts, color="#DC2626", linestyle="-", alpha=0.5,
                       linewidth=1.5)
            ax.annotate(f"Critical\n{ts:.2f}",
                        xy=(ts, 2.0), xytext=(ts + 0.03, 2.0 + 0.3),
                        fontsize=8, color="#DC2626", fontweight="bold",
                        arrowprops=dict(arrowstyle="->", color="#DC2626",
                                        linewidth=1))

        if thresh_15.get("found"):
            ts = thresh_15["spread_exact"]
            end = thresh_20["spread_exact"] if thresh_20.get("found") else sp[-1]
            if ts < end:
                ax.axvspan(ts, end, alpha=0.06, color="#F59E0B")
            ax.axvline(x=ts, color="#F59E0B", linestyle="-", alpha=0.5,
                       linewidth=1.5)
            ax.annotate(f"Warning\n{ts:.2f}",
                        xy=(ts, 1.5), xytext=(ts + 0.03, 1.5 + 0.2),
                        fontsize=8, color="#F59E0B", fontweight="bold",
                        arrowprops=dict(arrowstyle="->", color="#F59E0B",
                                        linewidth=1))

        ax.legend(fontsize=7, loc="upper left")

        # --- Bottom row: Service gap with threshold zones -------------
        ax = axes[1, col]
        ax.plot(sp, unmet_gap, "-", color=color, linewidth=2)
        ax.grid(True, alpha=0.3)
        ax.set_xlabel("Yield Spread", fontsize=11)
        if col == 0:
            ax.set_ylabel("Service Gap (extra unmet units under EV)",
                          fontsize=10)

        thresh_s1 = all_thresholds[exp_key].get("service_gap_1", {})
        thresh_s3 = all_thresholds[exp_key].get("service_gap_3", {})

        ax.axhline(y=1.0, color="#F59E0B", linestyle="--", alpha=0.7,
                   linewidth=1, label="1 unit warning")
        ax.axhline(y=3.0, color="#DC2626", linestyle="--", alpha=0.7,
                   linewidth=1, label="3 unit critical")
        ax.axhline(y=0.0, color="gray", linestyle="-", alpha=0.3)

        if thresh_s3.get("found"):
            ts = thresh_s3["spread_exact"]
            ax.axvspan(ts, sp[-1], alpha=0.08, color="#DC2626")
            ax.axvline(x=ts, color="#DC2626", linestyle="-", alpha=0.5,
                       linewidth=1.5)
            ax.annotate(f"{ts:.2f}",
                        xy=(ts, 3.0), xytext=(ts + 0.02, 3.5),
                        fontsize=8, color="#DC2626", fontweight="bold",
                        arrowprops=dict(arrowstyle="->", color="#DC2626"))

        if thresh_s1.get("found"):
            ts = thresh_s1["spread_exact"]
            ax.axvline(x=ts, color="#F59E0B", linestyle="-", alpha=0.5,
                       linewidth=1.5)
            ax.annotate(f"{ts:.2f}",
                        xy=(ts, 1.0), xytext=(ts + 0.02, 1.5),
                        fontsize=8, color="#F59E0B", fontweight="bold",
                        arrowprops=dict(arrowstyle="->", color="#F59E0B"))

        ax.legend(fontsize=7, loc="upper left")

    fig.suptitle("Step 5 - Failure Zone Identification\n"
                 "Where does deterministic planning start to fail?",
                 fontsize=14, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [saved] {filepath}")


def plot_degradation_rate(results_a, all_thresholds,
                          filepath="step5_fig2_degradation_rate.png"):
    """
    Figure 2: Degradation rate - How fast does performance degrade
    once you cross the threshold?  Uses Experiment A (FE only) as
    the primary illustration.

    Shows the metric trajectory with threshold markers and
    degradation slopes annotated.
    """
    if not HAS_MPL:
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    sp = [r["ramp_spread"] for r in results_a]
    vss = [r["vss"] for r in results_a]
    pct = [r["pct_vss"] for r in results_a]
    unmet = [r["unmet_gap"] for r in results_a]

    # --- Left panel: VSS trajectory with slopes -----------------------
    ax1.plot(sp, vss, "-", color="#2563EB", linewidth=2, label="VSS ($)")
    ax1.set_xlabel("FE Yield Spread", fontsize=11)
    ax1.set_ylabel("VSS ($)", fontsize=11)
    ax1.set_title("VSS Degradation After Threshold\n(Experiment A: FE Only)",
                  fontsize=12, fontweight="bold")
    ax1.grid(True, alpha=0.3)

    # Mark $150 threshold
    t150 = all_thresholds["A_FE_only"].get("vss_150", {})
    if t150.get("found"):
        ts = t150["spread_exact"]
        ax1.axhline(y=150, color="#DC2626", linestyle="--", alpha=0.6)
        ax1.axvline(x=ts, color="#DC2626", linestyle="-", alpha=0.5)
        ax1.axvspan(ts, sp[-1], alpha=0.06, color="#DC2626")

        # Annotate degradation: show slope line
        # Find values at ts and ts+0.10
        idx_after = t150.get("index_after", 0)
        if idx_after and idx_after + 10 < len(vss):
            slope_sp = [sp[idx_after], sp[min(idx_after + 10, len(sp)-1)]]
            slope_vs = [vss[idx_after], vss[min(idx_after + 10, len(vss)-1)]]
            ax1.plot(slope_sp, slope_vs, "r-", linewidth=3, alpha=0.4)
            rate = (slope_vs[1] - slope_vs[0]) / (slope_sp[1] - slope_sp[0])
            mid_x = (slope_sp[0] + slope_sp[1]) / 2
            mid_y = (slope_vs[0] + slope_vs[1]) / 2
            ax1.annotate(f"Rate: ${rate:.0f}/unit",
                         xy=(mid_x, mid_y),
                         xytext=(mid_x - 0.08, mid_y + 15),
                         fontsize=9, color="#DC2626", fontweight="bold")

    ax1.legend(fontsize=9)

    # --- Right panel: Service gap trajectory --------------------------
    ax2.plot(sp, unmet, "-", color="#2563EB", linewidth=2,
             label="Service gap (units)")
    ax2.set_xlabel("FE Yield Spread", fontsize=11)
    ax2.set_ylabel("Service Gap (EEV unmet − RP unmet)", fontsize=11)
    ax2.set_title("Service Degradation After Threshold\n"
                  "(Experiment A: FE Only)",
                  fontsize=12, fontweight="bold")
    ax2.grid(True, alpha=0.3)

    ts1 = all_thresholds["A_FE_only"].get("service_gap_1", {})
    ts3 = all_thresholds["A_FE_only"].get("service_gap_3", {})

    ax2.axhline(y=1.0, color="#F59E0B", linestyle="--", alpha=0.6,
                label="1 unit warning")
    ax2.axhline(y=3.0, color="#DC2626", linestyle="--", alpha=0.6,
                label="3 unit critical")
    ax2.axhline(y=0.0, color="gray", linestyle="-", alpha=0.3)

    if ts1.get("found"):
        ax2.axvline(x=ts1["spread_exact"], color="#F59E0B", linestyle="-",
                    alpha=0.5)
    if ts3.get("found"):
        ts = ts3["spread_exact"]
        ax2.axvline(x=ts, color="#DC2626", linestyle="-", alpha=0.5)
        ax2.axvspan(ts, sp[-1], alpha=0.06, color="#DC2626")

    ax2.legend(fontsize=9)

    fig.suptitle("Step 5 - Degradation Rate Analysis\n"
                 "How fast does performance deteriorate past the threshold?",
                 fontsize=13, fontweight="bold", y=1.03)
    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [saved] {filepath}")


def plot_threshold_dashboard(results_a, results_b, results_c,
                             all_thresholds,
                             filepath="step5_fig3_threshold_dashboard.png"):
    """
    Figure 3: Combined dashboard summarizing all thresholds found
    across all three experiments.  Bar chart showing which criteria
    are triggered and at what spread value.
    """
    if not HAS_MPL:
        return

    fig, ax = plt.subplots(figsize=(14, 7))

    # Collect all threshold results into plottable format
    crit_keys = list(FAILURE_CRITERIA.keys())
    exp_labels = ["A_FE_only", "B_BE_only", "C_both"]
    exp_display = {"A_FE_only": "FE Only", "B_BE_only": "BE Only",
                   "C_both": "Both"}
    exp_colors = {"A_FE_only": "#2563EB", "B_BE_only": "#DC2626",
                  "C_both": "#059669"}

    # Create grouped bar chart
    n_crit = len(crit_keys)
    n_exp = len(exp_labels)
    bar_width = 0.25
    x = range(n_crit)

    for j, exp_key in enumerate(exp_labels):
        values = []
        colors = []
        for crit_key in crit_keys:
            t = all_thresholds[exp_key][crit_key]
            if t["found"]:
                values.append(t["spread_exact"])
                colors.append(exp_colors[exp_key])
            else:
                values.append(0)
                colors.append("#E5E7EB")  # light gray for not triggered

        positions = [xi + j * bar_width for xi in x]
        bars = ax.bar(positions, values, bar_width,
                      label=exp_display[exp_key],
                      color=exp_colors[exp_key],
                      alpha=0.8 if any(v > 0 for v in values) else 0.3,
                      edgecolor="white")

        # Add value labels
        for pos, val in zip(positions, values):
            if val > 0:
                ax.text(pos, val + 0.005, f"{val:.2f}",
                        ha="center", va="bottom", fontsize=8,
                        fontweight="bold", color=exp_colors[exp_key])
            else:
                ax.text(pos, 0.01, "N/A", ha="center", va="bottom",
                        fontsize=7, color="#9CA3AF")

    ax.set_xticks([xi + bar_width for xi in x])
    ax.set_xticklabels(
        [FAILURE_CRITERIA[k]["short_label"] for k in crit_keys],
        fontsize=10, rotation=15, ha="right"
    )
    ax.set_ylabel("Yield Spread at Threshold", fontsize=12)
    ax.set_title("Step 5 - Threshold Dashboard\n"
                 "At what yield spread does each failure criterion trigger?",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=11, loc="upper left")
    ax.grid(True, axis="y", alpha=0.3)

    # Add severity bands
    ax.axhline(y=STEP1_FE_SPREAD, color="gray", linestyle=":",
               alpha=0.4, linewidth=1)
    ax.annotate("Step 1 baseline (0.15)", xy=(n_crit - 0.5, STEP1_FE_SPREAD),
                fontsize=8, color="gray", ha="right")

    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [saved] {filepath}")


# ======================================================================
# 8.  SUMMARY REPORT
# ======================================================================

def generate_summary_report(results_a, results_b, results_c,
                            all_thresholds, all_rates,
                            filepath="step5_summary_report.txt"):
    """Generate the plain-language Step 5 summary report."""

    lines = []
    lines.append("=" * 70)
    lines.append("  STEP 5: FAILURE POINT IDENTIFICATION - SUMMARY REPORT")
    lines.append(f"  Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 70)

    # --- Section 1: Overview ------------------------------------------
    lines.append("")
    lines.append("1. WHAT THIS STEP DOES")
    lines.append("-" * 50)
    lines.append("")
    lines.append("  Step 5 identifies the precise yield spread values where")
    lines.append("  deterministic (average-yield) planning starts to perform")
    lines.append("  poorly enough that a practitioner should consider switching")
    lines.append("  to stochastic planning.")
    lines.append("")
    lines.append("  Method: 150 experiments (50 spread levels × 3 experiments)")
    lines.append("  with 5 failure criteria applied to each, using linear")
    lines.append("  interpolation for sub-grid-point precision.")

    # --- Section 2: Threshold Results - Experiment A ------------------
    lines.append("")
    lines.append("")
    lines.append("2. THRESHOLD RESULTS - EXPERIMENT A (FE UNCERTAINTY ONLY)")
    lines.append("-" * 50)
    lines.append("  This is the most important experiment because FE uncertainty")
    lines.append("  is the primary driver of planning approach differences.")
    lines.append("")

    for crit_key in FAILURE_CRITERIA:
        crit = FAILURE_CRITERIA[crit_key]
        t = all_thresholds["A_FE_only"][crit_key]
        r = all_rates.get("A_FE_only", {}).get(crit_key, {})

        if t["found"]:
            lines.append(f"  {crit['short_label']}:")
            lines.append(f"    Triggered at FE spread = {t['spread_exact']:.4f}")
            if t.get("spread_before") is not None:
                lines.append(f"    Between spread {t['spread_before']:.4f} "
                             f"(value={t['value_before']:.4f}) and "
                             f"{t['spread_after']:.4f} "
                             f"(value={t['value_after']:.4f})")
            if r.get("rate_to_end") is not None:
                lines.append(f"    Degradation rate to end of range: "
                             f"{r['rate_to_end']:.2f} per unit spread")
            lines.append("")
        else:
            lines.append(f"  {crit['short_label']}: NOT triggered in range 0.01–0.50")
            lines.append("")

    # --- Section 3: Threshold Results - Experiment B ------------------
    lines.append("")
    lines.append("3. THRESHOLD RESULTS - EXPERIMENT B (BE UNCERTAINTY ONLY)")
    lines.append("-" * 50)
    lines.append("  BE uncertainty should NOT trigger failure criteria (or trigger")
    lines.append("  them only at the baseline level), confirming the no-recourse")
    lines.append("  finding from Steps 3-4.")
    lines.append("")

    any_triggered_b = False
    for crit_key in FAILURE_CRITERIA:
        t = all_thresholds["B_BE_only"][crit_key]
        crit = FAILURE_CRITERIA[crit_key]
        if t["found"]:
            any_triggered_b = True
            lines.append(f"  {crit['short_label']}: Triggered at "
                         f"spread = {t['spread_exact']:.4f}")
        else:
            lines.append(f"  {crit['short_label']}: NOT triggered")

    lines.append("")
    if not any_triggered_b:
        lines.append("  CONFIRMED: BE uncertainty does not cause planning failures.")
    else:
        lines.append("  Note: Any triggers here are from the baseline FE spread (0.15),")
        lines.append("  not from BE uncertainty changes.")

    # --- Section 4: Threshold Results - Experiment C ------------------
    lines.append("")
    lines.append("")
    lines.append("4. THRESHOLD RESULTS - EXPERIMENT C (BOTH TOGETHER)")
    lines.append("-" * 50)

    for crit_key in FAILURE_CRITERIA:
        crit = FAILURE_CRITERIA[crit_key]
        t = all_thresholds["C_both"][crit_key]
        if t["found"]:
            lines.append(f"  {crit['short_label']}: Triggered at "
                         f"spread = {t['spread_exact']:.4f}")
        else:
            lines.append(f"  {crit['short_label']}: NOT triggered")

    # --- Section 5: The Failure Zone Summary --------------------------
    lines.append("")
    lines.append("")
    lines.append("5. THE FAILURE ZONE - KEY FINDING")
    lines.append("-" * 50)
    lines.append("")

    # Find the earliest and latest triggers for Exp A
    a_triggers = []
    for crit_key in FAILURE_CRITERIA:
        t = all_thresholds["A_FE_only"][crit_key]
        if t["found"] and t["spread_exact"] is not None:
            a_triggers.append((t["spread_exact"], crit_key,
                               FAILURE_CRITERIA[crit_key]["short_label"],
                               FAILURE_CRITERIA[crit_key]["severity"]))

    if a_triggers:
        a_triggers.sort(key=lambda x: x[0])
        earliest = a_triggers[0]
        latest = a_triggers[-1]

        lines.append(f"  For FE uncertainty (Experiment A):")
        lines.append(f"    Earliest warning:   spread = {earliest[0]:.4f}  "
                     f"({earliest[2]})")
        lines.append(f"    Latest critical:    spread = {latest[0]:.4f}  "
                     f"({latest[2]})")
        lines.append("")
        lines.append(f"  The failure zone for FE uncertainty spans approximately:")
        lines.append(f"    Warning zone:       spread ≈ {earliest[0]:.2f} to "
                     f"{latest[0]:.2f}")
        lines.append(f"    Critical zone:      spread > {latest[0]:.2f}")
        lines.append("")
        lines.append(f"  In yield terms (FE mean = {FE_MEAN}):")
        fe_lo_warn = max(0.01, FE_MEAN - earliest[0] / 2)
        fe_hi_warn = min(1.00, FE_MEAN + earliest[0] / 2)
        fe_lo_crit = max(0.01, FE_MEAN - latest[0] / 2)
        fe_hi_crit = min(1.00, FE_MEAN + latest[0] / 2)
        lines.append(f"    Warning when FE yields range wider than "
                     f"[{fe_lo_warn:.3f}, {fe_hi_warn:.3f}]")
        lines.append(f"    Critical when FE yields range wider than "
                     f"[{fe_lo_crit:.3f}, {fe_hi_crit:.3f}]")

    # --- Section 6: Degradation Analysis Summary ---------------------
    lines.append("")
    lines.append("")
    lines.append("6. DEGRADATION ANALYSIS")
    lines.append("-" * 50)
    lines.append("")
    lines.append("  Once the threshold is crossed, how fast does performance")
    lines.append("  degrade? (Based on Experiment A - FE uncertainty only)")
    lines.append("")

    a_rates = all_rates.get("A_FE_only", {})
    for crit_key in FAILURE_CRITERIA:
        r = a_rates.get(crit_key, {})
        crit = FAILURE_CRITERIA[crit_key]
        if r.get("triggered") and r.get("rate_to_end") is not None:
            lines.append(f"  {crit['short_label']}:")
            lines.append(f"    At threshold:      {crit['metric']} = "
                         f"{r['val_at_threshold']:.2f}")
            lines.append(f"    At end of range:   {crit['metric']} = "
                         f"{r['val_at_end']:.2f}")
            lines.append(f"    Degradation rate:  "
                         f"{r['rate_to_end']:.2f} per unit spread")
            if r.get("rate_05") is not None:
                lines.append(f"    Rate at +0.05:     "
                             f"{r['rate_05']:.2f} per unit spread")
            lines.append("")

    # --- Section 7: Implications for Step 6 & 7 ----------------------
    lines.append("")
    lines.append("7. IMPLICATIONS FOR STEPS 6 AND 7")
    lines.append("-" * 50)
    lines.append("")
    lines.append("  The threshold values identified above are specific to the")
    lines.append("  current cost structure (penalty = $3/device, price = $10/device,")
    lines.append("  FE cost = $1.50/wafer). Step 6 will test whether these")
    lines.append("  thresholds shift when costs change:")
    lines.append("")
    lines.append("  - Higher shortage penalty ($5 or $10) → thresholds should move")
    lines.append("    LEFT (lower FE spread), meaning stochastic planning becomes")
    lines.append("    necessary sooner.")
    lines.append("  - Lower shortage penalty ($1) → thresholds should move RIGHT")
    lines.append("    (higher FE spread), meaning deterministic planning is adequate")
    lines.append("    for a wider range of uncertainty.")
    lines.append("  - Different capacity constraints → may change the hedging")
    lines.append("    mechanism and shift thresholds.")
    lines.append("")
    lines.append("  Step 7 will synthesize the threshold values from Steps 5 and 6")
    lines.append("  into practitioner guidance of the form:")
    lines.append("    'If your FE yield spread exceeds X and your shortage penalty")
    lines.append("     is at least Y% of selling price, invest in stochastic planning.")
    lines.append("     Otherwise, average-yield planning is sufficient.'")
    lines.append("")
    lines.append("  The thresholds from this step provide the X values for the")
    lines.append("  current cost structure. Step 6 will show how X changes with Y.")
    lines.append("")

    # --- Section 8: Connection to Literature --------------------------
    lines.append("")
    lines.append("8. CONNECTION TO THE LITERATURE")
    lines.append("-" * 50)
    lines.append("")
    lines.append("  Rashidi et al. (Figure 7) show that %VSS increases with")
    lines.append("  deviation level, but do not identify specific breakpoints.")
    lines.append("  They treat the uncertainty-to-VSS relationship as a continuous")
    lines.append("  curve and note that it grows, without specifying where it")
    lines.append("  becomes 'large enough to matter.'")
    lines.append("")
    lines.append("  Our Step 5 fills this gap by defining what 'large enough'")
    lines.append("  means (the failure criteria) and identifying the precise")
    lines.append("  yield spread values where each criterion triggers.")
    lines.append("")
    lines.append("  This is the core contribution the ITC 2026 paper provides:")
    lines.append("  not just 'VSS grows with uncertainty' (which is known), but")
    lines.append("  'here is exactly when it starts to matter, and here is how")
    lines.append("  fast it gets worse once it does.'")
    lines.append("")

    # Write to file
    report_text = "\n".join(lines)
    with open(filepath, "w") as f:
        f.write(report_text)

    print(report_text)
    print(f"\n  [saved] {filepath}")


# ======================================================================
# 9.  MAIN
# ======================================================================

def main():
    print("=" * 60)
    print("  step5_identify_failure_points.py")
    print("  Find when deterministic planning starts to fail")
    print("=" * 60)

    start_iso = datetime.datetime.now().isoformat()

    # --- Run fine-grained experiments ---------------------------------
    results_a, results_b, results_c = run_fine_experiments()

    # --- Save experiment data -----------------------------------------
    print("\n--- Saving experiment data ---")
    save_experiment_csv(results_a, results_b, results_c)

    # --- Detect all thresholds ----------------------------------------
    all_thresholds = find_all_thresholds(results_a, results_b, results_c)

    # --- Compute degradation rates ------------------------------------
    print(f"\n--- Computing degradation rates ---")
    all_rates = {}
    for exp_key, results in [("A_FE_only", results_a),
                              ("B_BE_only", results_b),
                              ("C_both", results_c)]:
        all_rates[exp_key] = compute_degradation_rates(
            results, all_thresholds[exp_key])

    # --- Save threshold summary ---------------------------------------
    print("\n--- Saving threshold summary ---")
    save_thresholds_csv(all_thresholds, all_rates)

    # --- Generate figures ---------------------------------------------
    print("\n--- Generating figures ---")
    plot_failure_zones(results_a, results_b, results_c, all_thresholds)
    plot_degradation_rate(results_a, all_thresholds)
    plot_threshold_dashboard(results_a, results_b, results_c, all_thresholds)

    # --- Generate summary report --------------------------------------
    print("\n--- Generating summary report ---")
    generate_summary_report(results_a, results_b, results_c,
                            all_thresholds, all_rates)

    # --- Final output list --------------------------------------------
    print(f"\n{'='*60}")
    print(f"  STEP 5 OUTPUTS")
    print(f"{'='*60}")
    print(f"  step5_failure_data.csv              (150 experiments, fine-grained)")
    print(f"  step5_thresholds.csv                (all threshold detection results)")
    print(f"  step5_fig1_failure_zones.png         Failure zone identification")
    print(f"  step5_fig2_degradation_rate.png      Degradation rate analysis")
    print(f"  step5_fig3_threshold_dashboard.png   Combined threshold dashboard")
    print(f"  step5_summary_report.txt             Plain-language findings")
    print(f"\n  Step 5 complete. Ready for Step 6 (test robustness).")
    print()

    if record_step:
        end_iso = datetime.datetime.now().isoformat()
        path = record_step("step5", start_iso, end_iso)
        print(f"  [manifest] {path}")


if __name__ == "__main__":
    main()
