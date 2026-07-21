"""
step2_freeze_model.py
=====================
Step 2: Lock the planning model structure, keep only yield parameters free.

Purpose
-------
This script freezes the validated Step 1 model - all costs, capacities,
prices, demand levels, and supply chain structure - and exposes ONLY the
yield parameters (FE yield range, BE yield range) as experimental inputs.

This creates the controlled experimental framework needed for Steps 3-7:
    - Independent variables: FE yield spread, BE yield spread
    - Dependent variables:   VSS, %VSS, wafer allocation, unmet demand, etc.
    - Controls (frozen):     Everything else

What this script does:
    1. Defines a FrozenInstance class that locks all non-yield parameters
    2. Provides run_experiment() that takes only yield inputs → returns metrics
    3. Validates that frozen model reproduces Step 1 results exactly
    4. Runs an initial yield-spread grid experiment (FE × BE)
    5. Outputs step2_experiment_results.csv and a heatmap figure

Usage
-----
    python step2_freeze_model.py

Requirements: Python 3.9+, PuLP  (pip install pulp)
Optional:     matplotlib        (pip install matplotlib) for heatmap
"""

import sys
import csv
import os
import datetime
import json
from itertools import product as cartesian
from copy import deepcopy

# ---------- Import PuLP ------------------------------------------------
try:
    from pulp import (
        LpProblem, LpMaximize, LpVariable, LpContinuous, LpBinary,
        lpSum, value, LpStatus, PULP_CBC_CMD,
    )
except ImportError:
    sys.exit("ERROR: PuLP is required.  Install with:  pip install pulp")

# ---------- Import matplotlib (optional) -------------------------------
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("[warning] matplotlib not installed - skipping heatmap.")

DEBUG = "--debug" in sys.argv


# ======================================================================
# 1.  FROZEN INSTANCE - The locked model parameters
# ======================================================================

class FrozenInstance:
    """
    Encapsulates ALL fixed parameters for the semiconductor supply chain.

    FROZEN (never changes across experiments):
        - Supply chain structure: 2 FE fabs, 1 DieBank, 2 BE facilities
        - Outsourcing options: 1 third-party FE, 1 third-party BE
        - All capacities (L_F, L_B, L_G, L_A)
        - All costs (c_F, c_G, c_B, c_A, c_K, c_D)
        - Selling price (p_d) and shortage penalty (v_d)
        - Demand levels (demand_lo, demand_hi)
        - Dies per wafer (n_f_i)
        - Number of scenarios (8) and equal probability (0.125)

    FREE (experimental inputs):
        - fe_yield_lo, fe_yield_hi  (Front-End yield range)
        - be_yield_lo, be_yield_hi  (Back-End yield range)

    The frozen values are exactly those from the validated Step 1 model.
    """

    # ---- Class-level frozen parameters (from Step 1 calibration) -----
    # These are CONSTANTS. They do not change.

    # Supply chain structure
    FE_SET  = ("FE1", "FE2")
    BE_SET  = ("BE1", "BE2")
    DB_SET  = ("DB1",)
    DEV_SET = ("D1",)
    DIE_SET = ("I1",)
    G_SET   = ("G1",)
    A_SET   = ("A1",)

    # Capacities
    L_F = {"FE1": 10, "FE2": 8}
    L_B = {"BE1": 500, "BE2": 400}
    L_G = {"G1": 300}
    L_A = {"A1": 150}

    # Costs
    N_F_I = 100         # gross dies per wafer
    C_F   = 1.5         # FE in-house cost per wafer
    C_G   = 1.65        # outsourced FE cost per die
    C_B   = 0.8         # BE in-house cost per device
    C_A   = 0.9         # outsourced BE cost per device
    C_K   = 0.05        # die-bank inventory cost per die
    C_D   = 0.05        # device inventory cost per device

    # Revenue and penalties
    P_D   = 10           # selling price per device
    V_D   = 3            # shortage penalty per device

    # Demand levels (frozen)
    DEMAND_LO = 600
    DEMAND_HI = 900

    # Scenario structure
    N_SCENARIOS = 8
    PROB_EACH   = 0.125

    # Step 1 baseline yields (for validation reference)
    STEP1_FE_LO = 0.80
    STEP1_FE_HI = 0.95
    STEP1_BE_LO = 0.70
    STEP1_BE_HI = 0.90
    STEP1_VSS   = 92.16   # expected VSS from Step 1 (for validation)

    def __init__(self, fe_yield_lo, fe_yield_hi, be_yield_lo, be_yield_hi):
        """
        Create an instance with specific yield parameters.
        All other parameters are frozen class-level constants.

        Parameters
        ----------
        fe_yield_lo : float   Front-End yield, low scenario (0 < y <= 1)
        fe_yield_hi : float   Front-End yield, high scenario (0 < y <= 1)
        be_yield_lo : float   Back-End yield, low scenario (0 < y <= 1)
        be_yield_hi : float   Back-End yield, high scenario (0 < y <= 1)
        """
        # --- Validate yield inputs ------------------------------------
        for name, val in [("fe_yield_lo", fe_yield_lo),
                          ("fe_yield_hi", fe_yield_hi),
                          ("be_yield_lo", be_yield_lo),
                          ("be_yield_hi", be_yield_hi)]:
            if not (0 < val <= 1.0):
                raise ValueError(f"{name} = {val} is out of range (0, 1]")
        if fe_yield_lo > fe_yield_hi:
            raise ValueError(f"fe_yield_lo ({fe_yield_lo}) > fe_yield_hi ({fe_yield_hi})")
        if be_yield_lo > be_yield_hi:
            raise ValueError(f"be_yield_lo ({be_yield_lo}) > be_yield_hi ({be_yield_hi})")

        # --- Store the FREE parameters --------------------------------
        self.fe_yield_lo = fe_yield_lo
        self.fe_yield_hi = fe_yield_hi
        self.be_yield_lo = be_yield_lo
        self.be_yield_hi = be_yield_hi

    @property
    def fe_spread(self):
        """FE yield spread (high - low). Measures FE uncertainty."""
        return self.fe_yield_hi - self.fe_yield_lo

    @property
    def be_spread(self):
        """BE yield spread (high - low). Measures BE uncertainty."""
        return self.be_yield_hi - self.be_yield_lo

    @property
    def fe_mean(self):
        """Expected FE yield (midpoint of lo/hi)."""
        return (self.fe_yield_lo + self.fe_yield_hi) / 2

    @property
    def be_mean(self):
        """Expected BE yield (midpoint of lo/hi)."""
        return (self.be_yield_lo + self.be_yield_hi) / 2

    def to_inst_dict(self):
        """Convert to the dict format expected by solve_rp / solve_ev."""
        return {
            "FE_set":  list(self.FE_SET),
            "BE_set":  list(self.BE_SET),
            "DB_set":  list(self.DB_SET),
            "DEV_set": list(self.DEV_SET),
            "DIE_set": list(self.DIE_SET),
            "G_set":   list(self.G_SET),
            "A_set":   list(self.A_SET),
            "n_f_i":   self.N_F_I,
            "L_F":     dict(self.L_F),
            "L_B":     dict(self.L_B),
            "L_G":     dict(self.L_G),
            "L_A":     dict(self.L_A),
            "p_d":     self.P_D,
            "v_d":     self.V_D,
            "c_F":     self.C_F,
            "c_G":     self.C_G,
            "c_B":     self.C_B,
            "c_A":     self.C_A,
            "c_K":     self.C_K,
            "c_D":     self.C_D,
            "fe_yield_lo": self.fe_yield_lo,
            "fe_yield_hi": self.fe_yield_hi,
            "be_yield_lo": self.be_yield_lo,
            "be_yield_hi": self.be_yield_hi,
            "demand_lo":   self.DEMAND_LO,
            "demand_hi":   self.DEMAND_HI,
        }

    def describe(self):
        """Print a human-readable summary showing frozen vs free params."""
        print(f"\n{'='*60}")
        print(f"  FROZEN INSTANCE CONFIGURATION")
        print(f"{'='*60}")
        print(f"\n  --- FROZEN PARAMETERS (do not change) ---")
        print(f"  Structure:   {len(self.FE_SET)} FE, {len(self.DB_SET)} DB, "
              f"{len(self.BE_SET)} BE, {len(self.G_SET)} outsrc FE, "
              f"{len(self.A_SET)} outsrc BE")
        print(f"  FE capacity: FE1={self.L_F['FE1']}, FE2={self.L_F['FE2']} wafers")
        print(f"  BE capacity: BE1={self.L_B['BE1']}, BE2={self.L_B['BE2']} devices")
        print(f"  Dies/wafer:  {self.N_F_I}")
        print(f"  Costs:       c_F={self.C_F}, c_G={self.C_G}, "
              f"c_B={self.C_B}, c_A={self.C_A}")
        print(f"  Inventory:   c_K={self.C_K}, c_D={self.C_D}")
        print(f"  Price:       p_d={self.P_D},  penalty: v_d={self.V_D}")
        print(f"  Demand:      [{self.DEMAND_LO}, {self.DEMAND_HI}]")
        print(f"  Scenarios:   {self.N_SCENARIOS} (prob={self.PROB_EACH} each)")
        print(f"\n  --- FREE PARAMETERS (experimental inputs) ---")
        print(f"  FE yield:    [{self.fe_yield_lo:.4f}, {self.fe_yield_hi:.4f}]"
              f"  spread={self.fe_spread:.4f}  mean={self.fe_mean:.4f}")
        print(f"  BE yield:    [{self.be_yield_lo:.4f}, {self.be_yield_hi:.4f}]"
              f"  spread={self.be_spread:.4f}  mean={self.be_mean:.4f}")
        print()

    @classmethod
    def step1_baseline(cls):
        """Create the exact Step 1 validated instance (for verification)."""
        return cls(
            fe_yield_lo=cls.STEP1_FE_LO,
            fe_yield_hi=cls.STEP1_FE_HI,
            be_yield_lo=cls.STEP1_BE_LO,
            be_yield_hi=cls.STEP1_BE_HI,
        )

    def frozen_manifest(self):
        """Return a dict documenting exactly what is frozen (for logging)."""
        return {
            "frozen_date": datetime.datetime.now().isoformat(),
            "structure": {
                "FE_fabs": list(self.FE_SET),
                "BE_fabs": list(self.BE_SET),
                "DieBanks": list(self.DB_SET),
                "Outsource_FE": list(self.G_SET),
                "Outsource_BE": list(self.A_SET),
            },
            "capacities": {
                "L_F": dict(self.L_F),
                "L_B": dict(self.L_B),
                "L_G": dict(self.L_G),
                "L_A": dict(self.L_A),
            },
            "costs": {
                "c_F": self.C_F, "c_G": self.C_G,
                "c_B": self.C_B, "c_A": self.C_A,
                "c_K": self.C_K, "c_D": self.C_D,
            },
            "revenue": {"p_d": self.P_D, "v_d": self.V_D},
            "demand": {"lo": self.DEMAND_LO, "hi": self.DEMAND_HI},
            "dies_per_wafer": self.N_F_I,
            "scenarios": self.N_SCENARIOS,
        }


# ======================================================================
# 2.  SOLVER FUNCTIONS (reused from Step 1 - no changes)
# ======================================================================
# These are identical to reproduce_vss.py.  The model structure is
# already locked by the FrozenInstance; these functions just execute it.

def build_scenarios(inst_dict):
    """Build 8 equiprobable scenarios from yield/demand combinations."""
    fe_levels = [("FElo", inst_dict["fe_yield_lo"]),
                 ("FEhi", inst_dict["fe_yield_hi"])]
    dm_levels = [("Dlo",  inst_dict["demand_lo"]),
                 ("Dhi",  inst_dict["demand_hi"])]
    be_levels = [("BElo", inst_dict["be_yield_lo"]),
                 ("BEhi", inst_dict["be_yield_hi"])]
    scenarios = []
    for (fn, fv), (dn, dv), (bn, bv) in cartesian(fe_levels, dm_levels,
                                                    be_levels):
        scenarios.append({
            "name": f"{fn}_{dn}_{bn}", "prob": 0.125,
            "fe_yield": fv, "demand": dv, "be_yield": bv,
        })
    return scenarios


def solve_rp(inst_dict, scenarios, tag="RP"):
    """Solve the stochastic recourse problem (RP). Returns result dict."""
    prob = LpProblem(f"SemiCond_{tag}", LpMaximize)

    FE = inst_dict["FE_set"];  BE = inst_dict["BE_set"]
    G  = inst_dict["G_set"];   A  = inst_dict["A_set"]
    S  = [s["name"] for s in scenarios]
    sp = {s["name"]: s["prob"]     for s in scenarios}
    fy = {s["name"]: s["fe_yield"] for s in scenarios}
    by_ = {s["name"]: s["be_yield"] for s in scenarios}
    dm = {s["name"]: s["demand"]   for s in scenarios}

    n = inst_dict["n_f_i"]
    c_F = inst_dict["c_F"]; c_G = inst_dict["c_G"]
    c_B = inst_dict["c_B"]; c_A = inst_dict["c_A"]
    c_K = inst_dict["c_K"]; c_D = inst_dict["c_D"]
    p_d = inst_dict["p_d"]; v_d = inst_dict["v_d"]

    # Stage 1 variables
    X_F = {f: LpVariable(f"XF_{f}_{tag}", 0, None, LpContinuous) for f in FE}
    O_G = {g: LpVariable(f"OG_{g}_{tag}", 0, 1, LpBinary) for g in G}
    O_A = {a: LpVariable(f"OA_{a}_{tag}", 0, 1, LpBinary) for a in A}

    # Stage 2 variables
    X_FK = {(s, f): LpVariable(f"XFK_{s}_{f}_{tag}", 0) for s in S for f in FE}
    X_GK = {(s, g): LpVariable(f"XGK_{s}_{g}_{tag}", 0) for s in S for g in G}
    Z = {s: LpVariable(f"Z_{s}_{tag}", 0) for s in S}
    X_KB = {(s, b): LpVariable(f"XKB_{s}_{b}_{tag}", 0) for s in S for b in BE}
    X_KA = {(s, a): LpVariable(f"XKA_{s}_{a}_{tag}", 0) for s in S for a in A}

    # Stage 3 variables
    X_BD = {(s, b): LpVariable(f"XBD_{s}_{b}_{tag}", 0) for s in S for b in BE}
    X_AD = {(s, a): LpVariable(f"XAD_{s}_{a}_{tag}", 0) for s in S for a in A}
    M = {s: LpVariable(f"M_{s}_{tag}", 0) for s in S}
    W = {s: LpVariable(f"W_{s}_{tag}", 0) for s in S}

    # Objective
    stage1_cost = lpSum(c_F * X_F[f] for f in FE)
    scenario_obj = []
    for s in S:
        revenue  = p_d * (dm[s] - M[s])
        penalty  = v_d * M[s]
        inv_die  = c_K * Z[s]
        inv_dev  = c_D * W[s]
        cost_g   = lpSum(c_G * X_GK[(s, g)] for g in G)
        cost_b   = lpSum(c_B * X_KB[(s, b)] for b in BE)
        cost_a   = lpSum(c_A * X_KA[(s, a)] for a in A)
        scen_profit = revenue - penalty - inv_die - inv_dev - cost_g - cost_b - cost_a
        scenario_obj.append(sp[s] * scen_profit)
    prob += lpSum(scenario_obj) - stage1_cost, "expected_profit"

    # Constraints
    for f in FE:
        prob += X_F[f] <= inst_dict["L_F"][f], f"FE_cap_{f}"
    for s in S:
        for f in FE:
            prob += X_FK[(s, f)] <= fy[s] * n * X_F[f], f"FE_yield_{s}_{f}"
    for s in S:
        for g in G:
            prob += X_GK[(s, g)] <= inst_dict["L_G"][g] * O_G[g], f"OG_cap_{s}_{g}"
    for s in S:
        incoming = lpSum(X_FK[(s, f)] for f in FE) + lpSum(X_GK[(s, g)] for g in G)
        used = lpSum(X_KB[(s, b)] for b in BE) + lpSum(X_KA[(s, a)] for a in A)
        prob += incoming - used - Z[s] == 0, f"DB_balance_{s}"
    for s in S:
        for b in BE:
            prob += X_KB[(s, b)] <= inst_dict["L_B"][b], f"BE_cap_{s}_{b}"
    for s in S:
        for b in BE:
            prob += X_BD[(s, b)] <= by_[s] * X_KB[(s, b)], f"BE_yield_{s}_{b}"
    for s in S:
        for a in A:
            prob += X_KA[(s, a)] <= inst_dict["L_A"][a] * O_A[a], f"OA_cap_{s}_{a}"
    for s in S:
        for a in A:
            prob += X_AD[(s, a)] == X_KA[(s, a)], f"OA_flow_{s}_{a}"
    for s in S:
        total_dev = lpSum(X_BD[(s, b)] for b in BE) + lpSum(X_AD[(s, a)] for a in A)
        prob += total_dev + M[s] - W[s] == dm[s], f"demand_bal_{s}"

    # Solve
    solver = PULP_CBC_CMD(msg=DEBUG)
    prob.solve(solver)

    return {
        "tag": tag, "status": LpStatus[prob.status], "obj": value(prob.objective),
        "X_F": {f: value(X_F[f]) for f in FE},
        "O_G": {g: value(O_G[g]) for g in G},
        "O_A": {a: value(O_A[a]) for a in A},
        "Z": {s: value(Z[s]) for s in S},
        "M": {s: value(M[s]) for s in S},
        "W": {s: value(W[s]) for s in S},
        "X_GK": {(s, g): value(X_GK[(s, g)]) for s in S for g in G},
        "X_KB": {(s, b): value(X_KB[(s, b)]) for s in S for b in BE},
        "X_BD": {(s, b): value(X_BD[(s, b)]) for s in S for b in BE},
        "X_AD": {(s, a): value(X_AD[(s, a)]) for s in S for a in A},
        "scenarios": scenarios,
    }


def solve_rp_fixed(inst_dict, scenarios, fix_xf, fix_og, fix_oa):
    """Solve RP with first-stage variables fixed (for EEV computation)."""
    prob = LpProblem("SemiCond_EEV", LpMaximize)

    FE = inst_dict["FE_set"];  BE = inst_dict["BE_set"]
    G  = inst_dict["G_set"];   A  = inst_dict["A_set"]
    S  = [s["name"] for s in scenarios]
    sp = {s["name"]: s["prob"]     for s in scenarios}
    fy = {s["name"]: s["fe_yield"] for s in scenarios}
    by_ = {s["name"]: s["be_yield"] for s in scenarios}
    dm = {s["name"]: s["demand"]   for s in scenarios}

    n = inst_dict["n_f_i"]
    c_F = inst_dict["c_F"]; c_G = inst_dict["c_G"]
    c_B = inst_dict["c_B"]; c_A = inst_dict["c_A"]
    c_K = inst_dict["c_K"]; c_D = inst_dict["c_D"]
    p_d = inst_dict["p_d"]; v_d = inst_dict["v_d"]

    # Fixed first-stage
    X_F = {f: LpVariable(f"XF_{f}_EEV", fix_xf[f], fix_xf[f], LpContinuous) for f in FE}
    O_G = {g: LpVariable(f"OG_{g}_EEV", fix_og[g], fix_og[g], LpBinary) for g in G}
    O_A = {a: LpVariable(f"OA_{a}_EEV", fix_oa[a], fix_oa[a], LpBinary) for a in A}

    # Recourse variables
    X_FK = {(s, f): LpVariable(f"XFK_{s}_{f}_EEV", 0) for s in S for f in FE}
    X_GK = {(s, g): LpVariable(f"XGK_{s}_{g}_EEV", 0) for s in S for g in G}
    Z  = {s: LpVariable(f"Z_{s}_EEV", 0) for s in S}
    X_KB = {(s, b): LpVariable(f"XKB_{s}_{b}_EEV", 0) for s in S for b in BE}
    X_KA = {(s, a): LpVariable(f"XKA_{s}_{a}_EEV", 0) for s in S for a in A}
    X_BD = {(s, b): LpVariable(f"XBD_{s}_{b}_EEV", 0) for s in S for b in BE}
    X_AD = {(s, a): LpVariable(f"XAD_{s}_{a}_EEV", 0) for s in S for a in A}
    M  = {s: LpVariable(f"M_{s}_EEV", 0) for s in S}
    W  = {s: LpVariable(f"W_{s}_EEV", 0) for s in S}

    # Objective
    stage1_cost = lpSum(c_F * X_F[f] for f in FE)
    scenario_obj = []
    for s in S:
        revenue  = p_d * (dm[s] - M[s])
        penalty  = v_d * M[s]
        inv_die  = c_K * Z[s]
        inv_dev  = c_D * W[s]
        cost_g   = lpSum(c_G * X_GK[(s, g)] for g in G)
        cost_b   = lpSum(c_B * X_KB[(s, b)] for b in BE)
        cost_a   = lpSum(c_A * X_KA[(s, a)] for a in A)
        scen_profit = revenue - penalty - inv_die - inv_dev - cost_g - cost_b - cost_a
        scenario_obj.append(sp[s] * scen_profit)
    prob += lpSum(scenario_obj) - stage1_cost, "expected_profit_EEV"

    # Constraints (identical to RP)
    for f in FE:
        prob += X_F[f] <= inst_dict["L_F"][f], f"FE_cap_{f}"
    for s in S:
        for f in FE:
            prob += X_FK[(s, f)] <= fy[s] * n * X_F[f], f"FE_yield_{s}_{f}"
    for s in S:
        for g in G:
            prob += X_GK[(s, g)] <= inst_dict["L_G"][g] * O_G[g], f"OG_cap_{s}_{g}"
    for s in S:
        incoming = lpSum(X_FK[(s, f)] for f in FE) + lpSum(X_GK[(s, g)] for g in G)
        used = lpSum(X_KB[(s, b)] for b in BE) + lpSum(X_KA[(s, a)] for a in A)
        prob += incoming - used - Z[s] == 0, f"DB_balance_{s}"
    for s in S:
        for b in BE:
            prob += X_KB[(s, b)] <= inst_dict["L_B"][b], f"BE_cap_{s}_{b}"
    for s in S:
        for b in BE:
            prob += X_BD[(s, b)] <= by_[s] * X_KB[(s, b)], f"BE_yield_{s}_{b}"
    for s in S:
        for a in A:
            prob += X_KA[(s, a)] <= inst_dict["L_A"][a] * O_A[a], f"OA_cap_{s}_{a}"
    for s in S:
        for a in A:
            prob += X_AD[(s, a)] == X_KA[(s, a)], f"OA_flow_{s}_{a}"
    for s in S:
        total_dev = lpSum(X_BD[(s, b)] for b in BE) + lpSum(X_AD[(s, a)] for a in A)
        prob += total_dev + M[s] - W[s] == dm[s], f"demand_bal_{s}"

    solver = PULP_CBC_CMD(msg=DEBUG)
    prob.solve(solver)

    return {
        "tag": "EEV", "status": LpStatus[prob.status], "obj": value(prob.objective),
        "X_F": {f: value(X_F[f]) for f in FE},
        "O_G": {g: value(O_G[g]) for g in G},
        "O_A": {a: value(O_A[a]) for a in A},
        "Z": {s: value(Z[s]) for s in S},
        "M": {s: value(M[s]) for s in S},
        "W": {s: value(W[s]) for s in S},
        "X_GK": {(s, g): value(X_GK[(s, g)]) for s in S for g in G},
        "X_KB": {(s, b): value(X_KB[(s, b)]) for s in S for b in BE},
        "X_BD": {(s, b): value(X_BD[(s, b)]) for s in S for b in BE},
        "X_AD": {(s, a): value(X_AD[(s, a)]) for s in S for a in A},
        "scenarios": scenarios,
    }


# ======================================================================
# 3.  RUN_EXPERIMENT - The main experimental interface
# ======================================================================

def run_experiment(frozen_inst, label="", include_raw=False):
    """
    Run one complete RP vs EEV comparison for a given FrozenInstance.

    This is the ONLY function you call to run an experiment.
    It takes a FrozenInstance (which has locked structure + free yields)
    and returns a dict with all metrics needed for analysis.

    Parameters
    ----------
    frozen_inst : FrozenInstance
        The instance with specific yield parameters set.
    label : str
        Optional label for this experiment run.
    include_raw : bool
        If True, add rp_raw and eev_raw to the return dict with full
        per-scenario decision variables (for step3_scenario_decisions export).

    Returns
    -------
    dict with keys:
        label, fe_yield_lo, fe_yield_hi, be_yield_lo, be_yield_hi,
        fe_spread, be_spread, fe_mean, be_mean,
        rp_obj, eev_obj, vss, pct_vss,
        rp_xf_fe1, rp_xf_fe2, ev_xf_fe1, ev_xf_fe2,
        rp_total_starts, ev_total_starts,
        rp_outsource_fe, rp_outsource_be,
        ev_outsource_fe, ev_outsource_be,
        rp_exp_unmet, eev_exp_unmet,
        rp_exp_inv, eev_exp_inv,
        status_rp, status_eev
    """
    inst = frozen_inst.to_inst_dict()
    scenarios = build_scenarios(inst)

    # --- Solve RP (stochastic) ----------------------------------------
    rp = solve_rp(inst, scenarios, tag=f"RP_{label}")

    # --- Solve EV (deterministic with mean yields) --------------------
    mean_fy = sum(s["prob"] * s["fe_yield"] for s in scenarios)
    mean_by = sum(s["prob"] * s["be_yield"] for s in scenarios)
    mean_dm = sum(s["prob"] * s["demand"]   for s in scenarios)
    ev_scen = [{"name": "EV_avg", "prob": 1.0,
                "fe_yield": mean_fy, "demand": mean_dm, "be_yield": mean_by}]
    ev = solve_rp(inst, ev_scen, tag=f"EV_{label}")

    # --- Fix first-stage from EV, evaluate under all scenarios → EEV --
    eev = solve_rp_fixed(inst, scenarios, ev["X_F"], ev["O_G"], ev["O_A"])

    # --- Compute metrics ----------------------------------------------
    S = [s["name"] for s in scenarios]
    sp = {s["name"]: s["prob"] for s in scenarios}

    vss = rp["obj"] - eev["obj"]
    pct_vss = 100.0 * vss / abs(rp["obj"]) if rp["obj"] != 0 else 0.0

    rp_unmet  = sum(sp[s] * (rp["M"][s] or 0) for s in S)
    eev_unmet = sum(sp[s] * (eev["M"][s] or 0) for s in S)
    rp_inv    = sum(sp[s] * (rp["Z"][s] or 0) for s in S)
    eev_inv   = sum(sp[s] * (eev["Z"][s] or 0) for s in S)

    out = {
        "label":         label,
        "fe_yield_lo":   frozen_inst.fe_yield_lo,
        "fe_yield_hi":   frozen_inst.fe_yield_hi,
        "be_yield_lo":   frozen_inst.be_yield_lo,
        "be_yield_hi":   frozen_inst.be_yield_hi,
        "fe_spread":     frozen_inst.fe_spread,
        "be_spread":     frozen_inst.be_spread,
        "fe_mean":       frozen_inst.fe_mean,
        "be_mean":       frozen_inst.be_mean,
        "rp_obj":        rp["obj"],
        "eev_obj":       eev["obj"],
        "vss":           vss,
        "pct_vss":       pct_vss,
        "rp_xf_fe1":    rp["X_F"]["FE1"] or 0,
        "rp_xf_fe2":    rp["X_F"]["FE2"] or 0,
        "ev_xf_fe1":    eev["X_F"]["FE1"] or 0,
        "ev_xf_fe2":    eev["X_F"]["FE2"] or 0,
        "rp_total_starts": sum(v or 0 for v in rp["X_F"].values()),
        "ev_total_starts": sum(v or 0 for v in eev["X_F"].values()),
        "rp_outsource_fe": "Yes" if (rp["O_G"]["G1"] or 0) > 0.5 else "No",
        "rp_outsource_be": "Yes" if (rp["O_A"]["A1"] or 0) > 0.5 else "No",
        "ev_outsource_fe": "Yes" if (eev["O_G"]["G1"] or 0) > 0.5 else "No",
        "ev_outsource_be": "Yes" if (eev["O_A"]["A1"] or 0) > 0.5 else "No",
        "rp_exp_unmet":  rp_unmet,
        "eev_exp_unmet": eev_unmet,
        "rp_exp_inv":    rp_inv,
        "eev_exp_inv":   eev_inv,
        "status_rp":     rp["status"],
        "status_eev":    eev["status"],
    }
    if include_raw:
        out["rp_raw"] = rp
        out["eev_raw"] = eev
    return out


# ======================================================================
# 4.  VALIDATION - Confirm Step 1 results are reproduced exactly
# ======================================================================

def validate_step1():
    """
    Run the frozen model with Step 1 baseline yields and verify
    that we get the same VSS.  This is the critical sanity check.
    """
    print(f"\n{'='*60}")
    print(f"  STEP 2 VALIDATION: Reproducing Step 1 baseline")
    print(f"{'='*60}")

    baseline = FrozenInstance.step1_baseline()
    baseline.describe()

    result = run_experiment(baseline, label="step1_validation")

    print(f"  Results:")
    print(f"    RP objective:  {result['rp_obj']:.2f}")
    print(f"    EEV objective: {result['eev_obj']:.2f}")
    print(f"    VSS:           {result['vss']:.2f}")
    print(f"    %VSS:          {result['pct_vss']:.2f}%")
    print()

    # Check against Step 1 expected value
    expected_vss = FrozenInstance.STEP1_VSS
    tolerance = 1.0  # allow $1 tolerance for solver numerics
    diff = abs(result["vss"] - expected_vss)

    if diff <= tolerance:
        print(f"  ✓ VALIDATION PASSED")
        print(f"    VSS = ${result['vss']:.2f}  (expected ~${expected_vss:.2f}, "
              f"diff = ${diff:.2f})")
    else:
        print(f"  ✗ VALIDATION FAILED")
        print(f"    VSS = ${result['vss']:.2f}  (expected ~${expected_vss:.2f}, "
              f"diff = ${diff:.2f} > tolerance ${tolerance:.2f})")
        print(f"    Check that frozen parameters match Step 1 exactly.")

    print()
    return result


# ======================================================================
# 5.  YIELD SPREAD GRID EXPERIMENT
# ======================================================================

def run_yield_grid():
    """
    Systematic experiment: vary FE and BE yield spreads independently
    while keeping their means at the Step 1 baseline values.

    This is the first real experiment using the frozen model.
    It answers: "How does VSS change when FE uncertainty and BE
    uncertainty change independently?"

    Grid design:
        FE spread: [0.03, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
        BE spread: [0.04, 0.08, 0.15, 0.20, 0.25, 0.30, 0.40]
        Total: 7 × 7 = 49 experiments

    Yields are constructed as:  mean ± spread/2
        FE mean = 0.875  (from Step 1: (0.80 + 0.95) / 2)
        BE mean = 0.800  (from Step 1: (0.70 + 0.90) / 2)
    """
    print(f"\n{'='*60}")
    print(f"  YIELD SPREAD GRID EXPERIMENT")
    print(f"{'='*60}")

    # Step 1 baseline means
    fe_mean = (FrozenInstance.STEP1_FE_LO + FrozenInstance.STEP1_FE_HI) / 2  # 0.875
    be_mean = (FrozenInstance.STEP1_BE_LO + FrozenInstance.STEP1_BE_HI) / 2  # 0.800

    # Spread values to test
    fe_spreads = [0.03, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
    be_spreads = [0.04, 0.08, 0.15, 0.20, 0.25, 0.30, 0.40]

    print(f"  FE mean (fixed): {fe_mean:.4f}")
    print(f"  BE mean (fixed): {be_mean:.4f}")
    print(f"  FE spreads:      {fe_spreads}")
    print(f"  BE spreads:      {be_spreads}")
    print(f"  Total experiments: {len(fe_spreads) * len(be_spreads)}")
    print()

    results = []
    exp_num = 0

    for fe_sp in fe_spreads:
        for be_sp in be_spreads:
            exp_num += 1

            fe_lo = max(0.01, fe_mean - fe_sp / 2)
            fe_hi = min(1.00, fe_mean + fe_sp / 2)
            be_lo = max(0.01, be_mean - be_sp / 2)
            be_hi = min(1.00, be_mean + be_sp / 2)

            label = f"FEsp{fe_sp:.2f}_BEsp{be_sp:.2f}"

            fi = FrozenInstance(fe_lo, fe_hi, be_lo, be_hi)
            r = run_experiment(fi, label=label)
            results.append(r)

            print(f"  [{exp_num:>3d}] FE=[{fe_lo:.3f},{fe_hi:.3f}] "
                  f"BE=[{be_lo:.3f},{be_hi:.3f}]  "
                  f"VSS=${r['vss']:>8.2f}  %VSS={r['pct_vss']:>5.2f}%  "
                  f"RP_starts={r['rp_total_starts']:.1f}  "
                  f"EV_starts={r['ev_total_starts']:.1f}")

    print(f"\n  Completed {len(results)} experiments.")
    return results, fe_spreads, be_spreads


# ======================================================================
# 6.  OUTPUT - CSV and Heatmap
# ======================================================================

def save_results_csv(results, filepath="step2_experiment_results.csv"):
    """Save all experiment results to a CSV file."""
    if not results:
        return

    fieldnames = [
        "label", "fe_yield_lo", "fe_yield_hi", "be_yield_lo", "be_yield_hi",
        "fe_spread", "be_spread", "fe_mean", "be_mean",
        "rp_obj", "eev_obj", "vss", "pct_vss",
        "rp_xf_fe1", "rp_xf_fe2", "ev_xf_fe1", "ev_xf_fe2",
        "rp_total_starts", "ev_total_starts",
        "rp_outsource_fe", "rp_outsource_be",
        "ev_outsource_fe", "ev_outsource_be",
        "rp_exp_unmet", "eev_exp_unmet",
        "rp_exp_inv", "eev_exp_inv",
        "status_rp", "status_eev",
    ]

    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            # Round floats for readability
            row = {}
            for k in fieldnames:
                v = r[k]
                if isinstance(v, float):
                    row[k] = f"{v:.4f}"
                else:
                    row[k] = v
            writer.writerow(row)

    print(f"\n  [saved] {filepath}  ({len(results)} rows)")


def save_frozen_manifest(filepath="step2_frozen_manifest.json"):
    """Save the frozen parameter manifest as a JSON file for documentation."""
    baseline = FrozenInstance.step1_baseline()
    manifest = baseline.frozen_manifest()
    manifest["description"] = (
        "This file documents all parameters that are FROZEN (locked) "
        "for the Step 2+ experiments. Only yield parameters "
        "(fe_yield_lo/hi, be_yield_lo/hi) are allowed to vary."
    )
    manifest["step1_baseline_yields"] = {
        "fe_yield_lo": FrozenInstance.STEP1_FE_LO,
        "fe_yield_hi": FrozenInstance.STEP1_FE_HI,
        "be_yield_lo": FrozenInstance.STEP1_BE_LO,
        "be_yield_hi": FrozenInstance.STEP1_BE_HI,
    }

    with open(filepath, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"  [saved] {filepath}")


def plot_vss_heatmap(results, fe_spreads, be_spreads,
                     filepath="step2_vss_heatmap.png"):
    """
    Create a heatmap: VSS as a function of FE spread (x) and BE spread (y).
    This is the key visualization for Step 2 - it shows how the value
    of stochastic planning depends on WHERE the uncertainty is.
    """
    if not HAS_MPL:
        print("  [skip] No matplotlib - cannot generate heatmap.")
        return

    # Build the VSS grid
    n_fe = len(fe_spreads)
    n_be = len(be_spreads)
    vss_grid = [[0.0] * n_fe for _ in range(n_be)]
    pct_grid = [[0.0] * n_fe for _ in range(n_be)]

    # Map results to grid positions
    for r in results:
        fe_sp = round(r["fe_spread"], 4)
        be_sp = round(r["be_spread"], 4)

        # Find grid indices
        fe_idx = None
        for i, fs in enumerate(fe_spreads):
            if abs(fe_sp - fs) < 0.001:
                fe_idx = i
                break
        be_idx = None
        for j, bs in enumerate(be_spreads):
            if abs(be_sp - bs) < 0.001:
                be_idx = j
                break

        if fe_idx is not None and be_idx is not None:
            vss_grid[be_idx][fe_idx] = r["vss"]
            pct_grid[be_idx][fe_idx] = r["pct_vss"]

    # --- Create figure ------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    # Heatmap 1: VSS in dollars
    im1 = ax1.imshow(vss_grid, aspect="auto", origin="lower",
                     cmap="YlOrRd", interpolation="nearest")
    ax1.set_xticks(range(n_fe))
    ax1.set_xticklabels([f"{s:.2f}" for s in fe_spreads], fontsize=9)
    ax1.set_yticks(range(n_be))
    ax1.set_yticklabels([f"{s:.2f}" for s in be_spreads], fontsize=9)
    ax1.set_xlabel("FE Yield Spread (hi - lo)", fontsize=11)
    ax1.set_ylabel("BE Yield Spread (hi - lo)", fontsize=11)
    ax1.set_title("VSS ($) by Yield Uncertainty\n"
                  "Darker = more value from stochastic planning",
                  fontsize=12, fontweight="bold")

    # Add value labels
    for i in range(n_be):
        for j in range(n_fe):
            val = vss_grid[i][j]
            color = "white" if val > max(max(row) for row in vss_grid) * 0.6 else "black"
            ax1.text(j, i, f"${val:.0f}", ha="center", va="center",
                     fontsize=8, color=color, fontweight="bold")

    cbar1 = fig.colorbar(im1, ax=ax1, shrink=0.8)
    cbar1.set_label("VSS ($)", fontsize=10)

    # Heatmap 2: %VSS
    im2 = ax2.imshow(pct_grid, aspect="auto", origin="lower",
                     cmap="YlOrRd", interpolation="nearest")
    ax2.set_xticks(range(n_fe))
    ax2.set_xticklabels([f"{s:.2f}" for s in fe_spreads], fontsize=9)
    ax2.set_yticks(range(n_be))
    ax2.set_yticklabels([f"{s:.2f}" for s in be_spreads], fontsize=9)
    ax2.set_xlabel("FE Yield Spread (hi - lo)", fontsize=11)
    ax2.set_ylabel("BE Yield Spread (hi - lo)", fontsize=11)
    ax2.set_title("%VSS by Yield Uncertainty\n"
                  "Darker = larger fraction of profit at risk",
                  fontsize=12, fontweight="bold")

    for i in range(n_be):
        for j in range(n_fe):
            val = pct_grid[i][j]
            color = "white" if val > max(max(row) for row in pct_grid) * 0.6 else "black"
            ax2.text(j, i, f"{val:.1f}%", ha="center", va="center",
                     fontsize=8, color=color, fontweight="bold")

    cbar2 = fig.colorbar(im2, ax=ax2, shrink=0.8)
    cbar2.set_label("%VSS", fontsize=10)

    # Mark the Step 1 baseline cell
    step1_fe_sp = FrozenInstance.STEP1_FE_HI - FrozenInstance.STEP1_FE_LO  # 0.15
    step1_be_sp = FrozenInstance.STEP1_BE_HI - FrozenInstance.STEP1_BE_LO  # 0.20

    for ax in [ax1, ax2]:
        for i, fs in enumerate(fe_spreads):
            for j, bs in enumerate(be_spreads):
                if abs(fs - step1_fe_sp) < 0.001 and abs(bs - step1_be_sp) < 0.001:
                    rect = plt.Rectangle((i - 0.5, j - 0.5), 1, 1,
                                         linewidth=3, edgecolor="blue",
                                         facecolor="none", linestyle="--")
                    ax.add_patch(rect)

    fig.suptitle("Step 2: How VSS Depends on Yield Uncertainty\n"
                 "(Blue dashed box = Step 1 baseline)",
                 fontsize=13, fontweight="bold", y=1.02)

    fig.tight_layout()
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [saved] {filepath}")


# ======================================================================
# 7.  MAIN
# ======================================================================

def main():
    print("=" * 60)
    print("  step2_freeze_model.py")
    print("  Lock model structure, prepare experimental framework")
    print("=" * 60)

    # --- Save the frozen manifest (documentation) ---------------------
    print("\n--- Saving frozen parameter manifest ---")
    save_frozen_manifest()

    # --- Validation: reproduce Step 1 ---------------------------------
    print("\n--- Validation: reproducing Step 1 baseline ---")
    val_result = validate_step1()

    # --- Run yield spread grid experiment -----------------------------
    print("\n--- Running yield spread grid experiment ---")
    results, fe_spreads, be_spreads = run_yield_grid()

    # --- Save outputs -------------------------------------------------
    print("\n--- Saving outputs ---")
    save_results_csv(results)
    plot_vss_heatmap(results, fe_spreads, be_spreads)

    # --- Print summary ------------------------------------------------
    print(f"\n{'='*60}")
    print(f"  STEP 2 SUMMARY")
    print(f"{'='*60}")
    print(f"  Frozen manifest:  step2_frozen_manifest.json")
    print(f"  Experiment CSV:   step2_experiment_results.csv")
    print(f"  VSS heatmap:      step2_vss_heatmap.png")
    print(f"\n  Key findings from grid experiment:")

    # Find min/max VSS
    vss_vals = [r["vss"] for r in results]
    min_r = min(results, key=lambda r: r["vss"])
    max_r = max(results, key=lambda r: r["vss"])

    print(f"    Minimum VSS: ${min_r['vss']:.2f} at "
          f"FE_spread={min_r['fe_spread']:.2f}, "
          f"BE_spread={min_r['be_spread']:.2f}")
    print(f"    Maximum VSS: ${max_r['vss']:.2f} at "
          f"FE_spread={max_r['fe_spread']:.2f}, "
          f"BE_spread={max_r['be_spread']:.2f}")
    print(f"    Range: ${min(vss_vals):.2f} - ${max(vss_vals):.2f}")

    # Step 1 baseline for reference
    step1_r = [r for r in results
               if abs(r["fe_spread"] - 0.15) < 0.01
               and abs(r["be_spread"] - 0.20) < 0.01]
    if step1_r:
        print(f"    Step 1 baseline (FE=0.15, BE=0.20): "
              f"VSS=${step1_r[0]['vss']:.2f}")

    print(f"\n  The frozen model is ready for Step 3 experiments.")
    print(f"  Use FrozenInstance + run_experiment() to run any yield scenario.")
    print()


if __name__ == "__main__":
    main()
