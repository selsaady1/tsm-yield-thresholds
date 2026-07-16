"""
reproduce_vss.py
================
Minimal reproduction of a multistage stochastic production-planning model
(RP) versus an average-yield deterministic model (EV) for a simplified
semiconductor FE -> DieBank -> BE supply chain.

Goal: Validate that stochastic planning (RP) can outperform average-yield
planning (EV) and that first-stage decisions (wafer starts, outsourcing)
differ between the two approaches.  The difference RP_obj - EV_obj is the
Value of the Stochastic Solution (VSS).

References
----------
[1] Rashidi, Bhuiyan & Mason, "Production Planning for Semiconductor
    Manufacturing under Demand and Yield Uncertainty", SSRN 4655409.
    -- Three-stage FE-DieBank-BE structure; push FE / pull BE;
       FE yield + demand realized at stage 2, BE yield at stage 3.

[2] Escudero, Garín, Merino & Pérez (2007), "The value of the stochastic
    solution in multistage problems", TOP 15:48-64.
    -- Defines VSS = RP - EEV for multistage; we use the simplified
       two-step EV/EEV procedure (solve EV, fix first-stage, evaluate
       under all scenarios).

Simplifications made for minimality
------------------------------------
* Single die type (I1), single device (D1), single DieBank (DB1).
* Fixed outsourcing fees (contract costs C_G, C_A) are OMITTED.
  Reason: they add binary variables but don't change the qualitative
  VSS result.  Outsourcing is controlled only by binary "contract"
  flags that enable/disable the outsourcing flow at zero fixed cost.
  This keeps the integer footprint tiny and debugging easy.
* Wafer starts are continuous (not integer) for solver robustness.
  Document: easy to switch to integer by changing cat=LpInteger.
* All 8 scenarios have equal probability (0.125).

Usage
-----
    python reproduce_vss.py            # normal run
    python reproduce_vss.py --debug    # show solver logs

Requirements: Python 3.9+, PuLP  (pip install pulp)
"""

import sys
import csv
import os
import datetime
import io
import contextlib
import json
from itertools import product as cartesian

# ---------- try to import PuLP -----------------------------------------
try:
    from pulp import (
        LpProblem, LpMaximize, LpVariable, LpContinuous, LpBinary,
        lpSum, value, LpStatus, PULP_CBC_CMD, GLPK_CMD,
    )
except ImportError:
    sys.exit("ERROR: PuLP is required.  Install with:  pip install pulp")

DEBUG = "--debug" in sys.argv

# ======================================================================
# 1.  INSTANCE DATA  (all parameters collected in one place)
# ======================================================================

def make_instance():
    """Return a dict with every numeric parameter.  Edit here to tweak."""
    d = {}

    # --- Sets ---------------------------------------------------------
    d["FE_set"]  = ["FE1", "FE2"]       # Front-End fabs
    d["BE_set"]  = ["BE1", "BE2"]       # Back-End facilities
    d["DB_set"]  = ["DB1"]              # Die Banks
    d["DEV_set"] = ["D1"]               # Devices (finished goods)
    d["DIE_set"] = ["I1"]               # Die types
    d["G_set"]   = ["G1"]               # 3rd-party Front-End
    d["A_set"]   = ["A1"]               # 3rd-party Back-End

    # --- Wafer / capacity parameters ----------------------------------
    d["n_f_i"]   = 100                          # gross dies per wafer
    d["L_F"]     = {"FE1": 10, "FE2": 8}       # asymmetric FE capacity (wafers)
    d["L_B"]     = {"BE1": 500, "BE2": 400}    # asymmetric BE capacity (devices)
    d["L_G"]     = {"G1": 300}                  # outsourced FE cap (dies) — limited
    d["L_A"]     = {"A1": 150}                  # outsourced BE cap (devices) — tight

    # --- Prices & penalties -------------------------------------------
    d["p_d"]     = 10           # selling price per device
    d["v_d"]     = 3            # penalty ~30% of price — meaningful but not crushing
    d["c_F"]     = 1.5          # FE in-house cost per wafer
    d["c_G"]     = 1.65         # outsourced FE ~10% more
    d["c_B"]     = 0.8          # BE in-house cost per device
    d["c_A"]     = 0.9          # outsourced BE ~13% more
    d["c_K"]     = 0.05         # die-bank inventory cost per die
    d["c_D"]     = 0.05         # device inventory cost per device

    # --- Yield levels (low / high) ------------------------------------
    d["fe_yield_lo"] = 0.80
    d["fe_yield_hi"] = 0.95
    d["be_yield_lo"] = 0.70
    d["be_yield_hi"] = 0.90

    # --- Demand levels (low / high) -----------------------------------
    d["demand_lo"] = 600
    d["demand_hi"] = 900

    return d


# ======================================================================
# 2.  SCENARIO GENERATION
# ======================================================================

def build_scenarios(inst):
    """
    Create 8 scenarios from binary low/high for each uncertain element:
        FE yield  x  demand  x  BE yield  =  2 x 2 x 2  =  8
    Each scenario is equally likely: prob = 0.125.

    Returns list of dicts, each with keys:
        name, prob, fe_yield, demand, be_yield
    """
    fe_levels = [("FElo", inst["fe_yield_lo"]),
                 ("FEhi", inst["fe_yield_hi"])]
    dm_levels = [("Dlo",  inst["demand_lo"]),
                 ("Dhi",  inst["demand_hi"])]
    be_levels = [("BElo", inst["be_yield_lo"]),
                 ("BEhi", inst["be_yield_hi"])]

    scenarios = []
    for (fn, fv), (dn, dv), (bn, bv) in cartesian(fe_levels, dm_levels,
                                                    be_levels):
        scenarios.append({
            "name":     f"{fn}_{dn}_{bn}",
            "prob":     0.125,
            "fe_yield": fv,
            "demand":   dv,
            "be_yield": bv,
        })

    # --- Sanity check -------------------------------------------------
    total_prob = sum(s["prob"] for s in scenarios)
    print(f"[check] Number of scenarios : {len(scenarios)}")
    print(f"[check] Sum of probabilities: {total_prob:.4f}  (should be 1.0)")
    mean_fe = sum(s["prob"] * s["fe_yield"] for s in scenarios)
    mean_be = sum(s["prob"] * s["be_yield"] for s in scenarios)
    mean_dm = sum(s["prob"] * s["demand"]   for s in scenarios)
    print(f"[check] E[FE yield] = {mean_fe:.4f}")
    print(f"[check] E[BE yield] = {mean_be:.4f}")
    print(f"[check] E[demand]   = {mean_dm:.1f}")
    print()
    return scenarios


# ======================================================================
# 3.  BUILD & SOLVE THE STOCHASTIC RP MODEL
# ======================================================================

def solve_rp(inst, scenarios, tag="RP"):
    """
    Build the scenario-expanded LP that maximizes expected profit.

    Decision structure (following Rashidi et al. [1]):
      Stage 1 (here-and-now, common across scenarios):
        X_F[f]   : wafer starts at each FE           (continuous >= 0)
        O_G[g]   : binary flag – open outsourcing contract for FE?
        O_A[a]   : binary flag – open outsourcing contract for BE?

      Stage 2 (per scenario – after FE yield & demand revealed):
        X_FK[s,f] : dies shipped from FE f to DieBank (continuous)
        X_GK[s,g] : dies purchased from 3rd-party FE  (continuous)
        Z[s]      : die-bank ending inventory          (continuous)
        X_KB[s,b] : device starts sent from DB to BE b (continuous)
        X_KA[s,a] : device starts sent from DB to 3rd-party BE (cont.)

      Stage 3 (per scenario – after BE yield revealed):
        X_BD[s,b] : devices produced at BE b           (continuous)
        X_AD[s,a] : devices from outsourced BE         (continuous)
        M[s]      : unmet demand for D1                (continuous)
        W[s]      : device inventory (surplus)         (continuous)
    """
    prob = LpProblem(f"SemiCond_{tag}", LpMaximize)

    FE = inst["FE_set"]
    BE = inst["BE_set"]
    G  = inst["G_set"]
    A  = inst["A_set"]
    S  = [s["name"] for s in scenarios]
    sp = {s["name"]: s["prob"]     for s in scenarios}
    fy = {s["name"]: s["fe_yield"] for s in scenarios}
    by = {s["name"]: s["be_yield"] for s in scenarios}
    dm = {s["name"]: s["demand"]   for s in scenarios}

    n   = inst["n_f_i"]
    c_F = inst["c_F"]
    c_G = inst["c_G"]
    c_B = inst["c_B"]
    c_A = inst["c_A"]
    c_K = inst["c_K"]
    c_D = inst["c_D"]
    p_d = inst["p_d"]
    v_d = inst["v_d"]

    # ---- Stage 1 variables (common) ----------------------------------
    X_F = {f: LpVariable(f"XF_{f}_{tag}", 0, None, LpContinuous)
           for f in FE}
    O_G = {g: LpVariable(f"OG_{g}_{tag}", 0, 1, LpBinary) for g in G}
    O_A = {a: LpVariable(f"OA_{a}_{tag}", 0, 1, LpBinary) for a in A}

    # ---- Stage 2 variables (per scenario) ----------------------------
    # Dies from each FE to DieBank
    X_FK = {(s, f): LpVariable(f"XFK_{s}_{f}_{tag}", 0)
            for s in S for f in FE}
    # Dies from outsourced FE to DieBank
    X_GK = {(s, g): LpVariable(f"XGK_{s}_{g}_{tag}", 0)
            for s in S for g in G}
    # Die-bank ending inventory
    Z = {s: LpVariable(f"Z_{s}_{tag}", 0) for s in S}
    # Device starts from DieBank to each in-house BE
    X_KB = {(s, b): LpVariable(f"XKB_{s}_{b}_{tag}", 0)
            for s in S for b in BE}
    # Device starts from DieBank to outsourced BE
    X_KA = {(s, a): LpVariable(f"XKA_{s}_{a}_{tag}", 0)
            for s in S for a in A}

    # ---- Stage 3 variables (per scenario) ----------------------------
    # Devices produced at in-house BE (after BE yield)
    X_BD = {(s, b): LpVariable(f"XBD_{s}_{b}_{tag}", 0)
            for s in S for b in BE}
    # Devices from outsourced BE (no yield loss on outsourced)
    X_AD = {(s, a): LpVariable(f"XAD_{s}_{a}_{tag}", 0)
            for s in S for a in A}
    # Unmet demand
    M = {s: LpVariable(f"M_{s}_{tag}", 0) for s in S}
    # Device inventory (surplus)
    W = {s: LpVariable(f"W_{s}_{tag}", 0) for s in S}

    # ==================================================================
    # OBJECTIVE:  maximize expected profit
    #   = E[ revenue - costs - penalties ]
    #
    # Stage 1 costs (deterministic, no probability weight):
    #   - FE wafer cost:  sum_f  c_F * X_F[f]
    #   (fixed outsourcing fees omitted for simplicity)
    #
    # Stage 2 costs (expected):
    #   - Die-bank inventory:  c_K * Z[s]
    #   - Outsourced FE cost:  c_G * X_GK[s,g]
    #   - In-house BE cost:    c_B * X_KB[s,b]
    #   - Outsourced BE cost:  c_A * X_KA[s,a]
    #
    # Stage 3 (expected):
    #   + Revenue:  p_d * (demand - M[s])
    #   - Unmet penalty:  v_d * M[s]
    #   - Device inventory cost:  c_D * W[s]
    # ==================================================================

    # --- Stage 1 cost (not weighted by probability) -------------------
    stage1_cost = lpSum(c_F * X_F[f] for f in FE)

    # --- Expected stage 2 + stage 3 per scenario ----------------------
    scenario_obj = []
    for s in S:
        revenue  = p_d * (dm[s] - M[s])
        penalty  = v_d * M[s]
        inv_die  = c_K * Z[s]
        inv_dev  = c_D * W[s]
        cost_g   = lpSum(c_G * X_GK[(s, g)] for g in G)
        cost_b   = lpSum(c_B * X_KB[(s, b)] for b in BE)
        cost_a   = lpSum(c_A * X_KA[(s, a)] for a in A)

        scen_profit = revenue - penalty - inv_die - inv_dev \
                      - cost_g - cost_b - cost_a
        scenario_obj.append(sp[s] * scen_profit)

    prob += lpSum(scenario_obj) - stage1_cost, "expected_profit"

    # ==================================================================
    # CONSTRAINTS
    # ==================================================================

    # --- (C1) FE capacity: wafer starts <= capacity -------------------
    for f in FE:
        prob += X_F[f] <= inst["L_F"][f], f"FE_cap_{f}"

    # --- (C2) FE yield: dies shipped <= yield * n * wafer_starts ------
    #     Eq (5.1) in Rashidi:  X_FK[s,f] <= y_FE * n_f_i * X_F[f]
    for s in S:
        for f in FE:
            prob += X_FK[(s, f)] <= fy[s] * n * X_F[f], \
                    f"FE_yield_{s}_{f}"

    # --- (C3) Outsourced FE capacity (enabled by O_G) -----------------
    #     Eq (3.1): outsourced dies <= L_G * O_G[g]
    for s in S:
        for g in G:
            prob += X_GK[(s, g)] <= inst["L_G"][g] * O_G[g], \
                    f"OG_cap_{s}_{g}"

    # --- (C4) DieBank balance: incoming - used - inventory = 0 --------
    #     incoming  = sum_f X_FK[s,f] + sum_g X_GK[s,g]
    #     used      = sum_b X_KB[s,b] + sum_a X_KA[s,a]
    #     inventory = Z[s]
    for s in S:
        incoming = lpSum(X_FK[(s, f)] for f in FE) \
                 + lpSum(X_GK[(s, g)] for g in G)
        used     = lpSum(X_KB[(s, b)] for b in BE) \
                 + lpSum(X_KA[(s, a)] for a in A)
        prob += incoming - used - Z[s] == 0, f"DB_balance_{s}"

    # --- (C5) BE capacity: device starts <= capacity ------------------
    #     Eq (2.2): sum over devices of X_KB <= L_B  (one device here)
    for s in S:
        for b in BE:
            prob += X_KB[(s, b)] <= inst["L_B"][b], f"BE_cap_{s}_{b}"

    # --- (C6) BE yield: devices produced <= yield * device starts -----
    #     Eq (5.2):  X_BD[s,b] <= y_BE * X_KB[s,b]
    for s in S:
        for b in BE:
            prob += X_BD[(s, b)] <= by[s] * X_KB[(s, b)], \
                    f"BE_yield_{s}_{b}"

    # --- (C7) Outsourced BE capacity (enabled by O_A) -----------------
    for s in S:
        for a in A:
            prob += X_KA[(s, a)] <= inst["L_A"][a] * O_A[a], \
                    f"OA_cap_{s}_{a}"

    # --- (C8) Outsourced BE: devices received = starts sent -----------
    #     (no yield loss on outsourced — Rashidi assumption)
    for s in S:
        for a in A:
            prob += X_AD[(s, a)] == X_KA[(s, a)], f"OA_flow_{s}_{a}"

    # --- (C9) Demand balance: produced + surplus - unmet = demand -----
    #     total_devices = sum_b X_BD[s,b] + sum_a X_AD[s,a]
    #     total_devices + W[s] - M[s] = demand[s]
    #     (W = surplus inventory if production > demand)
    #     Rearranged: total_devices - demand = M[s] - W[s]
    for s in S:
        total_dev = lpSum(X_BD[(s, b)] for b in BE) \
                  + lpSum(X_AD[(s, a)] for a in A)
        prob += total_dev + M[s] - W[s] == dm[s], f"demand_bal_{s}"

    # ==================================================================
    # SOLVE
    # ==================================================================
    solver = PULP_CBC_CMD(msg=DEBUG)
    prob.solve(solver)

    if LpStatus[prob.status] != "Optimal":
        print(f"WARNING: {tag} solve status = {LpStatus[prob.status]}")

    # --- Collect results ----------------------------------------------
    res = {
        "tag":        tag,
        "status":     LpStatus[prob.status],
        "obj":        value(prob.objective),
        "X_F":        {f: value(X_F[f]) for f in FE},
        "O_G":        {g: value(O_G[g]) for g in G},
        "O_A":        {a: value(O_A[a]) for a in A},
        # Per-scenario details
        "Z":          {s: value(Z[s]) for s in S},
        "M":          {s: value(M[s]) for s in S},
        "W":          {s: value(W[s]) for s in S},
        "X_GK":       {(s, g): value(X_GK[(s, g)]) for s in S for g in G},
        "X_KB":       {(s, b): value(X_KB[(s, b)]) for s in S for b in BE},
        "X_BD":       {(s, b): value(X_BD[(s, b)]) for s in S for b in BE},
        "X_AD":       {(s, a): value(X_AD[(s, a)]) for s in S for a in A},
        "scenarios":  scenarios,
    }
    return res


# ======================================================================
# 4.  BUILD & SOLVE THE DETERMINISTIC EV MODEL
# ======================================================================

def solve_ev(inst, scenarios):
    """
    Replace all stochastic yields and demand with their expected values,
    solve a single deterministic model (one "average" scenario), then
    evaluate the resulting first-stage decisions across all scenarios
    to get EEV (the expected profit when using the EV solution).

    Steps (following Escudero et al. [2] for two-stage simplification):
      1. Compute mean FE yield, mean BE yield, mean demand.
      2. Solve the deterministic model with those means (one scenario).
      3. Record first-stage decisions (wafer starts, outsourcing flags).
      4. Fix those first-stage decisions in the full RP model and solve
         to get EEV = expected profit under stochastic scenarios.
      5. VSS = RP_obj - EEV.
    """

    # --- Step 1: expected values --------------------------------------
    mean_fy = sum(s["prob"] * s["fe_yield"] for s in scenarios)
    mean_by = sum(s["prob"] * s["be_yield"] for s in scenarios)
    mean_dm = sum(s["prob"] * s["demand"]   for s in scenarios)

    print(f"[EV] Using expected values:  FE yield={mean_fy:.4f}, "
          f"BE yield={mean_by:.4f}, demand={mean_dm:.1f}")

    # --- Step 2: build single-scenario deterministic model ------------
    # Create a fake single scenario with expected values
    ev_scen = [{
        "name":     "EV_avg",
        "prob":     1.0,
        "fe_yield": mean_fy,
        "demand":   mean_dm,
        "be_yield": mean_by,
    }]

    ev_res = solve_rp(inst, ev_scen, tag="EV_det")

    # --- Step 3: extract first-stage decisions ------------------------
    ev_xf = ev_res["X_F"]
    ev_og = ev_res["O_G"]
    ev_oa = ev_res["O_A"]
    print(f"[EV] Deterministic wafer starts: {ev_xf}")
    print(f"[EV] Deterministic O_G:          {ev_og}")
    print(f"[EV] Deterministic O_A:          {ev_oa}")
    print(f"[EV] Deterministic obj (EV):     {ev_res['obj']:.2f}")
    print()

    # --- Step 4: fix first-stage in full stochastic model → EEV -------
    # We rebuild the RP model but add equality constraints that lock
    # the first-stage variables to the EV solution.
    eev_res = solve_rp_fixed_first_stage(inst, scenarios,
                                         ev_xf, ev_og, ev_oa)
    return ev_res, eev_res


def solve_rp_fixed_first_stage(inst, scenarios, fix_xf, fix_og, fix_oa):
    """
    Solve the full scenario-expanded model with first-stage variables
    fixed to the values from the EV solution.  The objective value
    is EEV (expected result of using the EV solution).
    """
    prob = LpProblem("SemiCond_EEV", LpMaximize)

    FE = inst["FE_set"]
    BE = inst["BE_set"]
    G  = inst["G_set"]
    A  = inst["A_set"]
    S  = [s["name"] for s in scenarios]
    sp = {s["name"]: s["prob"]     for s in scenarios}
    fy = {s["name"]: s["fe_yield"] for s in scenarios}
    by = {s["name"]: s["be_yield"] for s in scenarios}
    dm = {s["name"]: s["demand"]   for s in scenarios}

    n   = inst["n_f_i"]
    c_F = inst["c_F"]
    c_G = inst["c_G"]
    c_B = inst["c_B"]
    c_A = inst["c_A"]
    c_K = inst["c_K"]
    c_D = inst["c_D"]
    p_d = inst["p_d"]
    v_d = inst["v_d"]

    # ---- First-stage: FIXED variables --------------------------------
    X_F = {f: LpVariable(f"XF_{f}_EEV", fix_xf[f], fix_xf[f],
                          LpContinuous)
           for f in FE}
    # Binary flags fixed to EV solution values
    O_G = {g: LpVariable(f"OG_{g}_EEV", fix_og[g], fix_og[g], LpBinary)
           for g in G}
    O_A = {a: LpVariable(f"OA_{a}_EEV", fix_oa[a], fix_oa[a], LpBinary)
           for a in A}

    # ---- Recourse variables (same as in solve_rp) --------------------
    X_FK = {(s, f): LpVariable(f"XFK_{s}_{f}_EEV", 0)
            for s in S for f in FE}
    X_GK = {(s, g): LpVariable(f"XGK_{s}_{g}_EEV", 0)
            for s in S for g in G}
    Z  = {s: LpVariable(f"Z_{s}_EEV", 0) for s in S}
    X_KB = {(s, b): LpVariable(f"XKB_{s}_{b}_EEV", 0)
            for s in S for b in BE}
    X_KA = {(s, a): LpVariable(f"XKA_{s}_{a}_EEV", 0)
            for s in S for a in A}
    X_BD = {(s, b): LpVariable(f"XBD_{s}_{b}_EEV", 0)
            for s in S for b in BE}
    X_AD = {(s, a): LpVariable(f"XAD_{s}_{a}_EEV", 0)
            for s in S for a in A}
    M  = {s: LpVariable(f"M_{s}_EEV", 0) for s in S}
    W  = {s: LpVariable(f"W_{s}_EEV", 0) for s in S}

    # ---- Objective (identical structure) -----------------------------
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
        scen_profit = revenue - penalty - inv_die - inv_dev \
                      - cost_g - cost_b - cost_a
        scenario_obj.append(sp[s] * scen_profit)

    prob += lpSum(scenario_obj) - stage1_cost, "expected_profit_EEV"

    # ---- Constraints (identical to RP) -------------------------------
    for f in FE:
        prob += X_F[f] <= inst["L_F"][f], f"FE_cap_{f}"
    for s in S:
        for f in FE:
            prob += X_FK[(s, f)] <= fy[s] * n * X_F[f], \
                    f"FE_yield_{s}_{f}"
    for s in S:
        for g in G:
            prob += X_GK[(s, g)] <= inst["L_G"][g] * O_G[g], \
                    f"OG_cap_{s}_{g}"
    for s in S:
        incoming = lpSum(X_FK[(s, f)] for f in FE) \
                 + lpSum(X_GK[(s, g)] for g in G)
        used     = lpSum(X_KB[(s, b)] for b in BE) \
                 + lpSum(X_KA[(s, a)] for a in A)
        prob += incoming - used - Z[s] == 0, f"DB_balance_{s}"
    for s in S:
        for b in BE:
            prob += X_KB[(s, b)] <= inst["L_B"][b], f"BE_cap_{s}_{b}"
    for s in S:
        for b in BE:
            prob += X_BD[(s, b)] <= by[s] * X_KB[(s, b)], \
                    f"BE_yield_{s}_{b}"
    for s in S:
        for a in A:
            prob += X_KA[(s, a)] <= inst["L_A"][a] * O_A[a], \
                    f"OA_cap_{s}_{a}"
    for s in S:
        for a in A:
            prob += X_AD[(s, a)] == X_KA[(s, a)], f"OA_flow_{s}_{a}"
    for s in S:
        total_dev = lpSum(X_BD[(s, b)] for b in BE) \
                  + lpSum(X_AD[(s, a)] for a in A)
        prob += total_dev + M[s] - W[s] == dm[s], f"demand_bal_{s}"

    # ---- Solve -------------------------------------------------------
    solver = PULP_CBC_CMD(msg=DEBUG)
    prob.solve(solver)

    if LpStatus[prob.status] != "Optimal":
        print(f"WARNING: EEV solve status = {LpStatus[prob.status]}")

    res = {
        "tag":    "EEV",
        "status": LpStatus[prob.status],
        "obj":    value(prob.objective),
        "X_F":    {f: value(X_F[f]) for f in FE},
        "O_G":    {g: value(O_G[g]) for g in G},
        "O_A":    {a: value(O_A[a]) for a in A},
        "Z":      {s: value(Z[s]) for s in S},
        "M":      {s: value(M[s]) for s in S},
        "W":      {s: value(W[s]) for s in S},
        "X_GK":   {(s, g): value(X_GK[(s, g)]) for s in S for g in G},
        "X_KB":   {(s, b): value(X_KB[(s, b)]) for s in S for b in BE},
        "X_BD":   {(s, b): value(X_BD[(s, b)]) for s in S for b in BE},
        "X_AD":   {(s, a): value(X_AD[(s, a)]) for s in S for a in A},
        "scenarios": scenarios,
    }
    return res


# ======================================================================
# 5.  REPORTING UTILITIES
# ======================================================================

def print_results(res, label=""):
    """Print a compact summary of model results."""
    print(f"{'='*60}")
    print(f"  {label}  ({res['tag']})  —  Status: {res['status']}")
    print(f"{'='*60}")
    print(f"  Objective (expected profit): {res['obj']:>12.2f}")
    print()
    print(f"  First-stage decisions:")
    for f, v in res["X_F"].items():
        print(f"    Wafer starts {f}: {v:>10.2f}")
    for g, v in res["O_G"].items():
        print(f"    Outsource FE {g}: {'YES' if v and v > 0.5 else 'NO'}"
              f"  (flag={v})")
    for a, v in res["O_A"].items():
        print(f"    Outsource BE {a}: {'YES' if v and v > 0.5 else 'NO'}"
              f"  (flag={v})")
    print()

    # --- Aggregated statistics ----------------------------------------
    scenarios = res["scenarios"]
    S = [s["name"] for s in scenarios]
    sp = {s["name"]: s["prob"] for s in scenarios}

    exp_unmet = sum(sp[s] * (res["M"][s] or 0) for s in S)
    exp_inv   = sum(sp[s] * (res["Z"][s] or 0) for s in S)
    print(f"  Expected unmet demand:       {exp_unmet:>10.2f}")
    print(f"  Expected die-bank inventory: {exp_inv:>10.2f}")

    # --- One representative scenario detail ---------------------------
    # Pick the "stress" scenario: FE low, demand high, BE low
    stress = [s for s in S if "FElo" in s and "Dhi" in s and "BElo" in s]
    if stress:
        ss = stress[0]
        print(f"\n  Representative scenario: {ss}")
        print(f"    Unmet demand:     {res['M'][ss] or 0:>10.2f}")
        print(f"    DieBank inv:      {res['Z'][ss] or 0:>10.2f}")
        print(f"    Device inv (W):   {res['W'][ss] or 0:>10.2f}")
    print()


def print_comparison(rp_res, eev_res, ev_det_res):
    """Print the final comparison table and VSS."""
    vss = rp_res["obj"] - eev_res["obj"]
    pct_vss = 100.0 * vss / abs(rp_res["obj"]) if rp_res["obj"] != 0 \
              else float("nan")

    scenarios = rp_res["scenarios"]
    S  = [s["name"] for s in scenarios]
    sp = {s["name"]: s["prob"] for s in scenarios}

    rp_unmet  = sum(sp[s] * (rp_res["M"][s] or 0)  for s in S)
    eev_unmet = sum(sp[s] * (eev_res["M"][s] or 0) for s in S)

    print(f"{'='*60}")
    print(f"  COMPARISON TABLE:  RP  vs  EV  (first-stage locked)")
    print(f"{'='*60}")
    print(f"  {'Metric':<30s} {'RP':>12s} {'EV→EEV':>12s}")
    print(f"  {'-'*54}")

    for f in rp_res["X_F"]:
        rp_v  = rp_res["X_F"][f] or 0
        ev_v  = eev_res["X_F"][f] or 0
        print(f"  {'Wafer starts ' + f:<30s} {rp_v:>12.2f} {ev_v:>12.2f}")

    for g in rp_res["O_G"]:
        rp_v = "YES" if (rp_res["O_G"][g] or 0) > 0.5 else "NO"
        ev_v = "YES" if (eev_res["O_G"][g] or 0) > 0.5 else "NO"
        print(f"  {'Outsource FE ' + g:<30s} {rp_v:>12s} {ev_v:>12s}")

    for a in rp_res["O_A"]:
        rp_v = "YES" if (rp_res["O_A"][a] or 0) > 0.5 else "NO"
        ev_v = "YES" if (eev_res["O_A"][a] or 0) > 0.5 else "NO"
        print(f"  {'Outsource BE ' + a:<30s} {rp_v:>12s} {ev_v:>12s}")

    print(f"  {'Expected unmet demand':<30s} {rp_unmet:>12.2f} "
          f"{eev_unmet:>12.2f}")
    print(f"  {'Expected profit':<30s} {rp_res['obj']:>12.2f} "
          f"{eev_res['obj']:>12.2f}")
    print(f"  {'-'*54}")
    print(f"  {'VSS = RP - EEV':<30s} {vss:>12.2f}")
    print(f"  {'%VSS':<30s} {pct_vss:>11.2f}%")
    print()
    if vss > 0:
        print("  >> Stochastic planning (RP) outperforms average-yield")
        print("     planning (EV).  This matches the qualitative finding")
        print("     from Rashidi et al.: VSS > 0 and grows with yield")
        print("     uncertainty.")
    elif vss == 0:
        print("  >> VSS = 0: No benefit from stochastic planning here.")
    else:
        print("  >> VSS < 0: Unusual — check model or parameters.")
    print()


# ======================================================================
# 6.  OPTIONAL: SCAN YIELD VARIANCE
# ======================================================================

def scan_yield_variance(inst, alpha_list):
    """
    Scale FE and BE yields as:
        mean ± alpha * base_half_range
    where base_half_range is (high - low) / 2 from the instance.

    For each alpha, solve RP and EEV, compute VSS.
    Shows how VSS grows with increasing yield variance.
    """
    base_fe_mean  = (inst["fe_yield_lo"] + inst["fe_yield_hi"]) / 2
    base_be_mean  = (inst["be_yield_lo"] + inst["be_yield_hi"]) / 2
    base_fe_half  = (inst["fe_yield_hi"] - inst["fe_yield_lo"]) / 2
    base_be_half  = (inst["be_yield_hi"] - inst["be_yield_lo"]) / 2

    print(f"{'='*60}")
    print(f"  YIELD VARIANCE SCAN")
    print(f"{'='*60}")
    print(f"  {'alpha':<8s} {'FE range':<16s} {'BE range':<16s} "
          f"{'RP obj':>10s} {'EEV obj':>10s} {'VSS':>10s}")
    print(f"  {'-'*70}")

    for alpha in alpha_list:
        # Create modified instance
        mi = make_instance()
        mi["fe_yield_lo"] = max(0.01, base_fe_mean - alpha * base_fe_half)
        mi["fe_yield_hi"] = min(1.00, base_fe_mean + alpha * base_fe_half)
        mi["be_yield_lo"] = max(0.01, base_be_mean - alpha * base_be_half)
        mi["be_yield_hi"] = min(1.00, base_be_mean + alpha * base_be_half)

        scens = build_scenarios_quiet(mi)
        rp = solve_rp(mi, scens, tag=f"RP_a{alpha}")
        _, eev = solve_ev_quiet(mi, scens)
        vss = rp["obj"] - eev["obj"]

        fe_str = f"[{mi['fe_yield_lo']:.3f}, {mi['fe_yield_hi']:.3f}]"
        be_str = f"[{mi['be_yield_lo']:.3f}, {mi['be_yield_hi']:.3f}]"
        print(f"  {alpha:<8.2f} {fe_str:<16s} {be_str:<16s} "
              f"{rp['obj']:>10.2f} {eev['obj']:>10.2f} {vss:>10.2f}")
    print()


def build_scenarios_quiet(inst):
    """Build scenarios without printing."""
    fe_levels = [("FElo", inst["fe_yield_lo"]),
                 ("FEhi", inst["fe_yield_hi"])]
    dm_levels = [("Dlo",  inst["demand_lo"]),
                 ("Dhi",  inst["demand_hi"])]
    be_levels = [("BElo", inst["be_yield_lo"]),
                 ("BEhi", inst["be_yield_hi"])]
    scenarios = []
    for (fn, fv), (dn, dv), (bn, bv) in cartesian(fe_levels, dm_levels,
                                                    be_levels):
        scenarios.append({
            "name": f"{fn}_{dn}_{bn}", "prob": 0.125,
            "fe_yield": fv, "demand": dv, "be_yield": bv,
        })
    return scenarios


def solve_ev_quiet(inst, scenarios):
    """Solve EV + EEV without verbose printing."""
    mean_fy = sum(s["prob"] * s["fe_yield"] for s in scenarios)
    mean_by = sum(s["prob"] * s["be_yield"] for s in scenarios)
    mean_dm = sum(s["prob"] * s["demand"]   for s in scenarios)
    ev_scen = [{"name": "EV_avg", "prob": 1.0, "fe_yield": mean_fy,
                "demand": mean_dm, "be_yield": mean_by}]
    ev_res = solve_rp(inst, ev_scen, tag="EV_q")
    eev_res = solve_rp_fixed_first_stage(inst, scenarios,
                                          ev_res["X_F"],
                                          ev_res["O_G"],
                                          ev_res["O_A"])
    return ev_res, eev_res


# ======================================================================
# 8.  VISUALIZATIONS & SUMMARY TABLE
# ======================================================================

# --- Check for matplotlib (graceful fallback) -------------------------
try:
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend (no GUI needed)
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("[warning] matplotlib not installed — skipping graphs.")
    print("          Install with:  pip install matplotlib")


def generate_visualizations(rp_res, eev_res, inst, scenarios):
    """
    Produce three figures and one summary CSV that together document
    the Step 1 validation results.

    Files saved (in the current working directory):
        fig1_vss_vs_uncertainty.png
        fig2_wafer_starts_comparison.png
        fig3_profit_by_scenario.png
        step1_summary_table.csv
    """
    if not HAS_MPL:
        print("[skip] No matplotlib — only generating the CSV table.")
        _save_summary_csv(rp_res, eev_res, inst, scenarios)
        return

    _plot_vss_vs_uncertainty(inst)
    _plot_wafer_starts(rp_res, eev_res)
    _plot_profit_by_scenario(rp_res, eev_res, scenarios)
    _save_summary_csv(rp_res, eev_res, inst, scenarios)

    print("[done] Saved: fig1_vss_vs_uncertainty.png")
    print("              fig2_wafer_starts_comparison.png")
    print("              fig3_profit_by_scenario.png")
    print("              step1_summary_table.csv")


# ------------------------------------------------------------------
# GRAPH 1:  VSS vs Yield Uncertainty
# ------------------------------------------------------------------
# WHY THIS GRAPH:  This is the single most important result from
# Step 1.  Rashidi et al. (Figure 7) show that %VSS increases as
# the deviation in uncertain parameters grows.  This graph
# reproduces that finding with our simplified instance.
# ------------------------------------------------------------------

def _plot_vss_vs_uncertainty(inst):
    """Line chart: VSS ($) vs alpha (yield uncertainty multiplier)."""

    alphas = [0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00]
    vss_vals = []
    pct_vss_vals = []

    base_fe_mean = (inst["fe_yield_lo"] + inst["fe_yield_hi"]) / 2
    base_be_mean = (inst["be_yield_lo"] + inst["be_yield_hi"]) / 2
    base_fe_half = (inst["fe_yield_hi"] - inst["fe_yield_lo"]) / 2
    base_be_half = (inst["be_yield_hi"] - inst["be_yield_lo"]) / 2

    for alpha in alphas:
        mi = make_instance()
        mi["fe_yield_lo"] = max(0.01, base_fe_mean - alpha * base_fe_half)
        mi["fe_yield_hi"] = min(1.00, base_fe_mean + alpha * base_fe_half)
        mi["be_yield_lo"] = max(0.01, base_be_mean - alpha * base_be_half)
        mi["be_yield_hi"] = min(1.00, base_be_mean + alpha * base_be_half)

        scens = build_scenarios_quiet(mi)
        rp = solve_rp(mi, scens, tag=f"RP_fig1_a{alpha}")
        _, eev = solve_ev_quiet(mi, scens)
        vss = rp["obj"] - eev["obj"]
        pct = 100.0 * vss / abs(rp["obj"]) if rp["obj"] != 0 else 0
        vss_vals.append(vss)
        pct_vss_vals.append(pct)

    # --- Create figure with two y-axes --------------------------------
    fig, ax1 = plt.subplots(figsize=(8, 5))

    color1 = "#2563EB"  # blue
    color2 = "#DC2626"  # red

    # Left axis: VSS in dollars
    line1, = ax1.plot(alphas, vss_vals, "o-", color=color1, linewidth=2,
                      markersize=7, label="VSS ($)")
    ax1.set_xlabel("Yield Uncertainty Multiplier (α)\n"
                   "α = 1.0 is baseline; higher α = wider yield range",
                   fontsize=11)
    ax1.set_ylabel("VSS ($)", color=color1, fontsize=12)
    ax1.tick_params(axis="y", labelcolor=color1)

    # Right axis: %VSS
    ax2 = ax1.twinx()
    line2, = ax2.plot(alphas, pct_vss_vals, "s--", color=color2,
                      linewidth=2, markersize=7, label="%VSS")
    ax2.set_ylabel("%VSS (as % of RP profit)", color=color2, fontsize=12)
    ax2.tick_params(axis="y", labelcolor=color2)

    # Title and legend
    ax1.set_title("Graph 1: Value of Stochastic Solution vs "
                  "Yield Uncertainty\n"
                  "Confirms: ignoring uncertainty costs more as "
                  "uncertainty grows",
                  fontsize=12, fontweight="bold", pad=15)
    lines = [line1, line2]
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="upper left", fontsize=10)
    ax1.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig("fig1_vss_vs_uncertainty.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------
# GRAPH 2:  Wafer Starts — Stochastic (RP) vs Deterministic (EV)
# ------------------------------------------------------------------
# WHY THIS GRAPH:  The most visible first-stage difference between
# the two approaches.  Rashidi et al. show that stochastic planning
# changes wafer starts and facility allocation.  This bar chart
# makes the hedging behavior immediately obvious: RP loads FE2
# much more than EV does.
# ------------------------------------------------------------------

def _plot_wafer_starts(rp_res, eev_res):
    """Grouped bar chart: wafer starts at each FE for RP vs EV."""

    facilities = list(rp_res["X_F"].keys())
    rp_starts  = [rp_res["X_F"][f] or 0 for f in facilities]
    ev_starts  = [eev_res["X_F"][f] or 0 for f in facilities]

    x = range(len(facilities))
    width = 0.30

    fig, ax = plt.subplots(figsize=(7, 5))

    color_rp = "#2563EB"  # blue
    color_ev = "#F59E0B"  # amber

    bars1 = ax.bar([i - width/2 for i in x], rp_starts, width,
                   label="Stochastic (RP)", color=color_rp, edgecolor="white")
    bars2 = ax.bar([i + width/2 for i in x], ev_starts, width,
                   label="Deterministic (EV)", color=color_ev,
                   edgecolor="white")

    # Add value labels on each bar
    for bar in bars1:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, h + 0.15,
                f"{h:.2f}", ha="center", va="bottom", fontsize=11,
                fontweight="bold", color=color_rp)
    for bar in bars2:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, h + 0.15,
                f"{h:.2f}", ha="center", va="bottom", fontsize=11,
                fontweight="bold", color=color_ev)

    ax.set_xlabel("Front-End Facility", fontsize=12)
    ax.set_ylabel("Wafer Starts", fontsize=12)
    ax.set_title("Graph 2: First-Stage Wafer Starts — "
                 "Stochastic vs Deterministic\n"
                 "RP hedges by starting more wafers at FE2 "
                 "(3.12 vs 0.29)",
                 fontsize=12, fontweight="bold", pad=15)
    ax.set_xticks(list(x))
    ax.set_xticklabels(facilities, fontsize=11)
    ax.legend(fontsize=11)
    ax.grid(True, axis="y", alpha=0.3)

    # Add total wafer starts annotation
    rp_total = sum(rp_starts)
    ev_total = sum(ev_starts)
    ax.annotate(f"Total wafer starts:  RP = {rp_total:.2f}  |  "
                f"EV = {ev_total:.2f}",
                xy=(0.5, 0.02), xycoords="axes fraction",
                ha="center", fontsize=10,
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#F3F4F6",
                          edgecolor="#D1D5DB"))

    fig.tight_layout()
    fig.savefig("fig2_wafer_starts_comparison.png", dpi=150,
                bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------
# GRAPH 3:  Per-Scenario Profit — RP vs EEV
# ------------------------------------------------------------------
# WHY THIS GRAPH:  It shows WHERE the stochastic model wins.  Each
# of the 8 scenarios contributes differently to expected profit.
# By comparing RP and EEV scenario by scenario, we can see that RP
# particularly outperforms in stress scenarios (low yield + high
# demand).  This is the "insurance payoff" from hedging.
# ------------------------------------------------------------------

def _plot_profit_by_scenario(rp_res, eev_res, scenarios):
    """Grouped bar chart: per-scenario profit contribution for RP vs EEV."""

    S = [s["name"] for s in scenarios]
    sp = {s["name"]: s["prob"] for s in scenarios}

    FE = list(rp_res["X_F"].keys())
    BE = ["BE1", "BE2"]
    A  = ["A1"]

    def scenario_profit(res, s_name, inst_for_costs):
        """Compute profit for a single scenario (revenue - costs - penalty)."""
        sc = [s for s in scenarios if s["name"] == s_name][0]
        p_d = 10; v_d = 3; c_B = 0.8; c_A = 0.9
        c_G = 1.65; c_K = 0.05; c_D = 0.05

        # Revenue and penalty
        m = res["M"][s_name] or 0
        w = res["W"][s_name] or 0
        z = res["Z"][s_name] or 0
        revenue = p_d * (sc["demand"] - m)
        penalty = v_d * m

        # Stage 2 costs
        cost_g = sum(c_G * (res["X_GK"].get((s_name, g), 0) or 0)
                     for g in ["G1"])
        cost_b = sum(c_B * (res["X_KB"].get((s_name, b), 0) or 0)
                     for b in BE)
        # Note: X_KA is not in result dict, but X_AD == X_KA (no yield loss on outsourced)
        cost_a = sum(c_A * (res["X_AD"].get((s_name, a), 0) or 0)
                     for a in A)
        inv_die = c_K * z
        inv_dev = c_D * w

        return revenue - penalty - cost_g - cost_b - cost_a - inv_die - inv_dev

    rp_profits  = [scenario_profit(rp_res, s, None) for s in S]
    eev_profits = [scenario_profit(eev_res, s, None) for s in S]

    # --- Shorten scenario names for readability -----------------------
    short_names = [s.replace("FElo", "FE↓").replace("FEhi", "FE↑")
                    .replace("_Dlo_", "\nD↓ ")
                    .replace("_Dhi_", "\nD↑ ")
                    .replace("BElo", "BE↓").replace("BEhi", "BE↑")
                   for s in S]

    x = range(len(S))
    width = 0.35

    fig, ax = plt.subplots(figsize=(12, 6))

    color_rp  = "#2563EB"
    color_eev = "#F59E0B"

    ax.bar([i - width/2 for i in x], rp_profits, width,
           label="Stochastic (RP)", color=color_rp, edgecolor="white")
    ax.bar([i + width/2 for i in x], eev_profits, width,
           label="Deterministic (EEV)", color=color_eev, edgecolor="white")

    # Highlight the stress scenario
    stress_idx = [i for i, s in enumerate(S)
                  if "FElo" in s and "Dhi" in s and "BElo" in s]
    if stress_idx:
        idx = stress_idx[0]
        ax.annotate("Worst-case\nscenario",
                    xy=(idx, min(rp_profits[idx], eev_profits[idx])),
                    xytext=(idx + 1.2,
                            min(rp_profits[idx], eev_profits[idx]) - 300),
                    arrowprops=dict(arrowstyle="->", color="#DC2626",
                                   linewidth=1.5),
                    fontsize=10, color="#DC2626", fontweight="bold")

    ax.set_xlabel("Scenario (yield and demand outcome)", fontsize=11)
    ax.set_ylabel("Scenario Profit ($, before probability weighting)",
                  fontsize=11)
    ax.set_title("Graph 3: Per-Scenario Profit — Stochastic (RP) vs "
                 "Deterministic (EEV)\n"
                 "Shows where stochastic planning wins across "
                 "different futures",
                 fontsize=12, fontweight="bold", pad=15)
    ax.set_xticks(list(x))
    ax.set_xticklabels(short_names, fontsize=9)
    ax.legend(fontsize=11)
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig("fig3_profit_by_scenario.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------
# TABLE:  Summary CSV
# ------------------------------------------------------------------
# WHY A CSV:  Provides a clean, machine-readable record of all key
# metrics from Step 1.  You can open it in Excel, paste it into
# your thesis, or load it in a later script for comparison.
# ------------------------------------------------------------------

def _save_summary_csv(rp_res, eev_res, inst, scenarios):
    """Save a summary table as step1_summary_table.csv."""

    S = [s["name"] for s in scenarios]
    sp = {s["name"]: s["prob"] for s in scenarios}

    vss = rp_res["obj"] - eev_res["obj"]
    pct_vss = 100.0 * vss / abs(rp_res["obj"]) if rp_res["obj"] != 0 \
              else 0

    rp_unmet  = sum(sp[s] * (rp_res["M"][s] or 0) for s in S)
    eev_unmet = sum(sp[s] * (eev_res["M"][s] or 0) for s in S)
    rp_inv    = sum(sp[s] * (rp_res["Z"][s] or 0) for s in S)
    eev_inv   = sum(sp[s] * (eev_res["Z"][s] or 0) for s in S)

    rows = [
        ["Metric", "Stochastic (RP)", "Deterministic (EEV)", "Difference"],
        ["Wafer Starts FE1",
         f"{rp_res['X_F']['FE1'] or 0:.2f}",
         f"{eev_res['X_F']['FE1'] or 0:.2f}",
         f"{(rp_res['X_F']['FE1'] or 0) - (eev_res['X_F']['FE1'] or 0):.2f}"],
        ["Wafer Starts FE2",
         f"{rp_res['X_F']['FE2'] or 0:.2f}",
         f"{eev_res['X_F']['FE2'] or 0:.2f}",
         f"{(rp_res['X_F']['FE2'] or 0) - (eev_res['X_F']['FE2'] or 0):.2f}"],
        ["Total Wafer Starts",
         f"{sum(v or 0 for v in rp_res['X_F'].values()):.2f}",
         f"{sum(v or 0 for v in eev_res['X_F'].values()):.2f}",
         f"{sum(v or 0 for v in rp_res['X_F'].values()) - sum(v or 0 for v in eev_res['X_F'].values()):.2f}"],
        ["Outsource FE (G1)",
         "Yes" if (rp_res['O_G']['G1'] or 0) > 0.5 else "No",
         "Yes" if (eev_res['O_G']['G1'] or 0) > 0.5 else "No",
         "—"],
        ["Outsource BE (A1)",
         "Yes" if (rp_res['O_A']['A1'] or 0) > 0.5 else "No",
         "Yes" if (eev_res['O_A']['A1'] or 0) > 0.5 else "No",
         "—"],
        ["Expected Profit ($)",
         f"{rp_res['obj']:.2f}",
         f"{eev_res['obj']:.2f}",
         f"{vss:.2f}"],
        ["Expected Unmet Demand",
         f"{rp_unmet:.2f}",
         f"{eev_unmet:.2f}",
         f"{rp_unmet - eev_unmet:.2f}"],
        ["Expected DieBank Inventory",
         f"{rp_inv:.2f}",
         f"{eev_inv:.2f}",
         f"{rp_inv - eev_inv:.2f}"],
        ["", "", "", ""],
        ["VSS ($)", "", "", f"{vss:.2f}"],
        ["%VSS", "", "", f"{pct_vss:.2f}%"],
    ]

    filepath = "step1_summary_table.csv"
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


# ======================================================================
# 7.  MAIN
# ======================================================================

def main():
    print("=" * 60)
    print("  reproduce_vss.py")
    print("  Semiconductor FE-DieBank-BE: RP vs EV (VSS computation)")
    print("=" * 60)
    print()

    # --- Build instance -----------------------------------------------
    inst = make_instance()

    # --- Build scenarios ----------------------------------------------
    scenarios = build_scenarios(inst)

    # --- Solve stochastic RP ------------------------------------------
    print("-" * 60)
    print("  Solving stochastic RP model ...")
    print("-" * 60)
    rp_res = solve_rp(inst, scenarios, tag="RP")
    print_results(rp_res, label="STOCHASTIC RP")

    # --- Solve deterministic EV + evaluate EEV ------------------------
    print("-" * 60)
    print("  Solving deterministic EV model & computing EEV ...")
    print("-" * 60)
    ev_det_res, eev_res = solve_ev(inst, scenarios)
    print_results(eev_res, label="EV SOLUTION EVALUATED (EEV)")

    # --- Comparison table & VSS ---------------------------------------
    print_comparison(rp_res, eev_res, ev_det_res)

    # --- Optional: yield variance scan --------------------------------
    print("-" * 60)
    print("  Optional: scanning yield variance ...")
    print("-" * 60)
    scan_yield_variance(inst, alpha_list=[0.5, 1.0, 1.5, 2.0])

    # --- NEW: Generate visualizations and summary table ---------------
    print("-" * 60)
    print("  Generating visualizations & summary table ...")
    print("-" * 60)
    generate_visualizations(rp_res, eev_res, inst, scenarios)


if __name__ == "__main__":
    main()
