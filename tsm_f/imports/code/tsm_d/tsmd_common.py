"""
tsmd_common.py  (TSM-D, revision round of TSM-26-0314)

Shared helpers for the TSM-D runs. The optimisation model is the paper's model
as built by repo/experiments/revision_common.py (itself asserted to reproduce
repo/src/step2_freeze_model.py). Nothing here is a result: every number the
TSM-D scripts write is a CBC solve or a direct function of CBC solves.

Adds:
  * run_meta(): the run.json record required by the prompt (S4).
  * solve_lp_named(): the same model with the (inert) outsourcing binaries fixed
    at 1, as a pure LP with named constraints, so that slacks and shadow prices
    can be read. Its objective is asserted equal to revision_common.solve_model.
"""
import datetime
import hashlib
import json
import os
import platform
import subprocess
import sys
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
SANDBOX = os.path.abspath(os.path.join(HERE, "..", ".."))
REPO = os.path.join(SANDBOX, "repo")
sys.path[:0] = [os.path.join(REPO, "src"), os.path.join(REPO, "experiments")]

import pulp  # noqa: E402
from pulp import (LpProblem, LpMaximize, LpVariable, lpSum, value,  # noqa: E402
                  LpStatus, PULP_CBC_CMD)

import revision_common as rc  # noqa: E402

AZ = ZoneInfo("America/Phoenix")
CBC_OPTS = {"solver": "PULP_CBC_CMD", "msg": 0, "threads": 1,
            "gapRel": "CBC default (0, problems are LPs or MILPs with inert binaries; all solved to proven optimality)",
            "timeLimit": None}


def now():
    return datetime.datetime.now(AZ).isoformat(timespec="seconds")


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def cbc_version():
    try:
        exe = PULP_CBC_CMD().path
        out = subprocess.run([exe, "-quit"], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if line.strip().startswith("Version"):
                return line.split(":", 1)[1].strip() + f" ({exe} -> {os.path.realpath(exe)})"
    except Exception as exc:  # pragma: no cover
        return f"unknown ({exc!r})"
    return "unknown"


def run_dir(run_id):
    d = os.path.join(SANDBOX, "results", "tsm_d", run_id)
    os.makedirs(d, exist_ok=True)
    return d


def write_run_json(run_id, purpose, command, seed, started, t0, status, inputs, outputs,
                   scripts, notes=""):
    import time
    d = run_dir(run_id)
    rec = {
        "prompt_id": "tsm_d", "run_id": run_id, "purpose": purpose,
        "command": command, "cwd": os.getcwd(), "seed": seed,
        "started_at": started, "finished_at": now(),
        "runtime_s": round(time.time() - t0, 2), "status": status,
        "python": sys.version.split()[0], "pulp": pulp.__version__,
        "cbc": cbc_version(), "solver_options": CBC_OPTS,
        "platform": platform.platform(),
        "input_files": {os.path.relpath(p, SANDBOX): sha256(p) for p in inputs if os.path.exists(p)},
        "output_files": {os.path.relpath(p, SANDBOX): sha256(p) for p in outputs if os.path.exists(p)},
        "git_commit": "none (not a git repo)",
        "code_sha256": {os.path.relpath(p, SANDBOX): sha256(p) for p in scripts},
        "notes": notes,
    }
    with open(os.path.join(d, "run.json"), "w") as fh:
        json.dump(rec, fh, indent=1)
    return rec


def patch_clamp_fixed_first_stage():
    """PuLP reads CBC's solution file at limited precision, so an EV wafer start
    at a fractional fab capacity can be read as e.g. 10.209913 > L_F =
    10.2099127686, which makes the EEV problem (first stage fixed) infeasible.
    The wrapper clamps the fixed first stage to [0, L_F] (a change of at most
    1e-6 wafers) before rc.solve_model builds the EEV problem. It does not
    change the model; it only matters for non-integer capacities (r4)."""
    if getattr(rc, "_tsmd_clamped", False):
        return
    orig = rc.solve_model

    def wrapped(inst, scenarios, fix_xf=None, **kw):
        if fix_xf is not None:
            fix_xf = {f: min(max(0.0, x), inst["L_F"][f]) for f, x in fix_xf.items()}
        return orig(inst, scenarios, fix_xf=fix_xf, **kw)
    rc.solve_model = wrapped
    rc._tsmd_clamped = True


MODEL_FILES = [os.path.join(REPO, "experiments", "revision_common.py"),
               os.path.join(REPO, "src", "step2_freeze_model.py"),
               os.path.abspath(__file__)]


# ---------------------------------------------------------------------------
# LP with named constraints (outsourcing binaries fixed at 1; property (b))
# ---------------------------------------------------------------------------
def solve_lp_named(inst, scenarios, fix_xf=None):
    """Same model as revision_common.solve_model (nonanticipative=False) with
    o_g = o_a = 1. Returns objective, first stage, and per scenario primal
    values, slacks and shadow prices of the capacity constraints."""
    prob = LpProblem("SC_named", LpMaximize)
    FE, BE, G, A = inst["FE_set"], inst["BE_set"], inst["G_set"], inst["A_set"]
    S = [s["name"] for s in scenarios]
    sp = {s["name"]: s["prob"] for s in scenarios}
    fy = {s["name"]: s["fe_yield"] for s in scenarios}
    by = {s["name"]: s["be_yield"] for s in scenarios}
    dm = {s["name"]: s["demand"] for s in scenarios}
    n = inst["n_f_i"]
    if fix_xf is None:
        X = {f: LpVariable(f"X_{f}", 0) for f in FE}
    else:
        X = {f: LpVariable(f"X_{f}", fix_xf[f], fix_xf[f]) for f in FE}
    idx = {s: i for i, s in enumerate(S)}
    U = {(s, f): LpVariable(f"U_{idx[s]}_{f}", 0) for s in S for f in FE}
    Gv = {(s, g): LpVariable(f"G_{idx[s]}_{g}", 0) for s in S for g in G}
    Z = {s: LpVariable(f"Z_{idx[s]}", 0) for s in S}
    K = {(s, b): LpVariable(f"K_{idx[s]}_{b}", 0) for s in S for b in BE}
    Av = {(s, a): LpVariable(f"A_{idx[s]}_{a}", 0) for s in S for a in A}
    D = {(s, b): LpVariable(f"D_{idx[s]}_{b}", 0) for s in S for b in BE}
    M = {s: LpVariable(f"M_{idx[s]}", 0) for s in S}
    W = {s: LpVariable(f"W_{idx[s]}", 0) for s in S}
    prob += (lpSum(sp[s] * (inst["p_d"] * (dm[s] - M[s]) - inst["v_d"] * M[s]
                            - inst["c_K"] * Z[s] - inst["c_D"] * W[s]
                            - lpSum(inst["c_G"] * Gv[(s, g)] for g in G)
                            - lpSum(inst["c_B"] * K[(s, b)] for b in BE)
                            - lpSum(inst["c_A"] * Av[(s, a)] for a in A)) for s in S)
             - lpSum(inst["c_F"] * X[f] for f in FE))
    cons = {}
    for f in FE:
        cons[("fecap", f)] = X[f] <= inst["L_F"][f]
        prob += cons[("fecap", f)], f"fecap_{f}"
    for s in S:
        i = idx[s]
        for f in FE:
            prob += U[(s, f)] - fy[s] * n * X[f] <= 0, f"feyield_{i}_{f}"
        for g in G:
            cons[("gcap", s, g)] = Gv[(s, g)] <= inst["L_G"][g]
            prob += cons[("gcap", s, g)], f"gcap_{i}_{g}"
        prob += (lpSum(U[(s, f)] for f in FE) + lpSum(Gv[(s, g)] for g in G)
                 - lpSum(K[(s, b)] for b in BE) - lpSum(Av[(s, a)] for a in A) - Z[s] == 0), f"bank_{i}"
        for b in BE:
            prob += K[(s, b)] <= inst["L_B"][b], f"becap_{i}_{b}"
            prob += D[(s, b)] - by[s] * K[(s, b)] <= 0, f"beyield_{i}_{b}"
        for a in A:
            prob += Av[(s, a)] <= inst["L_A"][a], f"acap_{i}_{a}"
        prob += (lpSum(D[(s, b)] for b in BE) + lpSum(Av[(s, a)] for a in A)
                 + M[s] - W[s] == dm[s]), f"dem_{i}"
    prob.solve(PULP_CBC_CMD(msg=0, threads=1))
    v = lambda x: value(x) or 0.0
    C = prob.constraints
    pi = lambda name: (C[name].pi if C[name].pi is not None else 0.0)
    sl = lambda name: (C[name].slack if C[name].slack is not None else 0.0)
    out = {"status": LpStatus[prob.status], "obj": value(prob.objective),
           "X": {f: v(X[f]) for f in FE},
           "fecap_pi": {f: pi(f"fecap_{f}") for f in FE},
           "scen": []}
    for s in S:
        i = idx[s]
        out["scen"].append({
            "name": s, "prob": sp[s], "fe_yield": fy[s], "be_yield": by[s], "demand": dm[s],
            "dies_inhouse": sum(v(U[(s, f)]) for f in FE),
            "dies_inhouse_avail": sum(fy[s] * n * v(X[f]) for f in FE),
            "outsourced": sum(v(Gv[(s, g)]) for g in G),
            "L_G": sum(inst["L_G"][g] for g in G),
            "gcap_pi": sum(pi(f"gcap_{i}_{g}") for g in G),
            "released_be": sum(v(K[(s, b)]) for b in BE),
            "released_a": sum(v(Av[(s, a)]) for a in A),
            "becap_pi": sum(pi(f"becap_{i}_{b}") for b in BE),
            "becap_pi_max": max(pi(f"becap_{i}_{b}") for b in BE),
            "acap_pi": sum(pi(f"acap_{i}_{a}") for a in A),
            "bank": v(Z[s]), "bank_pi": pi(f"bank_{i}"),
            "unmet": v(M[s]), "excess": v(W[s]),
        })
    return out
