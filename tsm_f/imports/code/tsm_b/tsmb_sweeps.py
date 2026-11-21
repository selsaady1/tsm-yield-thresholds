"""tsmb_sweeps.py: FE half-range sweeps of the single-period model with the
tsm_b extensions, and the cliff check (solved onset versus prediction).

A configuration is a dict:
  name, inst_over (dict of base_inst overrides), c_F_f (per-fab wafer cost or
  None), fe2_mean (None = both fabs share the FE yield), corr (bool),
  groups (tool-group data or None), cong (congestion dict or None).
"""
from tsmb_common import crossing, bisect_first
import revision_common as rc
import tsmb_static as ts

HALVES = sorted(set(rc.HALF_GRID + [0.075]))

# Tool groups: litho, etch, implant.  Loads in tool hours per wafer; capacities
# in tool hours per period, chosen so that the bottleneck of each fab equals
# the aggregate capacity of Table I (FE1: litho, 10 wafers; FE2: etch, 8
# wafers) and the other groups have 10% to 20% slack.
TOOL_GROUPS = {
    "load": {"litho": 1.0, "etch": 0.8, "implant": 0.5},
    "cap": {"FE1": {"litho": 10.0, "etch": 8.8, "implant": 6.0},     # 10, 11, 12 wafers
            "FE2": {"litho": 9.0, "etch": 6.4, "implant": 4.8}},     # 9, 8, 9.6 wafers
}
# share of the raw process time spent at each group (sums to one)
T0_SHARE = {"litho": 0.45, "etch": 0.35, "implant": 0.20}

C_W_BASE = 0.05 * 100 * 0.875   # c_K x n x mean FE yield: the die-bank holding
                                # cost of one wafer's good dies (4.375 per wafer-period)


def scen(cfg, h):
    inst = cfg["inst"]
    lo, hi = rc.two_point(rc.FE_MEAN, h)
    fe2 = None
    if cfg.get("fe2_mean") is not None:
        fe2 = rc.two_point(cfg["fe2_mean"], h)
    return ts.scenarios(lo, hi, inst["demand_lo"], inst["demand_hi"], rc.BE_LO, rc.BE_HI,
                        fe2=fe2, corr=cfg.get("corr", True)), (lo, hi), fe2


def kw(cfg):
    return {"cong": cfg.get("cong"), "groups": cfg.get("groups"), "c_F_f": cfg.get("c_F_f")}


def point(cfg, h):
    inst = cfg["inst"]
    sc, fe1, fe2 = scen(cfg, h)
    r = ts.evaluate(inst, sc, **kw(cfg))
    rp, ev, eev = r["rp"], r["ev"], r["eev"]
    W = lambda x: sum(x["X_F"].values())
    out = {"half": h, "fe1_lo": fe1[0], "fe1_hi": fe1[1],
           "fe2_lo": fe2[0] if fe2 else fe1[0], "fe2_hi": fe2[1] if fe2 else fe1[1],
           "clipped": int(rc.FE_MEAN + h > 1 + 1e-9), "ok": r["ok"],
           "rp_obj": r["rp_obj"], "eev_obj": r["eev_obj"], "ev_obj": ev["obj"],
           "vss": r["vss"], "pct_vss": r["pct_vss"],
           "rp_unmet": r["rp_unmet"], "eev_unmet": r["eev_unmet"], "unmet_gap": r["unmet_gap"],
           "rp_fe1": rp["X_F"]["FE1"], "rp_fe2": rp["X_F"]["FE2"],
           "ev_fe1": ev["X_F"]["FE1"], "ev_fe2": ev["X_F"]["FE2"],
           "rp_u1": rp["util"]["FE1"], "rp_u2": rp["util"]["FE2"],
           "ev_u1": ev["util"]["FE1"], "ev_u2": ev["util"]["FE2"],
           "rp_wafers": W(rp), "ev_wafers": W(ev), "hedge": W(rp) - W(ev),
           "rp_exp_outs": rp["exp_outs"], "eev_exp_outs": eev["exp_outs"]}
    if "ct_fe" in rp:
        out.update({"rp_ct1": rp["ct_fe"]["FE1"], "rp_ct2": rp["ct_fe"]["FE2"],
                    "ev_ct1": ev["ct_fe"]["FE1"], "ev_ct2": ev["ct_fe"]["FE2"],
                    "rp_wipcost": rp["wip_cost_fe"], "ev_wipcost": ev["wip_cost_fe"]})
    if "wip_cost_be" in rp:
        out.update({"rp_wipcost_be": rp["wip_cost_be"], "eev_wipcost_be": eev["wip_cost_be"]})
    out["_raw"] = r
    return out


def sweep(cfg, halves=HALVES, progress=None):
    rows = []
    for h in halves:
        rows.append(point(cfg, h))
        if progress:
            progress(f"{cfg['name']} h={h}")
    return rows


def cliff(cfg, rows):
    """Solved onset of the service gap and the prediction from the EV plan.

    Prediction (generalised condition (12)): the deterministic plan loses
    service once  sum_f n * y_lo,f * W^EV_f + L_G < N_max, with W^EV_f the
    expected-value plan's starts at fab f at that half-range and N_max solved.
    """
    inst = cfg["inst"]
    n = inst["n_f_i"]
    L_G = sum(inst["L_G"].values())
    sc0, _, _ = scen(cfg, 0.075)
    nmax = ts.n_max(inst, sc0, **kw(cfg))
    rows = [r for r in rows if r["ok"]]
    first = next((r["half"] for r in rows if r["unmet_gap"] > 1e-6), None)
    if first is None:
        solved = None
    else:
        prev = max([r["half"] for r in rows if r["half"] < first], default=0.0)
        solved = bisect_first(lambda h: point(cfg, h)["unmet_gap"] > 1e-6, prev, first)

    def short(h):
        sc, fe1, fe2 = scen(cfg, h)
        ev = ts.solve(inst, ts.ev_scenario(sc), tag="EVc", **kw(cfg))
        ylo = {"FE1": fe1[0], "FE2": (fe2 or fe1)[0]}
        supply = sum(n * ylo[f] * ev["X_F"][f] for f in inst["FE_set"])
        return supply + L_G < nmax - 1e-6
    pred = bisect_first(short, 0.0, 0.50)
    return {"N_max": nmax, "gap_onset_solved": solved, "gap_onset_pred": pred,
            "rho_err": (abs(solved - pred) if (solved is not None and pred is not None) else None)}


def summarize(cfg, rows):
    f = lambda c: ("below_grid" if c == "below_grid" else ("none" if c is None else round(c, 4)))
    at = lambda key, h=0.075: next(r[key] for r in rows if abs(r["half"] - h) < 1e-9)
    s = {"config": cfg["name"],
         "pct_vss_at_0.075": at("pct_vss"), "vss_at_0.075": at("vss"),
         "rp_u1_at_0.075": at("rp_u1"), "rp_u2_at_0.075": at("rp_u2"),
         "ev_u1_at_0.075": at("ev_u1"), "ev_u2_at_0.075": at("ev_u2"),
         "rp_wafers_at_0.075": at("rp_wafers"), "ev_wafers_at_0.075": at("ev_wafers"),
         "hedge_at_0.075": at("hedge"),
         "vss2_half": f(crossing(rows, "pct_vss", 2.0)),
         "vss15_half": f(crossing(rows, "pct_vss", 1.5)),
         "gap1_half": f(crossing(rows, "unmet_gap", 1.0)),
         "gap3_half": f(crossing(rows, "unmet_gap", 3.0)),
         "max_abs_util_diff_rp": max(abs(r["rp_u1"] - r["rp_u2"]) for r in rows),
         "max_abs_util_diff_ev": max(abs(r["ev_u1"] - r["ev_u2"]) for r in rows),
         "pct_vss_at_0.50": rows[-1]["pct_vss"], "gap_at_0.50": rows[-1]["unmet_gap"],
         "nonoptimal": ";".join(str(r["half"]) for r in rows if not r["ok"]) or "none"}
    if "rp_ct1" in rows[0]:
        s.update({"rp_ct1_at_0.075": at("rp_ct1"), "rp_ct2_at_0.075": at("rp_ct2"),
                  "ev_ct1_at_0.075": at("ev_ct1"), "ev_ct2_at_0.075": at("ev_ct2")})
    return s
