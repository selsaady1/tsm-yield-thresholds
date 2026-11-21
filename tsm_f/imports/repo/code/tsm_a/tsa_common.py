"""
tsa_common.py  (TSM-A, revision of TSM-26-0314)
================================================
Shared model builder for the TSM-A experiments (other planning paradigms,
capacity uncertainty, demand map, scenarios from limited data).

The model is the paper's two-stage recourse problem, Eqs. (1)-(9) of
main.tex, exactly as built by experiments/revision_common.solve_model
(which itself is asserted to reproduce src/step2_freeze_model). This file
does NOT modify either of those files; it imports them read-only and
`self_check()` asserts that `solve_plan(mode="expected")` reproduces
`revision_common.solve_model` before any experiment is trusted.

What solve_plan adds (all optional; with the defaults it IS the paper's RP):
  * mode="expected"   risk-neutral recourse problem (the paper's RP)
  * mode="maxmin"     adjustable (two-stage) robust counterpart over a finite
                      scenario set, epigraph form (Ben-Tal et al. 2004):
                      max sum_g P_g t_g  s.t. t_g <= profit_xi for xi in g.
                      groups=None: one group, i.e. pure max-min profit.
  * mode="cvar"       (1-lam) E[profit] + lam CVaR_alpha(profit), lower tail,
                      Rockafellar-Uryasev linearisation.
  * chance constraint m_xi <= m_floor_xi + s + q_xi b_xi, sum pi b <= eps,
                      b binary (Luedtke-Ahmed scenario form).
  * per-scenario outsourced FE capacity  (scenario key "L_G": total dies)
  * per-scenario in-house FE capacity    (scenario key "L_F": dict per fab):
                      planned starts x_f (first stage, <= nominal L_F);
                      processed wafers r_f,xi = min(x_f, L_F,xi) enforced with
                      one binary per (fab, scenario) when L_F,xi < nominal;
                      wafer cost c_F charged on processed wafers r.
                      Without "L_F" in the scenarios r = x and the model is
                      unchanged.
  * per-fab FE yields  (scenario keys "fe_yield_FE1", "fe_yield_FE2"),
                      used only by the budgeted-uncertainty plan.
  * fix_x             first-stage wafer starts fixed (plan evaluation with
                      optimal recourse, exactly as EEV is computed).

All results are solver outputs (PuLP 3.3.0 + CBC). No number is hard-coded.
"""

import hashlib
import json
import os
import platform
import subprocess
import sys
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "experiments"))

import pulp  # noqa: E402
from pulp import (LpProblem, LpMaximize, LpVariable, LpBinary, lpSum,  # noqa: E402
                  value, LpStatus, PULP_CBC_CMD)

import revision_common as rc  # noqa: E402  (read-only reuse)
from revision_common import (FE_MEAN, BE_LO, BE_HI, HALF_GRID, base_inst,  # noqa: E402,F401
                             two_point, scenarios_2x2x2, max_die_requirement)

RESULTS = os.path.join(REPO, "results", "tsm_a")


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------
def _cbc_version():
    try:
        path = PULP_CBC_CMD().path
        out = subprocess.run([path, "-quit"], capture_output=True, text=True, timeout=20).stdout
        for line in out.splitlines():
            if line.strip().startswith("Version"):
                return line.split(":", 1)[1].strip()
    except Exception as exc:  # pragma: no cover
        return f"unknown ({exc!r})"
    return "unknown"


def _git(*args):
    try:
        return subprocess.run(["git", "-C", REPO] + list(args), capture_output=True,
                              text=True, timeout=20).stdout.strip()
    except Exception:
        return "unknown"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def write_run_json(out_dir, run_id, command, seed, t_start, t_end, extra=None):
    os.makedirs(out_dir, exist_ok=True)
    scripts = sorted(f for f in os.listdir(HERE) if f.endswith(".py"))
    meta = {
        "run_id": run_id,
        "command": command,
        "seed": seed,
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty_files": [l for l in _git("status", "--porcelain").splitlines() if l][:50],
        "note_git": ("code/tsm_a and results/tsm_a are new, uncommitted files; "
                     "script hashes below identify the exact code that ran"),
        "script_sha256": {s: sha256(os.path.join(HERE, s)) for s in scripts},
        "started": datetime.datetime.fromtimestamp(t_start).isoformat(timespec="seconds"),
        "finished": datetime.datetime.fromtimestamp(t_end).isoformat(timespec="seconds"),
        "runtime_seconds": round(t_end - t_start, 1),
        "solver": "CBC", "solver_version": _cbc_version(),
        "pulp_version": pulp.__version__,
        "python": platform.python_version(),
        "machine": f"{platform.system()} {platform.machine()}",
        "api_cost_usd": 0.0,
    }
    if extra:
        meta.update(extra)
    with open(os.path.join(out_dir, "run.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    return meta


# ---------------------------------------------------------------------------
# model
# ---------------------------------------------------------------------------
def solve_plan(inst, scenarios, mode="expected", fix_x=None, groups=None,
               lam=0.0, alpha=0.9, cc=None, tag="P", time_limit=None):
    """Build and solve the generalised model. Returns a result dict.

    cc : None or dict(eps=..., s=..., m_floor={scenario: units})
    groups : None or dict(scenario name -> group key), with group
             probability = sum of scenario probabilities in the group.
    """
    prob = LpProblem(f"TSA_{tag}", LpMaximize)
    FE, BE, G, A = inst["FE_set"], inst["BE_set"], inst["G_set"], inst["A_set"]
    S = [s["name"] for s in scenarios]
    sp = {s["name"]: s["prob"] for s in scenarios}
    by = {s["name"]: s["be_yield"] for s in scenarios}
    dm = {s["name"]: s["demand"] for s in scenarios}
    fy = {(s["name"], f): s.get(f"fe_yield_{f}", s.get("fe_yield")) for s in scenarios for f in FE}
    lg = {s["name"]: s.get("L_G") for s in scenarios}
    lf = {s["name"]: s.get("L_F") for s in scenarios}
    n = inst["n_f_i"]

    if fix_x is None:
        X = {f: LpVariable(f"XF_{f}", 0, inst["L_F"][f]) for f in FE}
    else:
        X = {f: LpVariable(f"XF_{f}", fix_x[f], fix_x[f]) for f in FE}
    O_G = {g: LpVariable(f"OG_{g}", 0, 1, LpBinary) for g in G}
    O_A = {a: LpVariable(f"OA_{a}", 0, 1, LpBinary) for a in A}

    idx = {s: i for i, s in enumerate(S)}
    XFK = {(s, f): LpVariable(f"XFK_{idx[s]}_{f}", 0) for s in S for f in FE}
    XGK = {(s, g): LpVariable(f"XGK_{idx[s]}_{g}", 0) for s in S for g in G}
    Z = {s: LpVariable(f"Z_{idx[s]}", 0) for s in S}
    XKB = {(s, b): LpVariable(f"XKB_{idx[s]}_{b}", 0) for s in S for b in BE}
    XKA = {(s, a): LpVariable(f"XKA_{idx[s]}_{a}", 0) for s in S for a in A}
    XBD = {(s, b): LpVariable(f"XBD_{idx[s]}_{b}", 0) for s in S for b in BE}
    XAD = {(s, a): LpVariable(f"XAD_{idx[s]}_{a}", 0) for s in S for a in A}
    M = {s: LpVariable(f"M_{idx[s]}", 0) for s in S}
    W = {s: LpVariable(f"W_{idx[s]}", 0) for s in S}

    # processed wafers: r = x unless the scenario carries its own FE capacity
    R = {}
    for s in S:
        for f in FE:
            if lf[s] is None or lf[s][f] >= inst["L_F"][f] - 1e-12:
                R[(s, f)] = X[f]
            else:
                r = LpVariable(f"R_{idx[s]}_{f}", 0)
                d = LpVariable(f"DL_{idx[s]}_{f}", 0, 1, LpBinary)
                big = inst["L_F"][f]
                prob += r <= X[f]
                prob += r <= lf[s][f]
                prob += r >= X[f] - big * d          # d = 0  ->  r >= x
                prob += r >= lf[s][f] - big * (1 - d)  # d = 1  ->  r >= L_F,xi
                R[(s, f)] = r

    def profit(s):
        return (inst["p_d"] * (dm[s] - M[s]) - inst["v_d"] * M[s]
                - inst["c_K"] * Z[s] - inst["c_D"] * W[s]
                - lpSum(inst["c_G"] * XGK[(s, g)] for g in G)
                - lpSum(inst["c_B"] * XKB[(s, b)] for b in BE)
                - lpSum(inst["c_A"] * XKA[(s, a)] for a in A)
                - lpSum(inst["c_F"] * R[(s, f)] for f in FE))

    P = {s: profit(s) for s in S}
    expected = lpSum(sp[s] * P[s] for s in S)

    if mode == "expected":
        prob += expected
    elif mode == "maxmin":
        if groups is None:
            groups = {s: "all" for s in S}
        keys = list(dict.fromkeys(groups[s] for s in S))
        gp = {k: sum(sp[s] for s in S if groups[s] == k) for k in keys}
        T = {k: LpVariable(f"T_{i}") for i, k in enumerate(keys)}
        for s in S:
            prob += T[groups[s]] <= P[s]
        prob += lpSum(gp[k] * T[k] for k in keys)
    elif mode == "cvar":
        eta = LpVariable("ETA")
        U = {s: LpVariable(f"U_{idx[s]}", 0) for s in S}
        for s in S:
            prob += U[s] >= eta - P[s]
        cvar = eta - (1.0 / (1.0 - alpha)) * lpSum(sp[s] * U[s] for s in S)
        prob += (1.0 - lam) * expected + lam * cvar
    else:
        raise ValueError(mode)

    if cc is not None:
        Bv = {s: LpVariable(f"B_{idx[s]}", 0, 1, LpBinary) for s in S}
        for s in S:
            prob += M[s] <= cc["m_floor"][s] + cc["s"] + dm[s] * Bv[s]
        prob += lpSum(sp[s] * Bv[s] for s in S) <= cc["eps"] + 1e-9

    for s in S:
        for f in FE:
            prob += XFK[(s, f)] <= fy[(s, f)] * n * R[(s, f)]
        for g in G:
            cap = inst["L_G"][g] if lg[s] is None else lg[s]
            prob += XGK[(s, g)] <= cap * O_G[g]
        prob += (lpSum(XFK[(s, f)] for f in FE) + lpSum(XGK[(s, g)] for g in G)
                 - lpSum(XKB[(s, b)] for b in BE) - lpSum(XKA[(s, a)] for a in A) - Z[s] == 0)
        for b in BE:
            prob += XKB[(s, b)] <= inst["L_B"][b]
            prob += XBD[(s, b)] <= by[s] * XKB[(s, b)]
        for a in A:
            prob += XKA[(s, a)] <= inst["L_A"][a] * O_A[a]
            prob += XAD[(s, a)] == XKA[(s, a)]
        prob += (lpSum(XBD[(s, b)] for b in BE) + lpSum(XAD[(s, a)] for a in A)
                 + M[s] - W[s] == dm[s])

    solver = PULP_CBC_CMD(msg=0, timeLimit=time_limit) if time_limit else PULP_CBC_CMD(msg=0)
    prob.solve(solver)
    v = lambda x: value(x) or 0.0
    status = LpStatus[prob.status]
    out = {"status": status, "obj": value(prob.objective)}
    if status != "Optimal":
        return out
    prof = {s: value(P[s]) for s in S}
    out.update({
        "X_F": {f: v(X[f]) for f in FE},
        "W_total": sum(v(X[f]) for f in FE),
        "exp_profit": sum(sp[s] * prof[s] for s in S),
        "profit": prof,
        "M": {s: v(M[s]) for s in S},
        "exp_unmet": sum(sp[s] * v(M[s]) for s in S),
        "exp_outsourced": sum(sp[s] * sum(v(XGK[(s, g)]) for g in G) for s in S),
        "dies_used": {s: sum(v(XKB[(s, b)]) for b in BE) + sum(v(XKA[(s, a)]) for a in A)
                      for s in S},
    })
    return out


def cvar_lower(values, probs, alpha=0.9):
    """Mean of the worst (1-alpha) probability mass of `values` (lower tail)."""
    tail = 1.0 - alpha
    acc, tot = 0.0, 0.0
    for v_, p_ in sorted(zip(values, probs)):
        take = min(p_, tail - acc)
        if take <= 0:
            break
        tot += take * v_
        acc += take
    return tot / tail


def evaluate_plan(inst, scenarios, x):
    """Fix wafer starts x, re-optimise recourse in every scenario (as for EEV)."""
    r = solve_plan(inst, scenarios, fix_x=x, tag="EVAL")
    if r["status"] != "Optimal":
        return r
    S = [s["name"] for s in scenarios]
    probs = [s["prob"] for s in scenarios]
    vals = [r["profit"][s] for s in S]
    r["worst_profit"] = min(vals)
    r["cvar90"] = cvar_lower(vals, probs, 0.9)
    return r


def ev_scenario(scenarios):
    m = lambda k: sum(s["prob"] * s[k] for s in scenarios)
    return [{"name": "EV", "prob": 1.0, "fe_yield": m("fe_yield"),
             "demand": m("demand"), "be_yield": m("be_yield")}]


def unmet_floor(inst, scenarios):
    """Unavoidable unmet demand per scenario: FE supply made non-binding
    (FE capacity 1e4 wafers, FE yield 1), solved, not assumed."""
    big = dict(inst)
    big["L_F"] = {f: 1e4 for f in inst["FE_set"]}
    out = {}
    for s in scenarios:
        sc = [dict(s, prob=1.0, fe_yield=1.0)]
        for f in inst["FE_set"]:
            sc[0].pop(f"fe_yield_{f}", None)
        sc[0].pop("L_F", None)
        r = solve_plan(big, sc, tag="FLOOR")
        out[s["name"]] = r["M"][s["name"]]
    return out


def crossing_up(xs, ys, level):
    """First upward crossing of `level` (linear interpolation, the rule of
    step5/step6 find_threshold and revision_common.crossing).
    Returns (value, note): note in {"", "below_grid", "never"}."""
    pts = [(x, y) for x, y in zip(xs, ys) if y is not None]
    if not pts:
        return None, "never"
    if pts[0][1] >= level:
        return None, "below_grid"
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if y0 < level <= y1:
            return x0 + (level - y0) / (y1 - y0) * (x1 - x0), ""
    return None, "never"


def self_check(tol=1e-4):
    """solve_plan must reproduce revision_common.solve_model (which is itself
    asserted against step2) for RP, EV and EEV, and the paper's baseline."""
    worst = rc.self_check()
    for (fl, fh) in [(0.80, 0.95), (0.697, 1.0), (0.60, 1.0), (0.865, 0.885)]:
        inst = base_inst()
        sc = scenarios_2x2x2(fl, fh, 600, 900, BE_LO, BE_HI)
        a = rc.solve_model(inst, sc, tag="A")
        b = solve_plan(inst, sc, tag="B")
        ev = rc.solve_model(inst, ev_scenario(sc), tag="EV")
        e1 = rc.solve_model(inst, sc, fix_xf=ev["X_F"], tag="E1")
        e2 = evaluate_plan(inst, sc, ev["X_F"])
        worst = max(worst, abs(a["obj"] - b["obj"]), abs(e1["obj"] - e2["obj"]))
    if worst > tol:
        raise AssertionError(f"solve_plan deviates from revision_common by {worst}")
    return worst
