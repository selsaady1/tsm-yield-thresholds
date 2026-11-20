#!/bin/zsh
# Reproduce every tsm_b run (prompt tsm_b, TSM-26-0314 revision: R1.7b, R1.7c, R1.8).
# Run from SANDBOX/code/tsm_b.  Solver runs only; no API calls; no random numbers.
set -e
source ./env.sh
nice -n 10 "$PY" run_r00_validate.py       # baseline RP/EEV/VSS reproduction and builder self-checks
nice -n 10 "$PY" run_r01_leadtime.py       # R1.7c multi-period, lead times, inventory, multistage
nice -n 10 "$PY" run_r02_aggregation.py    # R1.7b tool groups, non-identical fabs
nice -n 10 "$PY" run_r03_congestion.py     # R1.8 clearing function / congestion
"$PY" make_figs_tables.py                  # figure and tables from results/tsm_b/
"$PY" make_numbers.py                      # OUT/numbers.json and numbers.tex
"$PY" apply_blocks.py                      # sandbox .tex, OUT/manifest.json, OUT/patches
