# TSM-A: other planning approaches, capacity and demand uncertainty, scenarios from limited data

Code for the revision of IEEE TSM manuscript TSM-26-0314, prompt TSM-A (reviewer items
R1.1, R1.3, R1.7d-cap, R1.7d-dem, JZ.3). Article section `sec_extA.tex`
("Extensions I", inserted after Results) and supplement Section S-XV
(`supplement_extA.tex`), both in `TSM-26-0314/revision/paper/`.

Solver runs only: Python 3.14.5, PuLP 3.3.0, CBC 2.10.13 (Homebrew arm64 binary
symlinked into PuLP, see the repository README / environment notes). No language-model
API calls; cost USD 0.

## Files

| file | purpose |
|---|---|
| `tsa_common.py` | model builder: the paper's RP (Eqs. 1-9) plus max-min, CVaR, chance constraint, per-scenario capacities, per-fab yields, fixed-first-stage evaluation; provenance (`run.json`). `self_check()` asserts agreement with `experiments/revision_common.py` (itself checked against `src/step2_freeze_model.py`). Imports those files read-only; nothing outside `code/tsm_a/` and `results/tsm_a/` is modified. |
| `t0_baseline.py` | reproduces RP $6,380.66, EEV $6,288.50, VSS $92.16 before anything else |
| `t2_paradigms.py` | R1.3 / JZ.3: box, adjustable robust, budget, chance-constrained, CVaR plans; c_F = 1.50 and 15 |
| `t3_capacity.py` | R1.7d-cap: outsourced FE capacity and in-house FE capacity two-point random (16 scenarios) |
| `t4_demand_map.py` | R1.7d-dem: FE half-range x demand half-range x demand mean; checks reuse against Step 8 |
| `t5_limited_data.py` | R1.1: SAA and bootstrap scenario sets from n lot yields; exact out-of-sample evaluation |
| `make_figs_tables.py` | figures, LaTeX table bodies, `numbers.csv` (every quoted number with file and row) |
| `check_provenance.py` | matches every number in the two .tex files to `numbers.csv`, run.json, or a design parameter |
| `run_all.sh` | smoke tests, then all full runs, then figures/tables |
| `KEYS_FOR_TSM_C.md` | BibTeX and `\bibitem` text for the new citations (TSM-C owns the reference lists) |
| `latex/` | copies of `sec_extA.tex`, `supplement_extA.tex`, and the unified diffs of the two `\input` lines |
| `TSM_A_REPORT.md` | ID table, provenance tables A to D, TODO table, response-letter text, notes for other prompts |

## Exact commands (from the repository root `tsm-yield-thresholds/`)

```bash
bash code/tsm_a/run_all.sh
```

or one at a time:

```bash
.venv/bin/python code/tsm_a/t0_baseline.py
.venv/bin/python code/tsm_a/t2_paradigms.py
.venv/bin/python code/tsm_a/t3_capacity.py
.venv/bin/python code/tsm_a/t4_demand_map.py
.venv/bin/python code/tsm_a/t5_limited_data.py
.venv/bin/python code/tsm_a/make_figs_tables.py
.venv/bin/python code/tsm_a/check_provenance.py
```

Each experiment script accepts `--smoke` (reduced grid; output to `results/tsm_a/<run_id>_smoke/`).
Set `MPLCONFIGDIR` to a writable directory if `~/.matplotlib` is not writable.

## Seeds and runtimes (Nov 13, 2026, Apple-silicon Mac, git HEAD 98975b8 plus uncommitted files)

| run_id | seed | runtime (s) | status | outputs |
|---|---|---|---|---|
| t0_baseline | none (deterministic) | 0.7 | OK, baseline reproduced | `baseline.csv` |
| t2_paradigms | none | 51.2 | OK (12 chance-constrained points infeasible, recorded) | `points.csv`, `crossings.csv` |
| t3_capacity | none | 36.9 | OK | `points.csv`, `summary.csv` |
| t4_demand_map | none | 39.3 | OK | `grid.csv`, `summary.csv`, `reuse_check.csv` |
| t5_limited_data | 20261113 (`SeedSequence([20261113, sigma index, n, r])`) | 179.6 | OK | `replications.csv`, `summary.csv`, `truth.csv`, `validation.csv`, `qtables.npz` |
| figs_tables | none | < 1 | OK | `fig_extA_*.pdf`, `tab_*.tex`, `numbers.csv`, `provenance.csv` |

Every folder has a `run.json` with the command, seed, git commit, dirty-file list, SHA-256 of
each script in this folder, start and end time, solver and version, and runtime.

## Modelling notes

* All plans are compared on the paper's footing: wafer starts fixed, recourse re-optimised per scenario (as for EEV).
* Budgeted plan: worst case over the vertices of the budget set (finite-scenario version).
* In-house capacity uncertainty: processed wafers = min(planned, realised capacity), one binary per (fab, scenario); wafer cost on processed wafers; deterministic plan split in proportion to fab capacity (the solver's FE1-first split is also evaluated: column `pct_vss_cbc_split`).
* Limited data: the recourse value Q(D; demand, BE yield) is tabulated with CBC at every integer D in [0, 1800], its pieces recovered and validated against direct solves (max deviation 6.6e-5); the out-of-sample expectation is then exact (incomplete beta functions).
* Not run: the optional Wasserstein DRO plan of the prompt.
