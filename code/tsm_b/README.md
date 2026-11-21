# tsm_b code (R1.7b, R1.7c, R1.8)

All runs are LP/MILP solves; no LLM or API calls; no random numbers are drawn (seed 0 is set and stated in every `run.json`).

## Environment (as run on 2026-11-13)

- Python 3.14.5 from `PROJECT/tsm-yield-thresholds/.venv` (used read-only, `PYTHONDONTWRITEBYTECODE=1`), PuLP 3.3.0, CBC 2.10.13 (Homebrew build, symlinked into PuLP's solver dir), SciPy 1.18.1 (HiGHS, only for the small re-planning LPs of the rolling deterministic comparator), matplotlib for the figure.
- CBC options: `PULP_CBC_CMD(msg=0, threads=1)`, default tolerances, no time limit. Every job started with `nice -n 10`; at most two solver processes at a time.
- The model builder of the repository (`repo/experiments/revision_common.py`, `repo/src/step2_freeze_model.py`) is imported unchanged; `run_r00_validate.py` reproduces RP 6,380.66, EEV 6,288.50, VSS 92.16 (1.44%), 13.12 vs 10.29 wafers, and checks every new builder against it with the extension switched off (max deviation 0).

## Files

| File | Role |
|---|---|
| `env.sh` | interpreter and paths |
| `tsmb_common.py` | paths, solver call, run folder and `run.json` (rule S4), crossing and bisection rules (same as the repo) |
| `tsmb_static.py` | single-period model with tool groups, non-identical fabs, clearing function / convex congestion cost (FE, per tool group, BE) |
| `tsmb_sweeps.py` | half-range sweeps, cliff check (solved onset by bisection vs prediction from the EV plan), tool-group data, `c_W` |
| `tsmb_multiperiod.py` | scenario-tree multi-period model (two-stage, multistage), EV/EEV, rolling deterministic comparator |
| `run_r00_validate.py` | baseline reproduction and self-checks |
| `run_r01_leadtime.py` | R1.7c: 9 configurations x 51 half-ranges |
| `run_r02_aggregation.py` | R1.7b: 6 configurations x 51 half-ranges |
| `run_r03_congestion.py` | R1.8: 9 configurations x 51 half-ranges, plus scenario-level cycle times |
| `make_figs_tables.py` | `fig_tsm_b_extB.pdf` and `tab_tsm_b_*.tex` from the run folders only |
| `make_numbers.py` | `OUT/numbers.json`, `numbers.tex`; `--print KEY` recomputes one key from the run files |
| `apply_blocks.py` | applies `OUT/sections/*.tex` to the sandbox copies (from `_base`), writes `OUT/manifest.json` and `OUT/patches/` |
| `run_all.sh` | everything above in order |

## Commands and actual runtimes (cwd `SANDBOX/code/tsm_b`, after `source env.sh`)

| run_id | command | runtime |
|---|---|---|
| tsmb_r00_validate | `nice -n 10 $PY run_r00_validate.py` | 1.0 s |
| tsmb_r01_leadtime_smoke | `nice -n 10 $PY run_r01_leadtime.py --smoke` | 12.6 s |
| tsmb_r02_aggregation_smoke | `nice -n 10 $PY run_r02_aggregation.py --smoke` | 5.2 s |
| tsmb_r03_congestion_smoke | `nice -n 10 $PY run_r03_congestion.py --smoke` | 8.8 s (second smoke run, after the tangent grid was refined to 0.01 steps) |
| tsmb_r01_leadtime | `nice -n 10 $PY run_r01_leadtime.py` | 645.6 s |
| tsmb_r02_aggregation | `nice -n 10 $PY run_r02_aggregation.py` | 17.1 s |
| tsmb_r03_congestion | `nice -n 10 $PY run_r03_congestion.py` | 33.5 s |

Then `$PY make_figs_tables.py`, `$PY make_numbers.py`, `$PY apply_blocks.py` (seconds each). Cost: USD 0.
