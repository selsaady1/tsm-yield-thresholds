"""
t2_paradigms.py  (TSM-A, reviewer item R1.3 / JZ.3)   run_id: t2_paradigms
==========================================================================
Robust, chance-constrained and risk-averse plans on the paper's base
instance, over the same FE half-range sweep as Steps 5-6 (h = 0.01..0.50,
FE mean 0.875, clipping as in Eq. (11); BE 0.70/0.90; demand 600/900).

Every plan fixes the wafer starts (first stage). It is then EVALUATED exactly
as the paper evaluates the deterministic plan (EEV): the wafer starts are
fixed and the recourse is re-optimised in each of the 8 scenarios. So all
plans are compared on the same footing (risk-neutral expected profit under
the paper's scenario set), and in addition on worst-case profit, CVaR_0.9 of
profit and the probability of an avoidable shortfall.

Plans
  RP        risk-neutral recourse problem (the paper's stochastic plan)
  EEV       expected-value (deterministic) plan
  BOX_Y     static box-robust (Soyster 1973): deterministic plan with every
            yield at its lower bound (FE y_lo, BE 0.70), demand at its mean
  BOX_YD    as BOX_Y with demand also at its upper level (900)
  ARO_ALL   adjustable robust over the 8 scenarios (Ben-Tal et al. 2004):
            max over wafer starts of min over scenarios of profit with
            scenario-wise recourse (epigraph MILP)
  ARO_Y     adjustable robust in the yields only: for each demand level the
            worst case over the 4 yield combinations, expectation over demand
  BUD_G{0..3} budgeted uncertainty (Bertsimas-Sim 2004) over the three
            independent uncertain yields (FE1, FE2, BE): nominal = mean,
            deviation to the low level, at most Gamma deviate; worst case
            over the vertices of the budget set, expectation over demand
  CC_e{0,0.125,0.25} scenario chance constraint (Charnes-Cooper 1959;
            Luedtke-Ahmed 2008): max expected profit s.t.
            P(avoidable shortfall <= s) >= 1-eps, s = 0, binary indicators.
            Avoidable shortfall = unmet demand above the scenario's floor
            (unmet demand with unlimited FE supply, solved).
  CVAR_l{0,0.5,1} max (1-lam) E[profit] + lam CVaR_0.9(profit)
            (Rockafellar-Uryasev 2000); lam=0 must equal RP (checked).

Two wafer costs: the base c_F = 1.50 and c_F = 15 (hedging expensive), the
second as a sensitivity only.

    cd tsm-yield-thresholds && .venv/bin/python code/tsm_a/t2_paradigms.py [--smoke]
Outputs: results/tsm_a/t2_paradigms/{points.csv, crossings.csv, run.json, log.txt}
"""
import csv
import itertools
import os
import sys
import time

from tsa_common import (RESULTS, FE_MEAN, HALF_GRID, base_inst, two_point, scenarios_2x2x2,
                        solve_plan, evaluate_plan, ev_scenario, unmet_floor, crossing_up,
                        self_check, write_run_json)

SMOKE = "--smoke" in sys.argv
RUN_ID = "t2_paradigms"
SEED = 0  # deterministic (no sampling)
OUT = os.path.join(RESULTS, RUN_ID + ("_smoke" if SMOKE else ""))
HALVES = [0.05, 0.15, 0.25, 0.35, 0.45] if SMOKE else HALF_GRID
CFS = [1.5] if SMOKE else [1.5, 15.0]
D_LO, D_HI, B_LO, B_HI = 600, 900, 0.70, 0.90
EPS = 1e-6


def budget_scenarios(fe_nom, fe_lo, gamma):
    """Vertices of the budget set over (FE1, FE2, BE) with sum(zeta) <= gamma,
    crossed with the two demand levels; grouped by demand."""
    be_nom = (B_LO + B_HI) / 2
    sc, groups = [], {}
    for q in (D_LO, D_HI):
        verts = [z for z in itertools.product((0, 1), repeat=3) if sum(z) <= gamma]
        for z in verts:
            name = f"D{q}_z{''.join(map(str, z))}"
            sc.append({"name": name, "prob": 0.5 / len(verts), "demand": q,
                       "fe_yield": fe_nom,
                       "fe_yield_FE1": fe_lo if z[0] else fe_nom,
                       "fe_yield_FE2": fe_lo if z[1] else fe_nom,
                       "be_yield": B_LO if z[2] else be_nom})
            groups[name] = q
    return sc, groups


def plans_at(inst, lo, hi, floor):
    sc = scenarios_2x2x2(lo, hi, D_LO, D_HI, B_LO, B_HI)
    fe_nom = (lo + hi) / 2
    plans = {}

    def keep(name, r):
        plans[name] = r if r.get("status") == "Optimal" else {"status": r.get("status")}

    keep("RP", solve_plan(inst, sc, tag="RP"))
    keep("EEV", solve_plan(inst, ev_scenario(sc), tag="EV"))
    keep("BOX_Y", solve_plan(inst, [{"name": "BOXY", "prob": 1.0, "fe_yield": lo,
                                     "demand": (D_LO + D_HI) / 2, "be_yield": B_LO}], tag="BOXY"))
    keep("BOX_YD", solve_plan(inst, [{"name": "BOXYD", "prob": 1.0, "fe_yield": lo,
                                      "demand": D_HI, "be_yield": B_LO}], tag="BOXYD"))
    keep("ARO_ALL", solve_plan(inst, sc, mode="maxmin", tag="AROALL"))
    keep("ARO_Y", solve_plan(inst, sc, mode="maxmin",
                             groups={s["name"]: s["demand"] for s in sc}, tag="AROY"))
    for g in (0, 1, 2, 3):
        bsc, grp = budget_scenarios(fe_nom, lo, g)
        keep(f"BUD_G{g}", solve_plan(inst, bsc, mode="maxmin", groups=grp, tag=f"BUD{g}"))
    for e in (0.0, 0.125, 0.25):
        keep(f"CC_e{e:g}", solve_plan(inst, sc, cc={"eps": e, "s": 0.0, "m_floor": floor},
                                      tag=f"CC{e}"))
    for lam in (0.0, 0.5, 1.0):
        keep(f"CVAR_l{lam:g}", solve_plan(inst, sc, mode="cvar", lam=lam, alpha=0.9,
                                          tag=f"CV{lam}"))
    return sc, plans


def main():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    log = open(os.path.join(OUT, "log.txt"), "w")

    def say(msg):
        print(msg, flush=True)
        log.write(msg + "\n")

    say(f"t2_paradigms ({'SMOKE' if SMOKE else 'FULL'}) -> {OUT}")
    say(f"self-check vs revision_common/step2: max |dev| = {self_check():.2e}")
    points = []
    n_bad = 0
    for cf in CFS:
        inst = base_inst(c_F=cf)
        floor = unmet_floor(inst, scenarios_2x2x2(0.8, 0.95, D_LO, D_HI, B_LO, B_HI))
        say(f"c_F={cf}: unmet floor per scenario {sorted(set(round(v, 4) for v in floor.values()))}")
        for h in HALVES:
            lo, hi = two_point(FE_MEAN, h)
            sc, plans = plans_at(inst, lo, hi, floor)
            rp = evaluate_plan(inst, sc, plans["RP"]["X_F"])
            eev = evaluate_plan(inst, sc, plans["EEV"]["X_F"])
            for name, p in plans.items():
                rec = {"c_F": cf, "half": h, "fe_lo": lo, "fe_hi": hi,
                       "clipped": int(FE_MEAN + h > 1 + 1e-9), "method": name,
                       "status": p.get("status")}
                if p.get("status") != "Optimal":
                    n_bad += 1
                    points.append(rec)
                    continue
                ev = evaluate_plan(inst, sc, p["X_F"])
                if ev.get("status") != "Optimal":
                    rec["status"] = "eval_" + str(ev.get("status"))
                    n_bad += 1
                    points.append(rec)
                    continue
                p_short = sum(s["prob"] for s in sc
                              if ev["M"][s["name"]] > floor[s["name"]] + EPS)
                rec.update({
                    "model_obj": p["obj"], "wafers": p["W_total"],
                    "wafers_FE1": p["X_F"]["FE1"], "wafers_FE2": p["X_F"]["FE2"],
                    "exp_profit": ev["exp_profit"], "exp_unmet": ev["exp_unmet"],
                    "worst_profit": ev["worst_profit"], "cvar90": ev["cvar90"],
                    "p_avoidable_short": p_short,
                    "exp_outsourced": ev["exp_outsourced"],
                    "pct_gap_to_rp": 100 * (rp["exp_profit"] - ev["exp_profit"]) / rp["exp_profit"],
                    "pct_benefit_over_det": 100 * (ev["exp_profit"] - eev["exp_profit"]) / rp["exp_profit"],
                    "svc_gap_vs_rp": ev["exp_unmet"] - rp["exp_unmet"],
                    "svc_gain_vs_det": eev["exp_unmet"] - ev["exp_unmet"],
                    "pct_worst_benefit_over_det": 100 * (ev["worst_profit"] - eev["worst_profit"]) / abs(eev["worst_profit"]),
                    "pct_cvar_benefit_over_det": 100 * (ev["cvar90"] - eev["cvar90"]) / abs(eev["cvar90"]),
                })
                points.append(rec)
            r = {p["method"]: p for p in points if p["c_F"] == cf and p["half"] == h}
            say(f"  cF={cf:<4g} h={h:.2f} " + " ".join(
                f"{m}:{r[m]['pct_gap_to_rp']:.2f}%" if "pct_gap_to_rp" in r[m] else f"{m}:{r[m]['status']}"
                for m in ("EEV", "BOX_Y", "ARO_ALL", "ARO_Y", "BUD_G1", "CC_e0", "CVAR_l1")))
            # sanity: CVaR with lam=0 is the RP
            if "exp_profit" in r["CVAR_l0"] and abs(r["CVAR_l0"]["exp_profit"] - r["RP"]["exp_profit"]) > 1e-4:
                say(f"  WARNING CVaR(lam=0) != RP at cF={cf} h={h}")

    keys = ["c_F", "half", "fe_lo", "fe_hi", "clipped", "method", "status", "model_obj", "wafers",
            "wafers_FE1", "wafers_FE2", "exp_profit", "exp_unmet", "worst_profit", "cvar90",
            "p_avoidable_short", "exp_outsourced", "pct_gap_to_rp", "pct_benefit_over_det",
            "svc_gap_vs_rp", "svc_gain_vs_det", "pct_worst_benefit_over_det",
            "pct_cvar_benefit_over_det"]
    with open(os.path.join(OUT, "points.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for p in points:
            w.writerow({k: (f"{p[k]:.6f}" if isinstance(p.get(k), float) else p.get(k, "NA"))
                        for k in keys})

    # crossings per method
    cross = []
    methods = list(dict.fromkeys(p["method"] for p in points))
    for cf in CFS:
        for m in methods:
            rows = [p for p in points if p["c_F"] == cf and p["method"] == m]
            xs = [p["half"] for p in rows]
            g = lambda k: [p.get(k) for p in rows]
            c_gap, n_gap = crossing_up(xs, g("pct_gap_to_rp"), 2.0)
            c_svc, n_svc = crossing_up(xs, g("svc_gap_vs_rp"), 1.0)
            onset = next((p["half"] for p in rows if (p.get("svc_gap_vs_rp") or 0) > EPS), None)
            c_ben, n_ben = crossing_up(xs, g("pct_benefit_over_det"), 2.0)
            c_wst, n_wst = crossing_up(xs, g("pct_worst_benefit_over_det"), 2.0)
            c_cvr, n_cvr = crossing_up(xs, g("pct_cvar_benefit_over_det"), 2.0)
            infeas = [p["half"] for p in rows if p.get("status") != "Optimal"]
            f = lambda c, n: f"{c:.4f}" if c is not None else n
            cross.append({"c_F": cf, "method": m,
                          "loss_vs_rp_gt2pct_half": f(c_gap, n_gap),
                          "svc_gap_vs_rp_gt1_half": f(c_svc, n_svc),
                          "svc_gap_vs_rp_first_grid_half": f"{onset:.2f}" if onset is not None else "never",
                          "benefit_over_det_gt2pct_half": f(c_ben, n_ben),
                          "worstcase_benefit_over_det_gt2pct_half": f(c_wst, n_wst),
                          "cvar_benefit_over_det_gt2pct_half": f(c_cvr, n_cvr),
                          "n_grid": len(rows),
                          "infeasible_or_failed_halves": ";".join(f"{x:.2f}" for x in infeas) or "none"})
    with open(os.path.join(OUT, "crossings.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cross[0].keys()))
        w.writeheader()
        w.writerows(cross)
    for c in cross:
        say("  " + " ".join(f"{k}={v}" for k, v in c.items()))
    say(f"non-optimal (status recorded, no value written): {n_bad}")
    say(f"done in {time.time() - t0:.0f} s")
    log.close()
    write_run_json(OUT, RUN_ID + ("_smoke" if SMOKE else ""),
                   "cd tsm-yield-thresholds && .venv/bin/python code/tsm_a/t2_paradigms.py"
                   + (" --smoke" if SMOKE else ""), SEED, t0, time.time(),
                   {"n_points": len(points), "n_non_optimal": n_bad})


if __name__ == "__main__":
    main()
