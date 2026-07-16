# Solver logs

Raw CBC solver output for independent verification of the 493-experiment claim.
Steps 5 and 6 account for **1,050 solves** in total (450 + 600); every one prints
`Result - Optimal solution found`.

## Files

| File | Step | Experiments | Solves |
|------|------|-------------|--------|
| `step5_solver.log`, `step5_cbc_full.log` | Step 5 (failure points) | 150 | 450 (RP + EV + EEV per experiment) |
| `step6_solver.log`, `step6_cbc_full.log` | Step 6 (robustness) | 200 | 600 (RP + EV + EEV per experiment) |

## How to generate

Run with `--debug` to enable CBC `msg=True`. The scripts live in `src/` and
import the core model (`step2_freeze_model`), so put `src/` on `PYTHONPATH`:

```bash
PYTHONPATH=src python src/step5_failure_points.py --debug > logs/step5_solver.log 2>&1
PYTHONPATH=src python src/step6_robustness.py    --debug > logs/step6_solver.log 2>&1
```

## What each log contains

For every solve, CBC prints:

- **Solver name**: CBC (Coin-or Branch and Cut)
- **Problem size**: rows, columns, elements
- **Solve time**: CPU seconds, wallclock seconds
- **Optimality status**: `Result - Optimal solution found` (or other status)
- **Objective value**: Final LP objective
- **Iteration count**: Total iterations

These logs allow reviewers to confirm that all solves ran and achieved optimal status.
