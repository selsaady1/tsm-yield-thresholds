# Real results: calibration + average-yield sensitivity

All numbers below come from the paper's own model (step2_freeze_model.run_experiment),
solved with CBC. Reproducible, no fabricated values.

## 1. Environment check (faithfulness)
- Paper baseline (Front-End 0.80-0.95, Back-End 0.70-0.90): VSS = $92.16, %VSS = 1.44%.
  This matches the paper to the cent, confirming the sandbox runs the real solver correctly.

## 2. Calibration to published yields
- Front-End mean moved 0.875 -> 0.90 (published mature-node value): baseline VSS
  $92.16 -> $92.33 (%VSS 1.44% -> 1.45%). Negligible; the result is robust to using the
  realistic Front-End mean.
- Adding realistic tight Back-End yield (0.955-0.995) raises baseline VSS to $121.74 (1.77%).

## 3. Average-yield sensitivity (reviewer request)
- VSS vs Front-End mean (spread 0.15, Back-End 0.70-0.90): nearly flat, $91.8-$92.8 across
  Front-End mean 0.80 to 0.95.
- VSS vs Back-End mean (spread 0.20, Front-End 0.80-0.95): rises from $50.9 (mean 0.70)
  to $122.7 (mean 0.95).

## 4. Threshold vs average yield (the key finding)
Front-End spread where %VSS crosses 2% (full-range / half-range):

| Front-End mean | Full-range spread | Half-range | Worst-case FE yield at crossing |
|---|---|---|---|
| 0.850 | 0.306 | 0.153 | 0.697 |
| 0.875 | 0.356 | 0.178 | 0.697 |
| 0.900 | 0.406 | 0.203 | 0.697 |

The paper's reported 0.178 half-range appears exactly at mean 0.875, confirming it.
Clean result: at every mean, the crossing happens where the WORST-CASE Front-End yield
(mean minus half-range) is about 0.70. With realistic tight Back-End yield (0.955-0.995)
the crossing worst-case Front-End yield is about 0.68.

## 5. What this means for the paper (honest reading)
- The threshold is not perfectly universal in "spread" terms: it shifts with mean yield,
  from about 0.15 to about 0.20 half-range as Front-End mean goes 0.85 to 0.90. This directly
  and honestly answers the reviewers who said the threshold assumed one mean yield.
- But it collapses to a cleaner, mean-independent rule: invest in stochastic planning once
  the worst-case Front-End yield falls below about 0.70. That is a stronger statement than a
  fixed 0.17-0.18 spread, and it turns the reviewer criticism into a better result.

Calibration sources: see Yield_Data_Sources.md.

## 6. Continuous (Beta) yield distribution (reviewer request: two-point is unrealistic)
Front-End yield modeled as a Beta distribution on [0,1], discretized into 7 equal-probability
points, matched to the same mean (0.875) and standard deviation as the two-point model
(a two-point model at full-range spread s has std s/2, so std sigma is the continuous analog
of full-range spread 2*sigma). Real solves via solve_rp / solve_rp_fixed. Beta is bounded,
so it never clips at 1.0.

- Fabrication check in the same run: two-point baseline reproduced VSS = $92.16 exactly.
- %VSS crosses 2% at an equivalent full-range spread of 0.2611 (half-range 0.1305),
  versus 0.3556 / 0.1778 for the two-point model.
- Reading: with a realistic continuous distribution, deterministic planning fails sooner
  (threshold half-range ~0.13 vs ~0.18). This confirms the paper's stated caveat that the
  two-point threshold (0.17-0.18) is a conservative upper bound. Raw sweep: beta_results.csv.

