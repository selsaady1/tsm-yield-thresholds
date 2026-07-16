"""
STEP 1: Continuous (Beta) Front-End yield distribution.
Replaces the two-point (low/high) FE yield with a Beta distribution discretized
into K equal-probability points, matched to the same mean and standard deviation.
Reuses the paper's real solver (solve_rp / solve_rp_fixed). No fabricated numbers.

Fair comparison: a two-point yield at full-range spread s has std = s/2.
So a Beta with std = sigma is the continuous analog of full-range spread = 2*sigma.
Beta is bounded on [0,1], so unlike the two-point model it never clips at 1.0.
"""
import csv
import numpy as np
from scipy.stats import beta as beta_dist
from step2_freeze_model import FrozenInstance, solve_rp, solve_rp_fixed

inst = FrozenInstance.step1_baseline().to_inst_dict()   # structure + costs only
DEM_LO, DEM_HI = inst["demand_lo"], inst["demand_hi"]

def beta_ab(mu, sigma):
    t = mu * (1 - mu) / (sigma ** 2) - 1.0
    return mu * t, (1 - mu) * t

def fe_levels(mu, sigma, K):
    a, b = beta_ab(mu, sigma)
    qs = (np.arange(1, K + 1) - 0.5) / K          # equal-probability quantile midpoints
    return [(float(beta_dist.ppf(q, a, b)), 1.0 / K) for q in qs]

def scen_beta(mu, sigma, be_lo, be_hi, K=7):
    fes = fe_levels(mu, sigma, K)
    scen = []
    for i, (fv, fp) in enumerate(fes):
        for dn, dv in [("Dlo", DEM_LO), ("Dhi", DEM_HI)]:
            for bn, bv in [("BElo", be_lo), ("BEhi", be_hi)]:
                scen.append({"name": f"FE{i}_{dn}_{bn}", "prob": fp * 0.25,
                             "fe_yield": fv, "demand": dv, "be_yield": bv})
    return scen

def run(scen):
    rp = solve_rp(inst, scen, tag="RPb")
    mfy = sum(s["prob"] * s["fe_yield"] for s in scen)
    mby = sum(s["prob"] * s["be_yield"] for s in scen)
    mdm = sum(s["prob"] * s["demand"]   for s in scen)
    ev = solve_rp(inst, [{"name": "EV", "prob": 1.0, "fe_yield": mfy,
                          "demand": mdm, "be_yield": mby}], tag="EVb")
    eev = solve_rp_fixed(inst, scen, ev["X_F"], ev["O_G"], ev["O_A"])
    vss = rp["obj"] - eev["obj"]
    pct = 100.0 * vss / abs(rp["obj"]) if rp["obj"] else 0.0
    return vss, pct

# --- Fabrication check: two-point baseline must reproduce $92.16 --------------
base = solve_rp(inst, [
    {"name": n, "prob": 0.125, "fe_yield": fy, "demand": dv, "be_yield": by}
    for n, fy, dv, by in [
        ("a", 0.80, DEM_LO, 0.70), ("b", 0.80, DEM_LO, 0.90),
        ("c", 0.80, DEM_HI, 0.70), ("d", 0.80, DEM_HI, 0.90),
        ("e", 0.95, DEM_LO, 0.70), ("f", 0.95, DEM_LO, 0.90),
        ("g", 0.95, DEM_HI, 0.70), ("h", 0.95, DEM_HI, 0.90)]], tag="chk")
r = FrozenInstance(0.80, 0.95, 0.70, 0.90)
from step2_freeze_model import run_experiment
chk = run_experiment(r)
print(f"RES| CHECK two-point baseline VSS = ${chk['vss']:.2f}  (paper: $92.16)")

# --- Beta sweep ---------------------------------------------------------------
mu = 0.875
rows = []
target = 2.0
prev = None
cross = None
for sigma in np.round(np.arange(0.02, 0.251, 0.0125), 4):
    eq_full = round(2 * sigma, 4)
    vss, pct = run(scen_beta(mu, sigma, 0.70, 0.90, K=7))
    rows.append([eq_full, sigma, round(vss, 3), round(pct, 4)])
    print(f"RES| Beta mu={mu} sigma={sigma:.4f} equiv_full_spread={eq_full:.4f} "
          f"VSS=${vss:7.2f} %VSS={pct:5.2f}")
    if prev and prev[1] < target <= pct:
        f = (target - prev[1]) / (pct - prev[1])
        cross = prev[0] + f * (eq_full - prev[0])
    prev = (eq_full, pct)

with open("beta_results.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["equiv_full_spread", "sigma", "vss", "pct_vss"]); w.writerows(rows)

print("RES| " + "-" * 60)
if cross:
    print(f"RES| Beta (continuous) %VSS>2% crossing: equiv full-range spread = {cross:.4f} "
          f"(half-range = {cross/2:.4f})")
print("RES| Two-point (paper) crossing at mean 0.875: full 0.3556 / half 0.1778")
