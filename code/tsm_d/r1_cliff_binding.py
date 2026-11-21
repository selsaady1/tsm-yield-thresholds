"""r1_cliff_binding.py (T3; R1.5, R1.0c): the service cliff as a capacity and
safety-stock effect, read from solver output.

For the base instance and FE half-ranges h = 0.005 .. 0.50 (step 0.005) we solve
EV, RP and EEV with the named-constraint LP (objective identical to the
published builder, checked in r0) and record, per plan and per scenario, wafer
starts, in-house dies, outsourced dies against L_G, dies released against
N_max = sum L_B + sum L_A, unmet demand, and the shadow prices of the
outsourced-FE (L_G), BE and assembler capacity constraints and of the fab
capacity. Event half-ranges are then located by bisection (tolerance 1e-5).

    nice -n 10 python code/tsm_d/r1_cliff_binding.py [--smoke]
"""
import csv, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tsmd_common as T
rc = T.rc

SMOKE = "--smoke" in sys.argv
RUN = "tsmd_r1_cliff_binding" + ("_smoke" if SMOKE else "")
BASE = rc.base_inst()
EPS = 1e-6


def solve_all(h, inst=BASE, mean=rc.FE_MEAN):
    lo, hi = rc.two_point(mean, h)
    sc = rc.scenarios_2x2x2(lo, hi, inst["demand_lo"], inst["demand_hi"], rc.BE_LO, rc.BE_HI)
    m = lambda k: sum(s["prob"] * s[k] for s in sc)
    ev = T.solve_lp_named(inst, [{"name": "EV", "prob": 1.0, "fe_yield": m("fe_yield"),
                                  "demand": m("demand"), "be_yield": m("be_yield")}])
    rp = T.solve_lp_named(inst, sc)
    eev = T.solve_lp_named(inst, sc, fix_xf=ev["X"])
    return lo, hi, ev, rp, eev


def worst(res):
    """Scenario with low FE yield, high demand, low BE yield (largest die need)."""
    return min(res["scen"], key=lambda s: (s["fe_yield"], -s["demand"], s["be_yield"]))


def exp_unmet(res):
    return sum(s["prob"] * s["unmet"] for s in res["scen"])


def events():
    """Bisection for the half-ranges at which constraints start to bind."""
    def first(pred, a=0.0, b=0.5, tol=1e-5):
        if not pred(b):
            return None
        if pred(a):
            return a
        while b - a > tol:
            mid = 0.5 * (a + b)
            if pred(mid):
                b = mid
            else:
                a = mid
        return 0.5 * (a + b)
    LG = sum(BASE["L_G"].values())
    nmax = sum(BASE["L_B"].values()) + sum(BASE["L_A"].values())
    LF = sum(BASE["L_F"].values())
    ev_ = {}
    ev_["eev_LG_binds"] = first(lambda h: max(s["outsourced"] for s in solve_all(h)[4]["scen"]) >= LG - EPS)
    ev_["eev_release_below_Nmax"] = first(lambda h: min(s["released_be"] + s["released_a"]
                                                         for s in solve_all(h)[4]["scen"]
                                                         if s["demand"] == BASE["demand_hi"] and s["be_yield"] == rc.BE_LO) < nmax - EPS)
    ev_["service_gap_opens"] = first(lambda h: exp_unmet(solve_all(h)[4]) - exp_unmet(solve_all(h)[3]) > EPS)
    ev_["rp_fe_capacity_binds"] = first(lambda h: sum(solve_all(h)[3]["X"].values()) >= LF - EPS)
    ev_["rp_LG_binds"] = first(lambda h: max(s["outsourced"] for s in solve_all(h)[3]["scen"]) >= LG - EPS)
    base_rp_unmet = exp_unmet(solve_all(0.01)[3])
    ev_["rp_unmet_rises"] = first(lambda h: exp_unmet(solve_all(h)[3]) > base_rp_unmet + EPS)
    return ev_


def main():
    t0, started = time.time(), T.now()
    d = T.run_dir(RUN)
    log = open(os.path.join(d, "progress.log"), "w")
    halves = [round(0.005 * i, 4) for i in range(1, 101)]
    if SMOKE:
        halves = [0.05, 0.15, 0.2, 0.3, 0.45]
    LG = sum(BASE["L_G"].values())
    nmax = sum(BASE["L_B"].values()) + sum(BASE["L_A"].values())
    rows, scen_rows = [], []
    statuses = set()
    for h in halves:
        lo, hi, ev, rp, eev = solve_all(h)
        statuses |= {ev["status"], rp["status"], eev["status"]}
        w_ev, w_rp = sum(ev["X"].values()), sum(rp["X"].values())
        we, wr = worst(eev), worst(rp)
        rows.append({
            "half": h, "fe_lo": lo, "fe_hi": hi, "clipped": int(rc.FE_MEAN + h > 1 + 1e-9),
            "ev_wafers": round(w_ev, 6), "rp_wafers": round(w_rp, 6),
            "hedge_wafers": round(w_rp - w_ev, 6),
            "hedge_dies_at_low_yield": round((w_rp - w_ev) * lo * BASE["n_f_i"], 4),
            "rp_fecap_shadow": round(sum(rp["fecap_pi"].values()), 6),
            "eev_low_inhouse_plus_LG": round(BASE["n_f_i"] * lo * w_ev + LG, 4),
            "N_max": nmax,
            "eev_worst_outsourced": round(we["outsourced"], 4), "L_G": LG,
            "eev_worst_released": round(we["released_be"] + we["released_a"], 4),
            "eev_worst_unmet": round(we["unmet"], 4),
            "eev_worst_LG_shadow_cond": round(we["gcap_pi"] / we["prob"], 6),
            "eev_worst_BE_shadow_cond": round(we["becap_pi_max"] / we["prob"], 6),
            "eev_worst_A_shadow_cond": round(we["acap_pi"] / we["prob"], 6),
            "rp_worst_outsourced": round(wr["outsourced"], 4),
            "rp_worst_released": round(wr["released_be"] + wr["released_a"], 4),
            "rp_worst_unmet": round(wr["unmet"], 4),
            "rp_worst_LG_shadow_cond": round(wr["gcap_pi"] / wr["prob"], 6),
            "rp_worst_BE_shadow_cond": round(wr["becap_pi_max"] / wr["prob"], 6),
            "eev_exp_unmet": round(exp_unmet(eev), 4), "rp_exp_unmet": round(exp_unmet(rp), 4),
            "service_gap": round(exp_unmet(eev) - exp_unmet(rp), 4),
            "rp_obj": round(rp["obj"], 4), "eev_obj": round(eev["obj"], 4),
            "eev_n_scen_LG_binding": sum(1 for s in eev["scen"] if s["outsourced"] >= LG - EPS),
            "rp_n_scen_LG_binding": sum(1 for s in rp["scen"] if s["outsourced"] >= LG - EPS),
        })
        for plan, res in (("EEV", eev), ("RP", rp)):
            for s in res["scen"]:
                scen_rows.append({"half": h, "plan": plan, "scenario": s["name"],
                                  "fe_yield": s["fe_yield"], "demand": s["demand"], "be_yield": s["be_yield"],
                                  "dies_inhouse": round(s["dies_inhouse"], 4),
                                  "outsourced": round(s["outsourced"], 4),
                                  "LG_slack": round(LG - s["outsourced"], 4),
                                  "LG_shadow_cond": round(s["gcap_pi"] / s["prob"], 6),
                                  "released": round(s["released_be"] + s["released_a"], 4),
                                  "Nmax_slack": round(nmax - s["released_be"] - s["released_a"], 4),
                                  "BE_shadow_cond": round(s["becap_pi_max"] / s["prob"], 6),
                                  "A_shadow_cond": round(s["acap_pi"] / s["prob"], 6),
                                  "bank": round(s["bank"], 4), "unmet": round(s["unmet"], 4)})
        log.write(f"{T.now()} h={h} done\n"); log.flush()
    ev_ = events()
    log.write(f"{T.now()} events {ev_}\n"); log.close()
    outs = []
    for name, data in (("cliff_binding_sweep.csv", rows), ("cliff_binding_by_scenario.csv", scen_rows),
                       ("cliff_events.csv", [{"event": k, "half": ("NA" if v is None else f"{v:.5f}")}
                                             for k, v in ev_.items()])):
        p = os.path.join(d, name)
        with open(p, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0]))
            w.writeheader(); w.writerows(data)
        outs.append(p)
    status = "OK" if statuses == {"Optimal"} else "FAILED"
    print("events:", ev_, "statuses:", statuses)
    T.write_run_json(RUN, "T3 (R1.5, R1.0c): slacks and shadow prices of L_G, BE/assembler capacity and fab capacity versus FE half-range on the base instance",
                     "nice -n 10 python code/tsm_d/r1_cliff_binding.py" + (" --smoke" if SMOKE else ""),
                     "none (deterministic LP)", started, t0, status, T.MODEL_FILES, outs,
                     [os.path.abspath(__file__)] + T.MODEL_FILES,
                     notes="shadow prices are CBC row duals of the LP with o_g=o_a=1, divided by the scenario probability (conditional value of one more unit in that scenario); duals of degenerate LPs need not be unique, so binding status is read from slacks and the dual is reported only as supporting evidence.")


if __name__ == "__main__":
    main()
