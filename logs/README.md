# Solver logs

Raw CBC solver output for independent verification of the 493-experiment claim.

## Files

| File | Step | Experiments | Solves |
|------|------|-------------|--------|
| `step5_solver.log` | Step 5 (failure points) | 150 | ~450 (RP + EV + EEV per experiment) |
| `step6_solver.log` | Step 6 (robustness) | 200 | ~600 (RP + EV + EEV per experiment) |

## How to generate

Run with `--debug` to enable CBC `msg=True`:

```bash
python scripts/step5_failure_points.py --debug > solver_logs/step5_solver.log 2>&1
python scripts/step6_robustness.py --debug > solver_logs/step6_solver.log 2>&1
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
