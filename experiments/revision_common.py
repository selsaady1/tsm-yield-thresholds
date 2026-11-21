"""
revision_common.py
==================
Shared helpers for the revision-round experiments
(param_sensitivity_revision.py, capacity_cliff_sweep.py).

Everything here reuses the frozen instance of src/step2_freeze_model.py and
solves with the same PuLP/CBC call. No number is hard-coded as a result:
every value written by the revision scripts is a solver output.

What this module adds over step2_freeze_model.run_experiment
------------------------------------------------------------
1. `solve_model` rebuilds the *same* model as step2's solve_rp /
   solve_rp_fixed, but lets any frozen parameter (costs, capacities, demand,
   penalty) be overridden through the instance dict. `self_check()` asserts
   that it reproduces step2's objective values before any sweep is trusted.

2. An optional `nonanticipative=True` switch. In the model as solved for the
   paper, every recourse variable is indexed by the full scenario
   (FE yield, demand, BE yield), so die release into the Back-End is chosen
   with the Back-End yield already known. With the switch on, the
   die-bank/BE-release variables are shared by the two scenarios that differ
   only in BE yield, which is the strict three-stage information structure.
   This is used only as a robustness check on the paper's conclusions.

3. `evaluate` (one RP-vs-EEV comparison) and `sweep` / `crossing`
   (threshold location by linear interpolation, the same rule as
   step5/step6 find_threshold).

Yield parameterisation
----------------------
`two_point(mean, half)` is the paper's convention: lo = mean - half,
hi = mean + half, each clipped to [0.01, 1.00]. NOTE: once mean + half > 1
the upper point saturates at 1.00, the two-point distribution becomes
{lo, 1.00}, and its true mean is (lo + 1)/2 rather than the nominal mean.
`evaluate` therefore reports both the nominal and the realised mean and a
`clipped` flag, so every threshold can be labelled as lying in the
symmetric or in the clipped regime.
"""

from pulp import (LpProblem, LpMaximize, LpVariable, LpBinary, lpSum, value,
                  LpStatus, PULP_CBC_CMD)

from step2_freeze_model import (FrozenInstance, build_scenarios, solve_rp,
                                solve_rp_fixed)

FE_MEAN = 0.875          # paper baseline (0.80-0.95)
BE_LO, BE_HI = 0.70, 0.90
HALF_GRID = [round(0.01 * i, 4) for i in range(1, 51)]   # 0.01 .. 0.50


def base_inst(**over):
    """Frozen-instance dict (yields are placeholders) with optional overrides.

    Dict-valued overrides (L_F, L_B, L_G, L_A) replace the whole dict.
    """
    inst = FrozenInstance.step1_baseline().to_inst_dict()
    for k, v in over.items():
        if k not in inst:
            raise KeyError(f"unknown instance parameter: {k}")
        inst[k] = v
    return inst


def two_point(mean, half):
    """Paper convention: (lo, hi) = mean -/+ half, clipped to [0.01, 1.00]."""
    lo = max(0.01, round(mean - half, 6))
    hi = min(1.00, round(mean + half, 6))
    return lo, hi


def scenarios_2x2x2(fe_lo, fe_hi, d_lo, d_hi, be_lo, be_hi):
    inst = {"fe_yield_lo": fe_lo, "fe_yield_hi": fe_hi,
            "demand_lo": d_lo, "demand_hi": d_hi,
            "be_yield_lo": be_lo, "be_yield_hi": be_hi}
    return build_scenarios(inst)


def solve_model(inst, scenarios, fix_xf=None, nonanticipative=False,
                balance_fe=False, tag="M"):
    """Same model as step2 solve_rp (fix_xf=None) / solve_rp_fixed (fix_xf set).

    With nonanticipative=True the stage-2 variables (dies received, outsourced
    dies, die-bank inventory, dies released to BE / to the outside assembler)
    are indexed by the (FE yield, demand) node instead of the full scenario.
    """
    prob = LpProblem(f"SC_{tag}", LpMaximize)
    FE, BE, G, A = inst["FE_set"], inst["BE_set"], inst["G_set"], inst["A_set"]
    S = [s["name"] for s in scenarios]
    sp = {s["name"]: s["prob"] for s in scenarios}
    fy = {s["name"]: s["fe_yield"] for s in scenarios}
    by = {s["name"]: s["be_yield"] for s in scenarios}
    dm = {s["name"]: s["demand"] for s in scenarios}
    n = inst["n_f_i"]

    # node of a scenario for the stage-2 variables
    if nonanticipative:
        node = {s: (fy[s], dm[s]) for s in S}
    else:
        node = {s: s for s in S}
    nodes = list(dict.fromkeys(node.values()))
    nid = {nd: i for i, nd in enumerate(nodes)}

    if fix_xf is None:
        X_F = {f: LpVariable(f"XF_{f}", 0) for f in FE}
    else:
        X_F = {f: LpVariable(f"XF_{f}", fix_xf[f], fix_xf[f]) for f in FE}
    # Outsourcing contracts carry no fixed cost in this instance, so they are
    # free binaries in both RP and EEV (as they effectively are in step2:
    # PuLP resets the bounds of an LpBinary variable to [0, 1]).
    O_G = {g: LpVariable(f"OG_{g}", 0, 1, LpBinary) for g in G}
    O_A = {a: LpVariable(f"OA_{a}", 0, 1, LpBinary) for a in A}

    X_FK = {(k, f): LpVariable(f"XFK_{nid[k]}_{f}", 0) for k in nodes for f in FE}
    X_GK = {(k, g): LpVariable(f"XGK_{nid[k]}_{g}", 0) for k in nodes for g in G}
    Z = {k: LpVariable(f"Z_{nid[k]}", 0) for k in nodes}
    X_KB = {(k, b): LpVariable(f"XKB_{nid[k]}_{b}", 0) for k in nodes for b in BE}
    X_KA = {(k, a): LpVariable(f"XKA_{nid[k]}_{a}", 0) for k in nodes for a in A}
    X_BD = {(s, b): LpVariable(f"XBD_{i}_{b}", 0) for i, s in enumerate(S) for b in BE}
    X_AD = {(s, a): LpVariable(f"XAD_{i}_{a}", 0) for i, s in enumerate(S) for a in A}
    M = {s: LpVariable(f"M_{i}", 0) for i, s in enumerate(S)}
    W = {s: LpVariable(f"W_{i}", 0) for i, s in enumerate(S)}

    obj = []
    for s in S:
        k = node[s]
        obj.append(sp[s] * (
            inst["p_d"] * (dm[s] - M[s]) - inst["v_d"] * M[s]
            - inst["c_K"] * Z[k] - inst["c_D"] * W[s]
            - lpSum(inst["c_G"] * X_GK[(k, g)] for g in G)
            - lpSum(inst["c_B"] * X_KB[(k, b)] for b in BE)
            - lpSum(inst["c_A"] * X_KA[(k, a)] for a in A)))
    prob += lpSum(obj) - lpSum(inst["c_F"] * X_F[f] for f in FE)

    for f in FE:
        prob += X_F[f] <= inst["L_F"][f]
    if balance_fe and fix_xf is None:
        # equal utilisation of all fabs (load-balancing check)
        f0 = FE[0]
        for f in FE[1:]:
            prob += X_F[f] * inst["L_F"][f0] == X_F[f0] * inst["L_F"][f]
    for k in nodes:
        # every scenario mapped to node k has the same FE yield
        yk = next(fy[s] for s in S if node[s] == k)
        for f in FE:
            prob += X_FK[(k, f)] <= yk * n * X_F[f]
        for g in G:
            prob += X_GK[(k, g)] <= inst["L_G"][g] * O_G[g]
        prob += (lpSum(X_FK[(k, f)] for f in FE) + lpSum(X_GK[(k, g)] for g in G)
                 - lpSum(X_KB[(k, b)] for b in BE) - lpSum(X_KA[(k, a)] for a in A)
                 - Z[k] == 0)
        for b in BE:
            prob += X_KB[(k, b)] <= inst["L_B"][b]
        for a in A:
            prob += X_KA[(k, a)] <= inst["L_A"][a] * O_A[a]
    for s in S:
        k = node[s]
        for b in BE:
            prob += X_BD[(s, b)] <= by[s] * X_KB[(k, b)]
        for a in A:
            prob += X_AD[(s, a)] == X_KA[(k, a)]
        prob += (lpSum(X_BD[(s, b)] for b in BE) + lpSum(X_AD[(s, a)] for a in A)
                 + M[s] - W[s] == dm[s])

    prob.solve(PULP_CBC_CMD(msg=0))
    v = lambda x: value(x) or 0.0
    return {
        "status": LpStatus[prob.status],
        "obj": value(prob.objective),
        "X_F": {f: v(X_F[f]) for f in FE},
        "exp_unmet": sum(sp[s] * v(M[s]) for s in S),
        "max_unmet": max(v(M[s]) for s in S),
        "exp_outsourced_dies": sum(sp[s] * sum(v(X_GK[(node[s], g)]) for g in G) for s in S),
        "max_outsourced_dies": max(sum(v(X_GK[(node[s], g)]) for g in G) for s in S),
        "exp_diebank": sum(sp[s] * v(Z[node[s]]) for s in S),
        "exp_excess_devices": sum(sp[s] * v(W[s]) for s in S),
        "max_dies_used": max(sum(v(X_KB[(node[s], b)]) for b in BE)
                             + sum(v(X_KA[(node[s], a)]) for a in A) for s in S),
        "exp_dies_used": sum(sp[s] * (sum(v(X_KB[(node[s], b)]) for b in BE)
                                      + sum(v(X_KA[(node[s], a)]) for a in A)) for s in S),
        "M": {s: v(M[s]) for s in S},
        "G": {s: sum(v(X_GK[(node[s], g)]) for g in G) for s in S},
    }


def evaluate_scenarios(inst, sc, nonanticipative=False, balance_fe=False):
    """One RP-vs-EEV comparison on an arbitrary scenario list."""
    rp = solve_model(inst, sc, nonanticipative=nonanticipative, balance_fe=balance_fe, tag="RP")
    mean = lambda key: sum(s["prob"] * s[key] for s in sc)
    ev_sc = [{"name": "EV", "prob": 1.0, "fe_yield": mean("fe_yield"),
              "demand": mean("demand"), "be_yield": mean("be_yield")}]
    ev = solve_model(inst, ev_sc, balance_fe=balance_fe, tag="EV")
    eev = solve_model(inst, sc, fix_xf=ev["X_F"], nonanticipative=nonanticipative, tag="EEV")
    ok = all(r["status"] == "Optimal" for r in (rp, ev, eev))
    vss = rp["obj"] - eev["obj"]
    return {
        "ok": ok,
        "ev_dies_used": ev["max_dies_used"],
        "rp_obj": rp["obj"], "eev_obj": eev["obj"], "vss": vss,
        "pct_vss": 100.0 * vss / abs(rp["obj"]) if rp["obj"] else float("nan"),
        "rp_unmet": rp["exp_unmet"], "eev_unmet": eev["exp_unmet"],
        "unmet_gap": eev["exp_unmet"] - rp["exp_unmet"],
        "rp_fe1": rp["X_F"]["FE1"], "rp_fe2": rp["X_F"]["FE2"],
        "ev_fe1": ev["X_F"]["FE1"], "ev_fe2": ev["X_F"]["FE2"],
        "rp_exp_outs": rp["exp_outsourced_dies"], "eev_exp_outs": eev["exp_outsourced_dies"],
        "rp_max_outs": rp["max_outsourced_dies"], "eev_max_outs": eev["max_outsourced_dies"],
        "rp_exp_diebank": rp["exp_diebank"], "eev_exp_diebank": eev["exp_diebank"],
    }


def evaluate(inst, fe_lo, fe_hi, be_lo=BE_LO, be_hi=BE_HI, nonanticipative=False,
             balance_fe=False):
    """One RP-vs-EEV comparison on the paper's 2x2x2 scenario set."""
    sc = scenarios_2x2x2(fe_lo, fe_hi, inst["demand_lo"], inst["demand_hi"], be_lo, be_hi)
    r = evaluate_scenarios(inst, sc, nonanticipative, balance_fe)
    r.update({"fe_lo": fe_lo, "fe_hi": fe_hi, "fe_true_mean": (fe_lo + fe_hi) / 2})
    return r


def max_die_requirement(inst, be_lo=BE_LO, be_hi=BE_HI):
    """Largest number of dies any (demand, BE yield) scenario can usefully absorb.

    Solved, not assumed: the four (demand, BE yield) combinations are optimised
    with FE yield 1 and FE capacity made non-binding, and the largest die usage
    is returned.
    """
    big = dict(inst)
    big["L_F"] = {f: 1e4 for f in inst["FE_set"]}
    sc = scenarios_2x2x2(1.0, 1.0, inst["demand_lo"], inst["demand_hi"], be_lo, be_hi)
    return solve_model(big, sc, tag="NMAX")["max_dies_used"]


def sweep(inst, fe_mean=FE_MEAN, be_lo=BE_LO, be_hi=BE_HI, halves=HALF_GRID,
          nonanticipative=False):
    """FE half-range sweep (paper convention, with clipping). List of dicts."""
    rows = []
    for h in halves:
        lo, hi = two_point(fe_mean, h)
        r = evaluate(inst, lo, hi, be_lo, be_hi, nonanticipative)
        r["fe_mean_nominal"] = fe_mean
        r["half"] = h
        r["clipped"] = int(fe_mean + h > 1.0 + 1e-9)
        rows.append(r)
    return rows


def crossing(rows, metric, level):
    """First upward crossing of `level` by `metric` along the sweep.

    Linear interpolation between adjacent grid points (same rule as
    step5/step6 find_threshold). Returns a dict with the interpolated
    half-range, the corresponding worst-case (low) FE yield, the realised
    mean at the crossing and whether the crossing lies in the clipped
    regime; or None when the metric never crosses on the grid. If the
    metric is already above `level` at the first grid point the crossing is
    reported as "below_grid".
    """
    rows = [r for r in rows if r["ok"]]
    if not rows:
        return None
    if rows[0][metric] >= level:
        return {"half": None, "note": "below_grid"}
    for a, b in zip(rows, rows[1:]):
        if a[metric] < level <= b[metric]:
            t = (level - a[metric]) / (b[metric] - a[metric])
            half = a["half"] + t * (b["half"] - a["half"])
            mean = a["fe_mean_nominal"]
            lo, hi = two_point(mean, half)
            return {"half": half, "y_lo": lo, "y_hi": hi,
                    "true_mean": (lo + hi) / 2, "clipped": int(mean + half > 1.0 + 1e-9),
                    "note": ""}
    return None


def self_check(tol=1e-4):
    """solve_model must reproduce step2's RP and EEV objectives."""
    worst = 0.0
    for (fl, fh, bl, bh) in [(0.80, 0.95, 0.70, 0.90), (0.697, 1.0, 0.70, 0.90),
                             (0.675, 1.0, 0.70, 0.90), (0.80, 0.95, 0.55, 1.0)]:
        inst = FrozenInstance(fl, fh, bl, bh).to_inst_dict()
        sc = build_scenarios(inst)
        rp0 = solve_rp(inst, sc, tag="chk")
        m = lambda key: sum(s["prob"] * s[key] for s in sc)
        ev0 = solve_rp(inst, [{"name": "EV", "prob": 1.0, "fe_yield": m("fe_yield"),
                               "demand": m("demand"), "be_yield": m("be_yield")}], tag="chkEV")
        eev0 = solve_rp_fixed(inst, sc, ev0["X_F"], ev0["O_G"], ev0["O_A"])
        r = evaluate(base_inst(), fl, fh, bl, bh)
        worst = max(worst, abs(r["rp_obj"] - rp0["obj"]), abs(r["eev_obj"] - eev0["obj"]))
    if worst > tol:
        raise AssertionError(f"solve_model deviates from step2 by {worst}")
    return worst
