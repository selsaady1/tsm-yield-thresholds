"""
tsmb_multiperiod.py  (prompt tsm_b, R1.7c: lead times and die-bank inventory)

Multi-period version of the paper's model on a scenario tree.

Time.  Wafer cohorts arrive at the die bank in periods a = 1..T.  Dies are
released to BE in periods 1..T; with BE lead time lB = 0 they complete in the
same period (as in the paper's model as solved), with lB = 1 they complete one
period later.  Demand occurs in the completion periods, so there are T demand
periods in both cases.  Dies left in the die bank are carried to the next
period at the paper's holding cost c_K per die per period.  Unmet demand is
lost (penalty v); excess devices cost c_D, as in the paper.

Uncertainty, per period and independent across periods (base-instance
levels): FE yield of the cohort arriving in the period (two-point), BE yield
of the cohort completing in the period (two-point), and demand (600/900).
Each is revealed in the period it applies to, so a period has 8 outcomes
(2 FE x 2 demand x 2 BE) and a tree with T periods has 8^T leaves.

Decisions.  Every flow in a period (dies received, dies bought outside, dies
released, die-bank stock, completions) is chosen at the tree node of that
period, i.e. with the history up to and including that period known
(non-anticipative).  Wafer starts:
  * "two" (two-stage): all starts X[f,a] are fixed at the root, now.
  * "multi" (multistage): the start of the cohort that arrives in period a is
    chosen at the node of period a - lF (the root if a - lF <= 0), where lF is
    the FE lead time.  In the two-stage version lF only relabels periods.

Outsourcing contracts have no fixed cost (property (b) of the paper), so they
are fixed open here and no binaries are used.

With T = 1 and lB = 0 the model is the paper's single-period model;
check_T1() verifies RP, EV and EEV against revision_common.
"""
import itertools

import numpy as np
from pulp import LpProblem, LpMaximize, LpVariable, lpSum, value, LpStatus

from tsmb_common import solver
from revision_common import base_inst
import revision_common as rc


# --------------------------------------------------------------------------
# scenario tree
# --------------------------------------------------------------------------
class Tree:
    def __init__(self, T, lB, fe, be, dem, deterministic=False):
        """fe, be, dem: (lo, hi) two-point levels, each with probability 1/2.
        deterministic=True builds the single expected-value path."""
        self.T, self.lB = T, lB
        self.E = T + lB
        self.nodes = [{"id": 0, "e": 0, "parent": None, "prob": 1.0, "children": []}]
        frontier = [0]
        for e in range(1, self.E + 1):
            has_fe = e <= T
            has_cmp = (e <= T) if lB == 0 else (2 <= e <= T + 1)
            levels = []
            if deterministic:
                levels.append((np.mean(fe) if has_fe else None,
                               np.mean(be) if has_cmp else None,
                               np.mean(dem) if has_cmp else None, 1.0))
            else:
                fl = list(fe) if has_fe else [None]
                bl = list(be) if has_cmp else [None]
                dl = list(dem) if has_cmp else [None]
                combos = list(itertools.product(fl, dl, bl))
                for (a, d, b) in combos:
                    levels.append((a, b, d, 1.0 / len(combos)))
            new = []
            for pid in frontier:
                for (a, b, d, p) in levels:
                    nid = len(self.nodes)
                    self.nodes.append({"id": nid, "e": e, "parent": pid,
                                       "prob": self.nodes[pid]["prob"] * p,
                                       "fe_y": a, "be_y": b, "dem": d, "children": []})
                    self.nodes[pid]["children"].append(nid)
                    new.append(nid)
            frontier = new
        self.release = [n for n in self.nodes if 1 <= n["e"] <= T]
        self.complete = [n for n in self.nodes if n.get("be_y") is not None]

    def anc(self, nid, e):
        """Ancestor of node nid at epoch e (e <= epoch of nid; e<=0 -> root)."""
        if e <= 0:
            return 0
        while self.nodes[nid]["e"] > e:
            nid = self.nodes[nid]["parent"]
        return nid


def owner_epoch(a, mode, lF):
    return 0 if mode == "two" else max(0, a - lF)


# --------------------------------------------------------------------------
# tree LP (PuLP + CBC)
# --------------------------------------------------------------------------
def solve_tree(inst, tree, mode="two", lF=1, fix_x=None, tag="MP"):
    """Solve the multi-period model on `tree`.

    fix_x: dict {(f, a): wafers} fixes every start (used for EEV).
    Returns objective, per-period expected unmet demand, starts, inventory.
    """
    prob = LpProblem(f"MP_{tag}", LpMaximize)
    FE, BE = inst["FE_set"], inst["BE_set"]
    LG = sum(inst["L_G"].values())
    LA = sum(inst["L_A"].values())
    n = inst["n_f_i"]
    T, lB = tree.T, tree.lB
    N = tree.nodes

    # starts: X[(f, a, owner)]
    X = {}
    for nd in tree.release:
        a = nd["e"]
        ow = tree.anc(nd["id"], owner_epoch(a, mode, lF))
        for f in FE:
            key = (f, a, ow)
            if key not in X:
                if fix_x is not None:
                    v0 = fix_x[(f, a)]
                    X[key] = LpVariable(f"X_{f}_{a}_{ow}", v0, v0)
                else:
                    X[key] = LpVariable(f"X_{f}_{a}_{ow}", 0, inst["L_F"][f])
    u, g, I, k, aa = {}, {}, {}, {}, {}
    for nd in tree.release:
        i = nd["id"]
        for f in FE:
            u[(i, f)] = LpVariable(f"u_{i}_{f}", 0)
        g[i] = LpVariable(f"g_{i}", 0, LG)
        I[i] = LpVariable(f"I_{i}", 0)
        for b in BE:
            k[(i, b)] = LpVariable(f"k_{i}_{b}", 0, inst["L_B"][b])
        aa[i] = LpVariable(f"a_{i}", 0, LA)
    d, M, W = {}, {}, {}
    for nd in tree.complete:
        i = nd["id"]
        for b in BE:
            d[(i, b)] = LpVariable(f"d_{i}_{b}", 0)
        M[i] = LpVariable(f"M_{i}", 0)
        W[i] = LpVariable(f"W_{i}", 0)

    obj = []
    for (f, a, ow), var in X.items():
        obj.append(-N[ow]["prob"] * inst["c_F"] * var)
    for nd in tree.release:
        i, p = nd["id"], nd["prob"]
        obj.append(-p * (inst["c_G"] * g[i] + inst["c_B"] * lpSum(k[(i, b)] for b in BE)
                         + inst["c_A"] * aa[i] + inst["c_K"] * I[i]))
    for nd in tree.complete:
        i, p = nd["id"], nd["prob"]
        obj.append(p * (inst["p_d"] * (nd["dem"] - M[i]) - inst["v_d"] * M[i]
                        - inst["c_D"] * W[i]))
    prob += lpSum(obj)

    for nd in tree.release:
        i, a = nd["id"], nd["e"]
        ow = tree.anc(i, owner_epoch(a, mode, lF))
        for f in FE:
            prob += u[(i, f)] <= nd["fe_y"] * n * X[(f, a, ow)]
        prev = I[nd["parent"]] if nd["parent"] in I else 0
        prob += (prev + lpSum(u[(i, f)] for f in FE) + g[i]
                 == lpSum(k[(i, b)] for b in BE) + aa[i] + I[i])
    for nd in tree.complete:
        i = nd["id"]
        src = i if lB == 0 else nd["parent"]
        for b in BE:
            prob += d[(i, b)] <= nd["be_y"] * k[(src, b)]
        prob += lpSum(d[(i, b)] for b in BE) + aa[src] + M[i] - W[i] == nd["dem"]

    prob.solve(solver())
    st = LpStatus[prob.status]
    val = lambda x: value(x) or 0.0
    # expected starts per period (two-stage: the single root value)
    starts = {}
    for (f, a, ow), var in X.items():
        starts.setdefault((f, a), 0.0)
        starts[(f, a)] += N[ow]["prob"] * val(var)
    exp_unmet = {}
    for nd in tree.complete:
        exp_unmet[nd["e"]] = exp_unmet.get(nd["e"], 0.0) + nd["prob"] * val(M[nd["id"]])
    exp_inv = {}
    for nd in tree.release:
        exp_inv[nd["e"]] = exp_inv.get(nd["e"], 0.0) + nd["prob"] * val(I[nd["id"]])
    exp_outs = {}
    for nd in tree.release:
        exp_outs[nd["e"]] = exp_outs.get(nd["e"], 0.0) + nd["prob"] * val(g[nd["id"]])
    root_x = {(f, a): val(var) for (f, a, ow), var in X.items() if ow == 0}
    return {"status": st, "obj": value(prob.objective), "starts": starts, "root_x": root_x,
            "exp_unmet_by_period": exp_unmet, "exp_unmet_total": sum(exp_unmet.values()),
            "exp_inv_by_period": exp_inv, "exp_outs_by_period": exp_outs,
            "n_vars": len(prob.variables()), "n_cons": len(prob.constraints)}


def ev_plan(inst, T, lB, fe, be, dem):
    """Expected-value plan: one path with mean yields and mean demand."""
    tr = Tree(T, lB, fe, be, dem, deterministic=True)
    r = solve_tree(inst, tr, mode="two", tag="EV")
    r["x"] = {(f, a): r["root_x"][(f, a)] for f in inst["FE_set"] for a in range(1, T + 1)}
    return r


def evaluate(inst, T, lB, fe, be, dem, mode="two", lF=1, tree=None):
    """RP (two-stage or multistage), EV, EEV (EV starts fixed, flows adapt)."""
    tree = tree or Tree(T, lB, fe, be, dem)
    rp = solve_tree(inst, tree, mode=mode, lF=lF, tag="RP")
    ev = ev_plan(inst, T, lB, fe, be, dem)
    eev = solve_tree(inst, tree, mode="two", fix_x=ev["x"], tag="EEV")
    ok = all(r["status"] == "Optimal" for r in (rp, ev, eev))
    vss = rp["obj"] - eev["obj"]
    return {"ok": ok, "rp": rp, "ev": ev, "eev": eev, "rp_obj": rp["obj"], "eev_obj": eev["obj"],
            "vss": vss, "pct_vss": 100 * vss / abs(rp["obj"]),
            "rp_unmet_pp": rp["exp_unmet_total"] / T, "eev_unmet_pp": eev["exp_unmet_total"] / T,
            "unmet_gap_pp": (eev["exp_unmet_total"] - rp["exp_unmet_total"]) / T,
            "n_nodes": len(tree.nodes)}


def check_T1(tol=1e-6):
    """T=1, lB=0 must equal the paper's single-period RP/EEV (revision_common)."""
    inst = base_inst()
    worst = 0.0
    for (fl, fh, bl, bh) in [(0.80, 0.95, 0.70, 0.90), (0.697, 1.0, 0.70, 0.90),
                             (0.675, 1.0, 0.70, 0.90)]:
        ref = rc.evaluate(inst, fl, fh, bl, bh)
        r = evaluate(inst, 1, 0, (fl, fh), (bl, bh), (inst["demand_lo"], inst["demand_hi"]))
        worst = max(worst, abs(r["rp_obj"] - ref["rp_obj"]), abs(r["eev_obj"] - ref["eev_obj"]))
    if worst > tol:
        raise AssertionError(f"multi-period T=1 deviates from revision_common by {worst}")
    return worst


# --------------------------------------------------------------------------
# rolling-horizon deterministic policy (comparator for the multistage plan)
# --------------------------------------------------------------------------
def _path_lp(inst, e0, T, lB, lF, mode, state, cur, means):
    """Deterministic re-plan from epoch e0 (outcome of e0 observed).

    state: I_prev, committed {(f,a): x} for arrivals already fixed,
           k_prev/a_prev (lB=1: releases of e0-1 completing at e0).
    cur:   realised fe_y (if e0<=T), be_y, dem (if e0 is a completion epoch).
    means: (fe_mean, be_mean, dem_mean) for later epochs.
    Returns the decisions of epoch e0 (flows and the starts owned by e0).
    Solved with scipy's HiGHS (linprog); small path LPs only.
    """
    from scipy.optimize import linprog
    FE, BE = inst["FE_set"], inst["BE_set"]
    n = inst["n_f_i"]
    LG = sum(inst["L_G"].values())
    LA = sum(inst["L_A"].values())
    E = T + lB
    var, lo, hi, c = {}, [], [], []

    def add(name, lb, ub, cost):
        var[name] = len(lo)
        lo.append(lb)
        hi.append(ub)
        c.append(cost)
    # starts still open (owner epoch >= e0) for arrivals a >= e0
    for a in range(max(e0, 1), T + 1):
        for f in FE:
            if (f, a) in state["committed"]:
                continue
            add(("X", f, a), 0, inst["L_F"][f], inst["c_F"])
    for t in range(max(e0, 1), T + 1):
        for f in FE:
            add(("u", f, t), 0, None, 0.0)
        add(("g", t), 0, LG, inst["c_G"])
        add(("I", t), 0, None, inst["c_K"])
        for b in BE:
            add(("k", b, t), 0, inst["L_B"][b], inst["c_B"])
        add(("a", t), 0, LA, inst["c_A"])
    cmp_epochs = [t for t in range(max(e0, 1), E + 1)
                  if ((t <= T) if lB == 0 else (2 <= t <= T + 1))]
    for t in cmp_epochs:
        for b in BE:
            add(("d", b, t), 0, None, 0.0)
        add(("M", t), 0, None, inst["p_d"] + inst["v_d"])   # minimise cost; revenue const
        add(("W", t), 0, None, inst["c_D"])
    nv = len(lo)
    Aub, bub, Aeq, beq = [], [], [], []

    def row():
        return np.zeros(nv)
    fe_y = lambda t: cur["fe_y"] if t == e0 else means[0]
    be_y = lambda t: cur["be_y"] if t == e0 else means[1]
    dem = lambda t: cur["dem"] if t == e0 else means[2]
    for t in range(max(e0, 1), T + 1):
        for f in FE:
            r = row()
            r[var[("u", f, t)]] = 1
            if (f, t) in state["committed"]:
                rhs = fe_y(t) * n * state["committed"][(f, t)]
            else:
                r[var[("X", f, t)]] = -fe_y(t) * n
                rhs = 0.0
            Aub.append(r)
            bub.append(rhs)
        r = row()
        for f in FE:
            r[var[("u", f, t)]] = 1
        r[var[("g", t)]] = 1
        for b in BE:
            r[var[("k", b, t)]] = -1
        r[var[("a", t)]] = -1
        r[var[("I", t)]] = -1
        prevI = 0.0
        if t == max(e0, 1):
            prevI = state["I_prev"]
        else:
            r[var[("I", t - 1)]] = 1
        Aeq.append(r)
        beq.append(-prevI)
    for t in cmp_epochs:
        r = row()
        rhs_k = 0.0
        src = t if lB == 0 else t - 1
        for b in BE:
            rr = row()
            rr[var[("d", b, t)]] = 1
            if src < max(e0, 1):          # release already made (lB=1, t == e0)
                Aub.append(rr)
                bub.append(be_y(t) * state["k_prev"][b])
            else:
                rr[var[("k", b, src)]] = -be_y(t)
                Aub.append(rr)
                bub.append(0.0)
        q = row()
        for b in BE:
            q[var[("d", b, t)]] = 1
        if src < max(e0, 1):
            rhs_k = state["a_prev"]
        else:
            q[var[("a", src)]] = 1
        q[var[("M", t)]] = 1
        q[var[("W", t)]] = -1
        Aeq.append(q)
        beq.append(dem(t) - rhs_k)
    res = linprog(np.array(c), A_ub=np.array(Aub) if Aub else None,
                  b_ub=np.array(bub) if bub else None, A_eq=np.array(Aeq), b_eq=np.array(beq),
                  bounds=list(zip(lo, hi)), method="highs")
    if res.status != 0:
        raise RuntimeError(f"path LP failed at e0={e0}: {res.message}")
    x = res.x
    get = lambda key: float(x[var[key]]) if key in var else None
    out = {"X": {}, "flows": {}}
    for a in range(max(e0, 1), T + 1):
        for f in FE:
            if ("X", f, a) in var and owner_epoch(a, mode, lF) == e0:
                out["X"][(f, a)] = get(("X", f, a))
    if e0 >= 1:
        if e0 <= T:
            out["flows"] = {"u": {f: get(("u", f, e0)) for f in FE}, "g": get(("g", e0)),
                            "I": get(("I", e0)), "k": {b: get(("k", b, e0)) for b in BE},
                            "a": get(("a", e0))}
        if e0 in cmp_epochs:
            out["flows"]["M"] = get(("M", e0))
            out["flows"]["W"] = get(("W", e0))
            out["flows"]["d"] = {b: get(("d", b, e0)) for b in BE}
    return out


def rolling_ev(inst, tree, lF, mode="multi"):
    """Expected profit and unmet demand of the rolling deterministic policy.

    At every node the planner re-solves the expected-value problem from the
    current state (realised outcome of the period, mean values afterwards) and
    implements the decisions of the period, including the starts that must be
    committed now given the FE lead time lF.
    """
    T, lB = tree.T, tree.lB
    fe = sorted({nd["fe_y"] for nd in tree.nodes if nd.get("fe_y") is not None})
    be = sorted({nd["be_y"] for nd in tree.nodes if nd.get("be_y") is not None})
    dm = sorted({nd["dem"] for nd in tree.nodes if nd.get("dem") is not None})
    means = (float(np.mean(fe)), float(np.mean(be)), float(np.mean(dm)))
    FE, BE = inst["FE_set"], inst["BE_set"]
    total = {"profit": 0.0, "unmet": 0.0, "lps": 0}

    def visit(nid, state):
        nd = tree.nodes[nid]
        e = nd["e"]
        cur = {"fe_y": nd.get("fe_y"), "be_y": nd.get("be_y"), "dem": nd.get("dem")}
        dec = _path_lp(inst, e, T, lB, lF, mode, state, cur, means)
        total["lps"] += 1
        p = nd["prob"]
        committed = dict(state["committed"])
        for key, xv in dec["X"].items():
            committed[key] = xv
            total["profit"] -= p * inst["c_F"] * xv
        fl = dec["flows"]
        new_state = {"committed": committed, "I_prev": state["I_prev"],
                     "k_prev": state.get("k_prev"), "a_prev": state.get("a_prev")}
        if 1 <= e <= T:
            total["profit"] -= p * (inst["c_G"] * fl["g"] + inst["c_B"] * sum(fl["k"].values())
                                    + inst["c_A"] * fl["a"] + inst["c_K"] * fl["I"])
            new_state["I_prev"] = fl["I"]
            new_state["k_prev"] = fl["k"]
            new_state["a_prev"] = fl["a"]
        if "M" in fl:
            total["profit"] += p * (inst["p_d"] * (nd["dem"] - fl["M"]) - inst["v_d"] * fl["M"]
                                    - inst["c_D"] * fl["W"])
            total["unmet"] += p * fl["M"]
        for ch in nd["children"]:
            visit(ch, new_state)

    visit(0, {"committed": {}, "I_prev": 0.0, "k_prev": {b: 0.0 for b in BE}, "a_prev": 0.0})
    return {"obj": total["profit"], "exp_unmet_total": total["unmet"],
            "unmet_pp": total["unmet"] / T, "n_lps": total["lps"]}
