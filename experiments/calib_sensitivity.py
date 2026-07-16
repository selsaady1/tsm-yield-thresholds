"""
Calibration + average-yield sensitivity, reusing the paper's own model
(step2_freeze_model.run_experiment). Real solves only. No fabricated numbers.
"""
from step2_freeze_model import FrozenInstance, run_experiment

def mk(mean, spread):
    lo = max(0.01, mean - spread / 2.0)
    hi = min(1.00, mean + spread / 2.0)
    return round(lo, 4), round(hi, 4)

def one(fe_mean, fe_sp, be_mean, be_sp, label):
    fl, fh = mk(fe_mean, fe_sp)
    bl, bh = mk(be_mean, be_sp)
    r = run_experiment(FrozenInstance(fl, fh, bl, bh), label=label)
    vss = r.get("vss"); pct = r.get("pct_vss")
    su = r.get("eev_exp_unmet"); ru = r.get("rp_exp_unmet")
    sgap = (su - ru) if (su is not None and ru is not None) else float("nan")
    print(f"{label:<26s} FE[{fl:.3f},{fh:.3f}] BE[{bl:.3f},{bh:.3f}]  "
          f"VSS=${vss:7.2f}  %VSS={pct:5.2f}%  svc_gap={sgap:5.2f}")
    return r

print("="*96)
print("A) BASELINE CHECK (paper values)")
print("="*96)
one(0.875, 0.15, 0.800, 0.20, "paper baseline")

print("\n" + "="*96)
print("B) CALIBRATED TO PUBLISHED VALUES")
print("="*96)
one(0.900, 0.15, 0.800, 0.20, "FE calibrated (mean .90)")
one(0.900, 0.15, 0.975, 0.04, "FE .90 + realistic BE")

print("\n" + "="*96)
print("C) AVERAGE FRONT-END YIELD SENSITIVITY  (FE spread .15, BE 0.70-0.90)")
print("="*96)
for m in [0.80, 0.85, 0.875, 0.90, 0.925, 0.95]:
    one(m, 0.15, 0.800, 0.20, f"FE mean {m:.3f}")

print("\n" + "="*96)
print("D) AVERAGE BACK-END YIELD SENSITIVITY  (BE spread .20, FE 0.80-0.95)")
print("="*96)
for m in [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]:
    one(0.875, 0.15, m, 0.20, f"BE mean {m:.3f}")
