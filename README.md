# Yield Uncertainty Thresholds for Semiconductor Supply Chain Optimization

Code, experiments, results, and complete solver logs for:

> S. Elsaady and J. Zhang, "When Does Stochastic Planning Pay Off? Yield
> Uncertainty Thresholds for Semiconductor Supply Chain Optimization,"
> submitted to IEEE Transactions on Semiconductor Manufacturing, 2026.

## What this is

A three-stage (Front-End / Die Bank / Back-End) stochastic program is solved
across 493 controlled experiments that vary yield uncertainty while freezing
all other parameters. Headline result: for this single-product, single-period
instance class, deterministic (expected-value) planning loses more than 2% of
expected profit once the FE yield half-range spread exceeds ~0.17-0.18,
equivalently once the worst-case FE yield falls below ~70%.

Every number in the paper is regenerable from this repository. Each instance
is a MILP solved to proven optimality by CBC 2.10.3 via PuLP in <=0.01 CPU s;
`logs/` contains the raw CBC output for all 1,050 Step 5-6 solves.

## Layout

- `src/` - the seven-step pipeline. `step2_freeze_model.py` exposes
  `FrozenInstance` and `run_experiment` (the core model); `step1_reproduce_vss.py`
  reproduces the baseline (RP $6,380.66, EEV $6,288.50, VSS $92.16, 1.44%).
- `experiments/` - revision experiments: published-data calibration
  (`calib_sensitivity.py`), threshold vs. mean yield (`threshold_vs_mean.py`),
  continuous Beta yield distribution (`beta_experiment.py` + `beta_results.csv`),
  and figure regeneration (`fig_gen.py`).
- `results/` - per-step result CSVs and summary reports (Steps 1-7), including
  `Step7/step7_decision_table.csv` (the decision lookup table).
- `logs/` - complete CBC solver logs (all solves "Result - Optimal solution found").
- `docs/` - yield-calibration sources and the calibration/sensitivity results note.

## Reproduce

```bash
./reproduce.sh
```

Runs the baseline, calibration, mean-yield, and Beta experiments (~10-15 min
total on a laptop). The full Step 2-7 sweep scripts are in `src/` and are
listed at the end of `reproduce.sh`.

## Requirements

Python 3.10+, `pip install -r requirements.txt` (PuLP ships with CBC).
