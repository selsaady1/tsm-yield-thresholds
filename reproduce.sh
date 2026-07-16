#!/usr/bin/env bash
# Reproduces the headline results of "When Does Stochastic Planning Pay Off?"
# (Elsaady & Zhang). Each solve reaches proven optimality in <=0.01 CPU s (CBC).
set -e

# Resolve the repo root so this script works from any directory, and expose
# src/ on PYTHONPATH: the experiment scripts import the core model
# (step2_freeze_model) from src/.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

pip install -r requirements.txt

echo "== Step 1: baseline validation (expect RP \$6,380.66, EEV \$6,288.50, VSS \$92.16) =="
python src/step1_reproduce_vss.py

echo "== Calibration + mean-yield sensitivity (expect \$92.33 at FE mean 0.90) =="
python experiments/calib_sensitivity.py

echo "== Threshold vs mean (expect half-range 0.153/0.178/0.203; worst-case ~0.697) =="
python experiments/threshold_vs_mean.py

echo "== Continuous (Beta) yield distribution (expect crossing ~0.261 full / 0.131 half) =="
python experiments/beta_experiment.py

echo "== Steps 2-7 full pipeline (long; ~1,050 additional solves) =="
echo "   Run individually with src/ on PYTHONPATH (already exported above), e.g.:"
echo "     python src/step5_failure_points.py     # 150 experiments -> results/Step5/"
echo "     python src/step6_robustness.py         # 200 experiments -> results/Step6/"
echo "   Full chain: src/step2_freeze_model.py ... src/step7_deliver_guidance.py"
