#!/bin/zsh
# TSM-D: all runs, in order. Run from SANDBOX (PROJECT/TSM-26-0314_work/tsm_d).
# Interpreter: the repo venv (Python 3.14.5, PuLP 3.3.0, CBC 2.10.13 via brew symlink).
set -e
PY="${PY:-/Users/saifelsaady/Developer/Projects/PhD Research Project/tsm-yield-thresholds/.venv/bin/python}"
export MPLCONFIGDIR="$PWD/.mplcache"
for r in tsmd_r0_baseline tsmd_r1_cliff_binding tsmd_r2_matched_var tsmd_r3_mapping tsmd_r4_randinst; do mkdir -p results/tsm_d/$r; done
nice -n 10 "$PY" code/tsm_d/r0_baseline.py            > results/tsm_d/tsmd_r0_baseline/run.log 2>&1
nice -n 10 "$PY" code/tsm_d/r1_cliff_binding.py       > results/tsm_d/tsmd_r1_cliff_binding/run.log 2>&1 &
nice -n 10 "$PY" code/tsm_d/r2_matched_var.py         > results/tsm_d/tsmd_r2_matched_var/run.log 2>&1
wait
nice -n 10 "$PY" code/tsm_d/r3_mapping.py             > results/tsm_d/tsmd_r3_mapping/run.log 2>&1
nice -n 10 "$PY" code/tsm_d/r4_randinst.py --n 200 --workers 2 > results/tsm_d/tsmd_r4_randinst/run.log 2>&1
"$PY" code/tsm_d/summarize.py                         > results/tsm_d/tsmd_summary.log 2>&1 || true
echo ALL_DONE
