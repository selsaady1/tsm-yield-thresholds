#!/usr/bin/env bash
# TSM-A (TSM-26-0314 revision): reproduce every number in sec_extA.tex and S-XV.
# Solver runs only (PuLP 3.3.0 + CBC 2.10.13); no API calls, cost USD 0.
# Run from the repository root:   bash code/tsm_a/run_all.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv/bin/python
export MPLCONFIGDIR="${MPLCONFIGDIR:-${TMPDIR:-/tmp}/mpl_tsm_a}"
mkdir -p "$MPLCONFIGDIR"

# smoke tests (tiny grids) first; outputs go to results/tsm_a/<run_id>_smoke/
$PY code/tsm_a/t2_paradigms.py --smoke
$PY code/tsm_a/t3_capacity.py --smoke
$PY code/tsm_a/t4_demand_map.py --smoke
$PY code/tsm_a/t5_limited_data.py --smoke

# full runs
$PY code/tsm_a/t0_baseline.py         # baseline RP / EEV / VSS must match the paper
$PY code/tsm_a/t2_paradigms.py        # R1.3, JZ.3
$PY code/tsm_a/t3_capacity.py         # R1.7d (capacity)
$PY code/tsm_a/t4_demand_map.py       # R1.7d (demand)
$PY code/tsm_a/t5_limited_data.py     # R1.1
$PY code/tsm_a/make_figs_tables.py    # figures, table bodies, numbers.csv
