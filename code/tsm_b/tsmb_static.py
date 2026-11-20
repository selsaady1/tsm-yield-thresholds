"""
tsmb_static.py  (prompt tsm_b)

Single-period model of the paper (eqs. (1)-(9) of main.tex), rebuilt so that
three extensions can be switched on one at a time:

  * tool groups   (R1.7b): each fab f has groups k with capacity cap[f][k]
                   (tool hours) and load[k] (hours per wafer): load*x_f <= cap.
  * non-identical fabs (R1.7b): per-fab wafer cost c_F_f and per-fab FE
                   yield in each scenario (scenario key "fe_yield_f").
  * congestion   (R1.8): load-dependent WIP through a clearing function
                   x_f <= L_f W_f/(W_f + t0 L_f)  (Karmarkar form used by
                   Asmundsson et al.), outer-linearised by tangents, with WIP
                   cost c_W per wafer in WIP.  Cycle-time proxy CT_f = W_f/x_f
                   (Little's law), i.e. t0/(1-u_f).  Mode "pwl" is the
                   cross-check: the same WIP cost written as a convex
                   piecewise-linear cost of utilisation (Factory Physics VUT
                   form with V = 1), charged directly.  Optionally per tool
                   group (each group a queue with raw time t0_k) and at the BE
                   facilities (scenario-dependent, since die release is
                   recourse).

With every extension off, solve() is the same model as
revision_common.solve_model; self_check() verifies this on four instances.
"""
from pulp import LpProblem, LpMaximize, LpVariable, LpBinary, lpSum, value, LpStatus

from tsmb_common import solver
from revision_common import base_inst, two_point, FE_MEAN, BE_LO, BE_HI
import revision_common as rc

# utilisation points at which the clearing function / cost is linearised:
# every 0.01 from 0 to 0.98, then 0.985 and 0.99 (indifference band <= 0.01)
U_GRID = [round(0.01 * i, 2) for i in range(0, 99)] + [0.985, 0.99]


def scenarios(fe_lo, fe_hi, d_lo, d_hi, be_lo, be_hi, fe2=None, corr=True):
    """Equally likely scenarios.

    fe2=None: one FE yield common to both fabs (paper, 8 scenarios).
    fe2=(lo2, hi2): fab FE2 has its own levels; corr=True -> FE2 is low
    exactly when FE1 is low (8 scenarios); corr=False -> independent
    (16 scenarios).
    """
    out = []
    if fe2 is None:
        for fy in (fe_lo, fe_hi):
            for d in (d_lo, d_hi):
                for by in (be_lo, be_hi):
                    out.append({"fe_yield_f": {"FE1": fy, "FE2": fy}, "demand": d, "be_yield": by})
    else:
        pairs = ([(fe_lo, fe2[0]), (fe_hi, fe2[1])] if corr else
                 [(a, b) for a in (fe_lo, fe_hi) for b in fe2])
        for (a, b) in pairs:
            for d in (d_lo, d_hi):
                for by in (be_lo, be_hi):
                    out.append({"fe_yield_f": {"FE1": a, "FE2": b}, "demand": d, "be_yield": by})
    for i, s in enumerate(out):
        s["name"] = f"s{i}"
        s["prob"] = 1.0 / len(out)
    return out


def ev_scenario(sc):
    m = lambda f: sum(s["prob"] * f(s) for s in sc)
    fabs = list(sc[0]["fe_yield_f"].keys())
    return [{"name": "EV", "prob": 1.0,
             "fe_yield_f": {f: m(lambda s, f=f: s["fe_yield_f"][f]) for f in fabs},
             "demand": m(lambda s: s["demand"]), "be_yield": m(lambda s: s["be_yield"])}]


def _cf_tangents(prob, x, W, L, t0, tag):
    """x <= L*W/(W + t0*L), outer-linearised at the points of U_GRID."""
    k = t0 * L
    for j, u in enumerate(U_GRID):
        Wj = k * u / (1.0 - u)
        slope = L * (1.0 - u) ** 2 / k
        prob += x <= L * u + slope * (W - Wj), f"cf_{tag}_{j}"


def _pwl_cost(prob, x, C, L, t0, tag):
    """C >= t0*x/(1 - x/L) (WIP in wafers), tangents at U_GRID."""
    for j, u in enumerate(U_GRID):
        xj = L * u
        g = t0 * xj / (1.0 - u)
        slope = t0 / (1.0 - u) ** 2
        prob += C >= g + slope * (x - xj), f"pwl_{tag}_{j}"


def solve(inst, sc, fix_xf=None, cong=None, groups=None, c_F_f=None, tag="M",
          keep_binaries=True):
    """Build and solve the single-period model.

    cong: None or dict(mode="cf"|"pwl", c_W=..., t0=1.0, fe=True,
          per_group=False, t0_k={k: share}, be=False, c_W_be=..., t0_be=1.0)
    groups: None or dict(load={k: h/wafer}, cap={f: {k: hours}})
    """
    prob = LpProblem(f"TSMB_{tag}", LpMaximize)
    FE, BE, G, A = inst["FE_set"], inst["BE_set"], inst["G_set"], inst["A_set"]
    S = [s["name"] for s in sc]
    sp = {s["name"]: s["prob"] for s in sc}
    fy = {s["name"]: s["fe_yield_f"] for s in sc}
    by = {s["name"]: s["be_yield"] for s in sc}
    dm = {s["name"]: s["demand"] for s in sc}
    n = inst["n_f_i"]
    cF = c_F_f or {f: inst["c_F"] for f in FE}

    if fix_xf is None:
        X = {f: LpVariable(f"XF_{f}", 0) for f in FE}
    else:
        X = {f: LpVariable(f"XF_{f}", fix_xf[f], fix_xf[f]) for f in FE}
    if keep_binaries:
        OG = {g: LpVariable(f"OG_{g}", 0, 1, LpBinary) for g in G}
        OA = {a: LpVariable(f"OA_{a}", 0, 1, LpBinary) for a in A}
    else:
        OG = {g: 1.0 for g in G}
        OA = {a: 1.0 for a in A}
    i_ = {s: i for i, s in enumerate(S)}
    XFK = {(s, f): LpVariable(f"XFK_{i_[s]}_{f}", 0) for s in S for f in FE}
    XGK = {(s, g): LpVariable(f"XGK_{i_[s]}_{g}", 0) for s in S for g in G}
    Z = {s: LpVariable(f"Z_{i_[s]}", 0) for s in S}
    XKB = {(s, b): LpVariable(f"XKB_{i_[s]}_{b}", 0) for s in S for b in BE}
    XKA = {(s, a): LpVariable(f"XKA_{i_[s]}_{a}", 0) for s in S for a in A}
    XBD = {(s, b): LpVariable(f"XBD_{i_[s]}_{b}", 0) for s in S for b in BE}
    M = {s: LpVariable(f"M_{i_[s]}", 0) for s in S}
    Wd = {s: LpVariable(f"W_{i_[s]}", 0) for s in S}

    obj = []
    for s in S:
        obj.append(sp[s] * (
            inst["p_d"] * (dm[s] - M[s]) - inst["v_d"] * M[s]
            - inst["c_K"] * Z[s] - inst["c_D"] * Wd[s]
            - lpSum(inst["c_G"] * XGK[(s, g)] for g in G)
            - lpSum(inst["c_B"] * XKB[(s, b)] for b in BE)
            - lpSum(inst["c_A"] * XKA[(s, a)] for a in A)))
    first = lpSum(cF[f] * X[f] for f in FE)

    # ---------------- congestion (WIP) ----------------
    wip_fe, wip_terms, be_wip = {}, [], {}
    if cong:
        c_W = cong["c_W"]
        t0 = cong.get("t0", 1.0)
        if cong.get("fe", True):
            if cong.get("per_group"):
                for f in FE:
                    for k, lk in groups["load"].items():
                        Lfk = groups["cap"][f][k] / lk
                        t0k = t0 * cong["t0_k"][k]
                        Wv = LpVariable(f"WIP_{f}_{k}", 0)
                        if cong["mode"] == "cf":
                            _cf_tangents(prob, X[f], Wv, Lfk, t0k, f"{f}_{k}")
                        else:
                            _pwl_cost(prob, X[f], Wv, Lfk, t0k, f"{f}_{k}")
                        wip_fe[(f, k)] = Wv
            else:
                for f in FE:
                    Wv = LpVariable(f"WIP_{f}", 0)
                    if cong["mode"] == "cf":
                        _cf_tangents(prob, X[f], Wv, inst["L_F"][f], t0, f)
                    else:
                        _pwl_cost(prob, X[f], Wv, inst["L_F"][f], t0, f)
                    wip_fe[f] = Wv
            wip_terms.append(c_W * lpSum(wip_fe.values()))
        if cong.get("be"):
            c_Wb, t0b = cong["c_W_be"], cong.get("t0_be", 1.0)
            for s in S:
                for b in BE:
                    Wv = LpVariable(f"WIPB_{i_[s]}_{b}", 0)
                    if cong["mode"] == "cf":
                        _cf_tangents(prob, XKB[(s, b)], Wv, inst["L_B"][b], t0b, f"B{i_[s]}{b}")
                    else:
                        _pwl_cost(prob, XKB[(s, b)], Wv, inst["L_B"][b], t0b, f"B{i_[s]}{b}")
                    be_wip[(s, b)] = Wv
            wip_terms.append(lpSum(sp[s] * c_Wb * be_wip[(s, b)] for s in S for b in BE))

    prob += lpSum(obj) - first - (lpSum(wip_terms) if wip_terms else 0)

    for f in FE:
        prob += X[f] <= inst["L_F"][f]
    if groups:
        for f in FE:
            for k, lk in groups["load"].items():
                prob += lk * X[f] <= groups["cap"][f][k], f"tg_{f}_{k}"
    for s in S:
        for f in FE:
            prob += XFK[(s, f)] <= fy[s][f] * n * X[f]
        for g in G:
            prob += XGK[(s, g)] <= inst["L_G"][g] * OG[g]
        prob += (lpSum(XFK[(s, f)] for f in FE) + lpSum(XGK[(s, g)] for g in G)
                 - lpSum(XKB[(s, b)] for b in BE) - lpSum(XKA[(s, a)] for a in A) - Z[s] == 0)
        for b in BE:
            prob += XKB[(s, b)] <= inst["L_B"][b]
            prob += XBD[(s, b)] <= by[s] * XKB[(s, b)]
        for a in A:
            prob += XKA[(s, a)] <= inst["L_A"][a] * OA[a]
        prob += (lpSum(XBD[(s, b)] for b in BE) + lpSum(XKA[(s, a)] for a in A)
                 + M[s] - Wd[s] == dm[s])

    prob.solve(solver())
    v = lambda x: (value(x) or 0.0) if not isinstance(x, (int, float)) else float(x)
    xf = {f: v(X[f]) for f in FE}
    res = {
        "status": LpStatus[prob.status], "obj": value(prob.objective), "X_F": xf,
        "util": {f: xf[f] / inst["L_F"][f] for f in FE},
        "exp_unmet": sum(sp[s] * v(M[s]) for s in S),
        "M": {s: v(M[s]) for s in S},
        "exp_outs": sum(sp[s] * sum(v(XGK[(s, g)]) for g in G) for s in S),
        "max_outs": max(sum(v(XGK[(s, g)]) for g in G) for s in S),
        "max_dies_used": max(sum(v(XKB[(s, b)]) for b in BE) + sum(v(XKA[(s, a)]) for a in A)
                             for s in S),
        "exp_diebank": sum(sp[s] * v(Z[s]) for s in S),
        "wafer_cost": sum(cF[f] * xf[f] for f in FE),
    }
    if wip_fe:
        res["wip_fe"] = {str(k): v(w) for k, w in wip_fe.items()}
        if cong.get("per_group"):
            res["ct_fe"] = {f: sum(v(wip_fe[(f, k)]) for k in groups["load"]) / xf[f]
                            if xf[f] > 1e-9 else 0.0 for f in FE}
        else:
            res["ct_fe"] = {f: v(wip_fe[f]) / xf[f] if xf[f] > 1e-9 else 0.0 for f in FE}
        res["wip_cost_fe"] = cong["c_W"] * sum(v(w) for w in wip_fe.values())
    if be_wip:
        res["ct_be"] = {s: {b: (v(be_wip[(s, b)]) / v(XKB[(s, b)]) if v(XKB[(s, b)]) > 1e-9 else 0.0)
                            for b in BE} for s in S}
        res["util_be"] = {s: {b: v(XKB[(s, b)]) / inst["L_B"][b] for b in BE} for s in S}
        res["wip_cost_be"] = sum(sp[s] * cong["c_W_be"] * v(be_wip[(s, b)]) for s in S for b in BE)
    return res


def evaluate(inst, sc, **kw):
    """RP, EV and EEV on one scenario set (same definitions as the paper)."""
    rp = solve(inst, sc, tag="RP", **kw)
    ev = solve(inst, ev_scenario(sc), tag="EV", **kw)
    eev = solve(inst, sc, fix_xf=ev["X_F"], tag="EEV", **kw)
    ok = all(r["status"] == "Optimal" for r in (rp, ev, eev))
    vss = rp["obj"] - eev["obj"]
    return {"ok": ok, "rp": rp, "ev": ev, "eev": eev, "rp_obj": rp["obj"],
            "eev_obj": eev["obj"], "vss": vss,
            "pct_vss": 100.0 * vss / abs(rp["obj"]) if rp["obj"] else float("nan"),
            "rp_unmet": rp["exp_unmet"], "eev_unmet": eev["exp_unmet"],
            "unmet_gap": eev["exp_unmet"] - rp["exp_unmet"]}


def n_max(inst, sc, **kw):
    """Largest number of dies any scenario can turn into sales (solved):
    FE yield 1 and FE capacity non-binding, as in revision_common."""
    big = dict(inst)
    big["L_F"] = {f: 1e4 for f in inst["FE_set"]}
    sc1 = [dict(s, fe_yield_f={f: 1.0 for f in inst["FE_set"]}) for s in sc]
    kw = dict(kw)
    kw.pop("groups", None)
    c = kw.get("cong")
    if c and c.get("fe", True):
        c = dict(c, fe=False)
        kw["cong"] = c if c.get("be") else None
    return solve(big, sc1, tag="NMAX", **kw)["max_dies_used"]


def self_check(tol=1e-6):
    """With all extensions off, solve()/evaluate() must equal revision_common."""
    worst = 0.0
    inst = base_inst()
    for (fl, fh, bl, bh) in [(0.80, 0.95, 0.70, 0.90), (0.697, 1.0, 0.70, 0.90),
                             (0.675, 1.0, 0.70, 0.90), (0.80, 0.95, 0.55, 1.0)]:
        ref = rc.evaluate(inst, fl, fh, bl, bh)
        sc = scenarios(fl, fh, inst["demand_lo"], inst["demand_hi"], bl, bh)
        r = evaluate(inst, sc)
        worst = max(worst, abs(r["rp_obj"] - ref["rp_obj"]), abs(r["eev_obj"] - ref["eev_obj"]))
    if worst > tol:
        raise AssertionError(f"tsmb_static deviates from revision_common by {worst}")
    return worst
