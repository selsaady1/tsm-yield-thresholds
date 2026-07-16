"""
Does the deterministic-planning threshold (%VSS > 2%) move when the AVERAGE yield
changes? Sweep FE full-range spread at several FE means; find the 2% crossing.
Real solves via the paper's own run_experiment. Full-range spread; half-range = /2.
"""
import numpy as np
from step2_freeze_model import FrozenInstance, run_experiment

def mk(mean, spread):
    return max(0.01, mean - spread/2.0), min(1.00, mean + spread/2.0)

def crossing(fe_mean, be_lo, be_hi, target=2.0):
    spreads = np.round(np.arange(0.02, 0.451, 0.015), 4)
    xs, ys = [], []
    for sp in spreads:
        fl, fh = mk(fe_mean, sp)
        r = run_experiment(FrozenInstance(round(fl,4), round(fh,4), be_lo, be_hi))
        xs.append(sp); ys.append(r["pct_vss"])
    for i in range(1, len(xs)):
        if ys[i-1] < target <= ys[i]:
            f = (target - ys[i-1]) / (ys[i] - ys[i-1])
            return xs[i-1] + f*(xs[i]-xs[i-1])
    return None

print("Threshold where %VSS crosses 2%  (BE held at 0.70-0.90, paper's Experiment A)")
print("-"*72)
for m in [0.850, 0.875, 0.900]:
    c = crossing(m, 0.70, 0.90)
    print(f"  FE mean {m:.3f}:  full-range spread = {c:.4f}   half-range = {c/2:.4f}" if c
          else f"  FE mean {m:.3f}:  no crossing")
print()
print("Same, but with realistic tight BE (0.955-0.995):")
print("-"*72)
for m in [0.875, 0.900]:
    c = crossing(m, 0.955, 0.995)
    print(f"  FE mean {m:.3f}:  full-range spread = {c:.4f}   half-range = {c/2:.4f}" if c
          else f"  FE mean {m:.3f}:  no crossing")
