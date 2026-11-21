"""summarize.py: turn the TSM-D run files into the NUMBERS REGISTRY entries,
the generated tables, and the figures. Reads only results/tsm_d/<run_id>/.

    python code/tsm_d/summarize.py              # write everything
    python code/tsm_d/summarize.py --print KEY  # print one value from the run files
"""
import csv, json, math, os, shutil, statistics, sys, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tsmd_common as T

SB = T.SANDBOX
RES = os.path.join(SB, "results", "tsm_d")
OUT = os.path.join(SB, "OUT")
PAPER = os.path.join(SB, "revision", "paper")
RUN = "tsmd_summary"


def rcsv(run, name):
    with open(os.path.join(RES, run, name)) as fh:
        return list(csv.DictReader(fh))


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


ENTRIES = []


def add(key, value, display, meaning, run, file, row, col, unit="", typ="number", decimals=None, rule=None):
    e = {"key": key, "display": display, "value": value, "decimals": decimals, "unit": unit, "type": typ,
         "meaning": meaning, "producer": "tsm_d",
         "source": {"run": f"results/tsm_d/{run}/", "file": file, "row": row, "col": col},
         "recompute": f"python code/tsm_d/summarize.py --print {key}"}
    if rule:
        e["rule"] = rule
    ENTRIES.append(e)


def f3(x):
    return f"{x:.3f}"


def pct(k, n):
    v = 100.0 * k / n
    return v, (f"{v:.0f}" if abs(v - round(v)) < 1e-9 else f"{v:.1f}")


def build_numbers():
    # ---------------- r1: cliff mechanism -------------------------------
    ev = {r["event"]: num(r["half"]) for r in rcsv("tsmd_r1_cliff_binding", "cliff_events.csv")}
    add("TSMD_cliff_bind_hr", ev["eev_LG_binds"], f3(ev["eev_LG_binds"]),
        "FE half-range at which, in the deterministic (EEV) plan, outsourced FE capacity L_G becomes binding and dies released fall below N_max (same point as the service-gap onset)",
        "tsmd_r1_cliff_binding", "cliff_events.csv", "event=eev_LG_binds", "half", "FE half-range", decimals=3)
    for k, ek, m in (("TSMD_cliff_gap_hr", "service_gap_opens", "service-gap onset (bisection) on the base instance"),
                     ("TSMD_cliff_rpcap_hr", "rp_fe_capacity_binds", "half-range at which the stochastic plan's wafer starts reach total fab capacity (18 wafers)"),
                     ("TSMD_cliff_rpLG_hr", "rp_LG_binds", "half-range at which the stochastic plan's outsourcing reaches L_G in its worst scenario (and its own unmet demand rises)")):
        add(k, ev[ek], f3(ev[ek]), m, "tsmd_r1_cliff_binding", "cliff_events.csv", f"event={ek}", "half", "FE half-range", decimals=3)
    sw = rcsv("tsmd_r1_cliff_binding", "cliff_binding_sweep.csv")
    row = lambda h: next(r for r in sw if abs(float(r["half"]) - h) < 1e-9)
    r016, r010, r020 = row(0.16), row(0.10), row(0.20)
    add("TSMD_cliff_shadow_be_before", num(r010["eev_worst_BE_shadow_cond"]), f"{num(r010['eev_worst_BE_shadow_cond']):.2f}",
        "shadow price of one BE facility's capacity in the EEV worst scenario (low FE yield, high demand, low BE yield) at half-range 0.10, before the cliff, per die and conditional on the scenario",
        "tsmd_r1_cliff_binding", "cliff_binding_sweep.csv", "half=0.1", "eev_worst_BE_shadow_cond", "$ per die", decimals=2)
    add("TSMD_cliff_shadow_lg_before", num(r010["eev_worst_LG_shadow_cond"]), f"{num(r010['eev_worst_LG_shadow_cond']):.0f}",
        "shadow price of L_G in the EEV worst scenario at half-range 0.10 (before the cliff)",
        "tsmd_r1_cliff_binding", "cliff_binding_sweep.csv", "half=0.1", "eev_worst_LG_shadow_cond", "$ per die", decimals=0)
    add("TSMD_cliff_shadow_lg_after", num(r020["eev_worst_LG_shadow_cond"]), f"{num(r020['eev_worst_LG_shadow_cond']):.2f}",
        "shadow price of L_G in the EEV worst scenario at half-range 0.20, after the cliff, per die and conditional on the scenario",
        "tsmd_r1_cliff_binding", "cliff_binding_sweep.csv", "half=0.2", "eev_worst_LG_shadow_cond", "$ per die", decimals=2)
    add("TSMD_cliff_shadow_be_after", num(r020["eev_worst_BE_shadow_cond"]), f"{num(r020['eev_worst_BE_shadow_cond']):.0f}",
        "shadow price of BE capacity in the EEV worst scenario at half-range 0.20 (after the cliff)",
        "tsmd_r1_cliff_binding", "cliff_binding_sweep.csv", "half=0.2", "eev_worst_BE_shadow_cond", "$ per die", decimals=0)
    n = 100
    rp_low = n * float(r016["fe_lo"]) * float(r016["rp_wafers"])
    ev_low = n * float(r016["fe_lo"]) * float(r016["ev_wafers"])
    add("TSMD_cliff_rp_wafers_016", num(r016["rp_wafers"]), f"{num(r016['rp_wafers']):.2f}",
        "stochastic-plan wafer starts at half-range 0.16 (just before the cliff)", "tsmd_r1_cliff_binding",
        "cliff_binding_sweep.csv", "half=0.16", "rp_wafers", "wafers", decimals=2)
    add("TSMD_cliff_ev_wafers_016", num(r016["ev_wafers"]), f"{num(r016['ev_wafers']):.2f}",
        "expected-value-plan wafer starts at half-range 0.16", "tsmd_r1_cliff_binding",
        "cliff_binding_sweep.csv", "half=0.16", "ev_wafers", "wafers", decimals=2)
    add("TSMD_cliff_rp_lowdies_016", rp_low, f"{rp_low:,.0f}".replace(",", "{,}"),
        "in-house dies of the stochastic plan at the low FE yield, half-range 0.16: n*y_lo*W_RP", "tsmd_r1_cliff_binding",
        "cliff_binding_sweep.csv", "half=0.16", "100*fe_lo*rp_wafers", "dies", decimals=0)
    add("TSMD_cliff_ev_lowdies_016", ev_low, f"{ev_low:.1f}",
        "in-house dies of the deterministic plan at the low FE yield, half-range 0.16: n*y_lo*W_EV", "tsmd_r1_cliff_binding",
        "cliff_binding_sweep.csv", "half=0.16", "100*fe_lo*ev_wafers", "dies", decimals=1)
    add("TSMD_cliff_rp_worst_outs_016", num(r016["rp_worst_outsourced"]), f"{num(r016['rp_worst_outsourced']):.0f}",
        "dies the stochastic plan buys outside in its worst scenario at half-range 0.16", "tsmd_r1_cliff_binding",
        "cliff_binding_sweep.csv", "half=0.16", "rp_worst_outsourced", "dies", decimals=0)
    add("TSMD_cliff_ev_worst_outs_016", num(r016["eev_worst_outsourced"]), f"{num(r016['eev_worst_outsourced']):.1f}",
        "dies the deterministic plan buys outside in its worst scenario at half-range 0.16", "tsmd_r1_cliff_binding",
        "cliff_binding_sweep.csv", "half=0.16", "eev_worst_outsourced", "dies", decimals=1)

    # ---------------- r2: two-point versus other shapes ------------------
    ms = rcsv("tsmd_r2_matched_var", "matched_summary.csv")
    g = lambda fam, K: next(r for r in ms if r["family"] == fam and int(r["K"]) == K)
    tp, u7, b7 = g("two_point", 2), g("uniform", 7), g("beta22", 7)
    u15, b15, bms = g("uniform", 15), g("beta22", 15), g("beta_mean_sd", 7)
    for key, r, col, mean, unit in (
            ("TSMD_tp_thr_half", tp, "vss2_half", "two-point: half-range at the 2% crossing", "FE half-range"),
            ("TSMD_tp_thr_sd", tp, "vss2_sd", "two-point: realised standard deviation at the 2% crossing", "FE yield sd"),
            ("TSMD_unif7_thr_half", u7, "vss2_half", "uniform on the same interval (7 points): half-range at the 2% crossing", "FE half-range"),
            ("TSMD_unif7_thr_sd", u7, "vss2_sd", "uniform (7 points): realised sd at the 2% crossing", "FE yield sd"),
            ("TSMD_beta22_7_thr_half", b7, "vss2_half", "Beta(2,2) on the same interval (7 points): half-range at the 2% crossing", "FE half-range"),
            ("TSMD_beta22_7_thr_sd", b7, "vss2_sd", "Beta(2,2) (7 points): realised sd at the 2% crossing", "FE yield sd"),
            ("TSMD_unif15_thr_half", u15, "vss2_half", "uniform (15 points): half-range at the 2% crossing", "FE half-range"),
            ("TSMD_beta22_15_thr_half", b15, "vss2_half", "Beta(2,2) (15 points): half-range at the 2% crossing", "FE half-range"),
            ("TSMD_betams_thr_sigma", bms, "vss2_sigma", "Beta with mean 0.875 and sd sigma (7 points): sigma at the 2% crossing", "FE yield sd"),
            ("TSMD_betams_thr_sd", bms, "vss2_sd", "same Beta: realised sd of the 7 points at the 2% crossing", "FE yield sd"),
            ("TSMD_tp_onset_half", tp, "onset_half", "two-point: service-gap onset half-range", "FE half-range"),
            ("TSMD_unif7_onset_half", u7, "onset_half", "uniform (7 points): service-gap onset half-range", "FE half-range"),
            ("TSMD_beta22_7_onset_half", b7, "onset_half", "Beta(2,2) (7 points): service-gap onset half-range", "FE half-range")):
        add(key, num(r[col]), f3(num(r[col])), mean, "tsmd_r2_matched_var", "matched_summary.csv",
            f"family={r['family']},K={r['K']}", col, unit, decimals=3)
    ratios = [num(r["onset_lowest_over_mean"]) for r in ms if num(r["onset_lowest_over_mean"]) is not None]
    add("TSMD_matched_onset_ratio_min", min(ratios), f3(min(ratios)),
        "smallest (lowest support point / mean) at the service-gap onset over all distribution families",
        "tsmd_r2_matched_var", "matched_summary.csv", "all families", "onset_lowest_over_mean", "ratio", decimals=3)
    add("TSMD_matched_onset_ratio_max", max(ratios), f3(max(ratios)),
        "largest (lowest support point / mean) at the service-gap onset over all distribution families",
        "tsmd_r2_matched_var", "matched_summary.csv", "all families", "onset_lowest_over_mean", "ratio", decimals=3)
    vd = {r["key"]: r["value"] for r in rcsv("tsmd_r2_matched_var", "matched_verdict.csv")}
    add("TSMD_tp_matchedvar", vd["TSMD_tp_matchedvar"], vd["TSMD_tp_matchedvar"],
        "whether the matched-variance comparison supports calling the two-point threshold conservative",
        "tsmd_r2_matched_var", "matched_verdict.csv", "key=TSMD_tp_matchedvar", "value", typ="text", rule=vd["rule"])
    sup = "supports" if vd["two_point_crosses_first_at_matched_support"] == "1" else "does not support"
    add("TSMD_tp_matchedsupport", sup, sup,
        "whether the matched-support (same interval) comparison supports calling the two-point threshold conservative",
        "tsmd_r2_matched_var", "matched_verdict.csv", "key=two_point_crosses_first_at_matched_support", "value", typ="text",
        rule="'supports' if the two-point 2% crossing (half-range) is not larger than any other family's on the same interval")

    # ---------------- r3: mapping ---------------------------------------
    mp = rcsv("tsmd_r3_mapping", "mapping_table.csv")
    base = next(r for r in mp if r["factor"] == "base")
    add("TSMD_map_ylo_base", num(base["rho_times_ybar"]), f"{num(base['rho_times_ybar']):.2f}",
        "rho times ybar for the base instance (symmetric-regime worst-case-yield threshold)", "tsmd_r3_mapping",
        "mapping_table.csv", "factor=base", "rho_times_ybar", "FE yield", decimals=2)
    add("TSMD_map_ylo_base_clip", num(base["pred_onset_ylo"]), f3(num(base["pred_onset_ylo"])),
        "rho/(2-rho) for the base instance (worst-case yield at the onset once the upper yield is clipped at 1)",
        "tsmd_r3_mapping", "mapping_table.csv", "factor=base", "pred_onset_ylo", "FE yield", decimals=3)
    add("TSMD_map_rho_base", num(base["rho"]), f3(num(base["rho"])), "rho for the base instance", "tsmd_r3_mapping",
        "mapping_table.csv", "factor=base", "rho", "ratio", decimals=3)
    yl = [(num(r["vss2_ylo"]), r) for r in mp if num(r["vss2_ylo"]) is not None]
    lo_, hi_ = min(yl, key=lambda t: t[0]), max(yl, key=lambda t: t[0])
    add("TSMD_map_ylo_min", lo_[0], f"{lo_[0]:.2f}",
        f"smallest worst-case FE yield at the 2% crossing across the one-factor changes ({lo_[1]['factor']}={lo_[1]['level']})",
        "tsmd_r3_mapping", "mapping_table.csv", f"factor={lo_[1]['factor']},level={lo_[1]['level']}", "vss2_ylo", "FE yield", decimals=2)
    add("TSMD_map_ylo_max", hi_[0], f"{hi_[0]:.2f}",
        f"largest worst-case FE yield at the 2% crossing across the one-factor changes ({hi_[1]['factor']}={hi_[1]['level']})",
        "tsmd_r3_mapping", "mapping_table.csv", f"factor={hi_[1]['factor']},level={hi_[1]['level']}", "vss2_ylo", "FE yield", decimals=2)
    on = [(num(r["solved_onset_ylo"]), r) for r in mp
          if num(r["solved_onset_half"]) is not None and num(r["solved_onset_half"]) > 1e-3]
    olo, ohi = min(on, key=lambda t: t[0]), max(on, key=lambda t: t[0])
    add("TSMD_map_onset_ylo_min", olo[0], f"{olo[0]:.2f}", f"smallest worst-case FE yield at the service-gap onset across the one-factor changes with an onset inside the sweep ({olo[1]['factor']}={olo[1]['level']})",
        "tsmd_r3_mapping", "mapping_table.csv", f"factor={olo[1]['factor']},level={olo[1]['level']}", "solved_onset_ylo", "FE yield", decimals=2)
    add("TSMD_map_onset_ylo_max", ohi[0], f"{ohi[0]:.2f}", f"largest worst-case FE yield at the service-gap onset across the one-factor changes with an onset inside the sweep ({ohi[1]['factor']}={ohi[1]['level']})",
        "tsmd_r3_mapping", "mapping_table.csv", f"factor={ohi[1]['factor']},level={ohi[1]['level']}", "solved_onset_ylo", "FE yield", decimals=2)
    errs = [num(r["onset_abs_err_half"]) for r in mp if num(r["onset_abs_err_half"]) is not None]
    add("TSMD_map_onset_err_max", max(errs), "below $10^{-4}$" if max(errs) < 1e-4 else f"{max(errs):.4f}",
        "largest |predicted - solved| service-gap onset (half-range) over the one-factor configurations with an onset",
        "tsmd_r3_mapping", "mapping_table.csv", "all rows with onset", "onset_abs_err_half", "FE half-range")
    add("TSMD_map_n_configs", len(mp), str(len(mp)), "number of one-factor configurations in the mapping run (base included)",
        "tsmd_r3_mapping", "mapping_table.csv", "all rows", "count", "configurations", decimals=0)
    nrow = sum(1 for r in mp if r["solved_onset_half"] not in ("none",))
    add("TSMD_map_n_onset", nrow, str(nrow), "configurations whose service gap opens within the swept range",
        "tsmd_r3_mapping", "mapping_table.csv", "solved_onset_half != none", "count", "configurations", decimals=0)

    # ---------------- r4: random instances ------------------------------
    R = [json.loads(l) for l in open(os.path.join(RES, "tsmd_r4_randinst", "instances_results.jsonl"))]
    B = next(r for r in R if r["id"] == 0)
    R = sorted([r for r in R if r["id"] > 0], key=lambda r: r["id"])
    src = ("tsmd_r4_randinst", "instances_results.csv")
    N = len(R)
    opt = [r for r in R if r["nonoptimal"] == 0]
    add("TSMD_200inst_drawn", N, str(N), "random instances drawn", *src, "id>0", "count", "instances", decimals=0)
    add("TSMD_200inst_seed", 20261113, "20261113", "Latin hypercube seed", "tsmd_r4_randinst", "run.json", "", "seed", decimals=0)
    add("TSMD_200inst_n", len(opt), str(len(opt)), "random instances whose every solve reached proven optimality", *src,
        "id>0,nonoptimal==0", "count", "instances", decimals=0)
    thr = [r for r in opt if r["thr2_class"] == "threshold"]
    alw = [r for r in opt if r["thr2_class"] == "always"]
    nev = [r for r in opt if r["thr2_class"] == "never"]
    for key, grp, m in (("struct", thr, "have a 2% threshold inside (0.01, 0.50]"),
                        ("always", alw, "exceed 2% already at half-range 0.01"),
                        ("never", nev, "stay below 2% up to half-range 0.50")):
        add(f"TSMD_200inst_{key}_n", len(grp), str(len(grp)), f"instances that {m}", *src, f"thr2_class={grp[0]['thr2_class'] if grp else key}", "count", "instances", decimals=0)
        v, dsp = pct(len(grp), len(opt))
        add(f"TSMD_200inst_{key}_pct", v, dsp, f"percent of optimal instances that {m}", *src,
            f"thr2_class share", "count/n", "%", decimals=1)
    t = np.array([r["thr2_half"] for r in thr])
    for key, val, m in (("mean", float(t.mean()), "mean"), ("median", float(np.median(t)), "median"),
                        ("min", float(t.min()), "smallest"), ("max", float(t.max()), "largest"),
                        ("p10", float(np.percentile(t, 10)), "10th percentile of"),
                        ("p90", float(np.percentile(t, 90)), "90th percentile of")):
        add(f"TSMD_200inst_{key}", val, f3(val), f"{m} the 2% profit threshold (FE half-range, bisection) over the random instances that have one",
            *src, "thr2_class=threshold", "thr2_half", "FE half-range", decimals=3)
    add("TSMD_200inst_base_thr", B["thr2_half"], f3(B["thr2_half"]), "2% threshold of the base instance computed by the same bisection (instance 0)",
        *src, "id=0", "thr2_half", "FE half-range", decimals=3)
    add("TSMD_200inst_base_onset", B["solved_onset_half"], f3(B["solved_onset_half"]), "service-gap onset of the base instance by the same bisection (instance 0)",
        *src, "id=0", "solved_onset_half", "FE half-range", decimals=3)
    mc = sum(1 for r in thr if r["n_crossings_2pct"] > 1)
    add("TSMD_200inst_multicross_n", mc, str(mc), "threshold instances whose %VSS crosses 2% more than once on the grid",
        *src, "thr2_class=threshold,n_crossings_2pct>1", "count", "instances", decimals=0)
    # cliff check
    TOL = 0.005
    def pin(r):
        return r["pred_onset_half"] is not None and r["pred_onset_half"] <= 0.5
    cl = [r for r in opt if pin(r) or r["solved_onset_half"] is not None]
    both = [r for r in opt if pin(r) and r["solved_onset_half"] is not None]
    err = np.array([abs(r["pred_onset_half"] - r["solved_onset_half"]) for r in both])
    hits = [r for r in both if abs(r["pred_onset_half"] - r["solved_onset_half"]) <= TOL]
    none_ = [r for r in opt if not pin(r) and r["solved_onset_half"] is None]
    misses = [r for r in cl if r not in hits]
    add("TSMD_200inst_cliff_n", len(cl), str(len(cl)), "instances with a service cliff inside the sweep by prediction or by solve",
        *src, "pred_onset_half<=0.5 or solved_onset_half!=NA", "count", "instances", decimals=0)
    add("TSMD_200inst_both_n", len(both), str(len(both)), "instances with both a predicted (<=0.50) and a solved onset",
        *src, "both present", "count", "instances", decimals=0)
    add("TSMD_200inst_hit_n", len(hits), str(len(hits)), f"instances where the rho check locates the solved onset within {TOL} (half-range)",
        *src, f"|pred-solved|<={TOL}", "count", "instances", decimals=0)
    add("TSMD_200inst_nocliff_n", len(none_), str(len(none_)), "instances with neither a predicted nor a solved cliff inside the sweep",
        *src, "neither", "count", "instances", decimals=0)
    add("TSMD_200inst_miss_n", len(misses), str(len(misses)), "instances with a cliff where the rho check misses by more than the tolerance (or predicts a cliff that does not open)",
        *src, "cliff and not hit", "count", "instances", decimals=0)
    v, dsp = pct(len(hits), len(cl))
    add("TSMD_200inst_rho_hit_pct", v, dsp, f"percent of instances with a cliff in which the rho check locates it within {TOL} half-range",
        *src, "hit_n / cliff_n", "count", "%", decimals=1)
    v, dsp = pct(len(hits) + len(none_), len(opt))
    add("TSMD_200inst_agree_pct", v, dsp, "percent of all optimal instances where the rho check agrees with the solve (cliff within tolerance, or no cliff by either)",
        *src, "(hit_n + nocliff_n)/n", "count", "%", decimals=1)
    add("TSMD_200inst_rho_tol", TOL, f"{TOL}", "tolerance used for a hit (FE half-range; half the 0.01 sweep step)", *src, "", "", "FE half-range", decimals=3)
    for key, val, m in (("median", float(np.median(err)), "median"), ("p90", float(np.percentile(err, 90)), "90th percentile of the")):
        dsp = "below $10^{-5}$" if val < 1e-5 else f"{val:.3f}"
        add(f"TSMD_200inst_rho_err_{key}", val, dsp, f"{m} absolute error |predicted - solved| of the service-gap onset (half-range) over instances with both",
            *src, "both present", "|pred_onset_half - solved_onset_half|", "FE half-range")
    add("TSMD_200inst_rho_err_max", float(err.max()), f3(float(err.max())), "largest absolute onset error", *src, "both present",
        "|pred_onset_half - solved_onset_half|", "FE half-range", decimals=3)
    hm = [r["rp_hedge_wafers_at_0.25"] for r in misses]
    hh = [r["rp_hedge_wafers_at_0.25"] for r in hits]
    add("TSMD_200inst_miss_hedge_max", max(hm), f"{max(hm):.2f}", "largest stochastic-minus-deterministic wafer starts at half-range 0.25 among the misses",
        *src, "misses", "rp_hedge_wafers_at_0.25", "wafers", decimals=2)
    add("TSMD_200inst_hit_hedge_min", min(hh), f"{min(hh):.2f}", "smallest stochastic-minus-deterministic wafer starts at half-range 0.25 among the hits",
        *src, "hits", "rp_hedge_wafers_at_0.25", "wafers", decimals=2)
    nh = sum(1 for x in hh if x < max(hm) + 1e-9)
    add("TSMD_200inst_hit_lowhedge_n", nh, str(nh), "hits whose hedge at 0.25 is not larger than the largest hedge among the misses",
        *src, "hits", "rp_hedge_wafers_at_0.25", "instances", decimals=0)
    # rank correlation between predicted cliff and the 2% threshold
    pairs = [(r["pred_onset_half"], r["thr2_half"]) for r in thr if pin(r)]
    from scipy.stats import spearmanr
    rs = float(spearmanr([a for a, _ in pairs], [b for _, b in pairs]).correlation)
    add("TSMD_200inst_spearman", rs, f"{rs:.2f}", "Spearman rank correlation between the predicted cliff (rho check) and the 2% threshold over threshold instances with a predicted cliff",
        *src, "thr2_class=threshold and pred_onset_half<=0.5", "spearman(pred_onset_half, thr2_half)", "", decimals=2)
    add("TSMD_200inst_spearman_n", len(pairs), str(len(pairs)), "instances in that correlation", *src, "", "count", "instances", decimals=0)
    near = [r for r in thr if r["solved_onset_half"] is not None and abs(r["thr2_half"] - r["solved_onset_half"]) <= 0.02]
    v, dsp = pct(len(near), len(thr))
    add("TSMD_200inst_near_cliff_pct", v, dsp, "percent of threshold instances whose 2% threshold lies within 0.02 of their service-gap onset",
        *src, "thr2_class=threshold", "|thr2_half - solved_onset_half|<=0.02", "%", decimals=1)
    before = [r for r in thr if r["solved_onset_half"] is not None and r["thr2_half"] < r["solved_onset_half"] - 0.02]
    v, dsp = pct(len(before), len(thr))
    add("TSMD_200inst_before_cliff_pct", v, dsp, "percent of threshold instances whose 2% threshold comes more than 0.02 before the service-gap onset",
        *src, "thr2_class=threshold", "thr2_half < solved_onset_half - 0.02", "%", decimals=1)
    rj = json.load(open(os.path.join(RES, "tsmd_r4_randinst", "run.json")))
    add("TSMD_200inst_runtime_min", rj["runtime_s"] / 60, f"{rj['runtime_s']/60:.0f}", "wall time of the random-instance run (2 worker processes)",
        "tsmd_r4_randinst", "run.json", "", "runtime_s/60", "minutes", decimals=0)
    return {"R": R, "B": B, "opt": opt, "thr": thr, "hits": hits, "misses": misses, "both": both, "mp": mp, "sw": sw,
            "ms": ms, "ev": ev}


# ---------------------------------------------------------------------------
def write_numbers():
    meta = {"key": "TSMD__tables", "type": "meta", "display": "", "value": None, "producer": "tsm_d",
            "meaning": "generated tables whose literals are written from run files by code/tsm_d/summarize.py (R1)",
            "tables": {"OUT/tables/tab_tsm_d_mapping.tex": {"script": "code/tsm_d/summarize.py", "source": "results/tsm_d/tsmd_r3_mapping/mapping_table.csv"},
                       "OUT/tables/tab_tsm_d_randinst_misses.tex": {"script": "code/tsm_d/summarize.py", "source": "results/tsm_d/tsmd_r4_randinst/instances_results.jsonl"}}}
    json.dump(ENTRIES + [meta], open(os.path.join(OUT, "numbers.json"), "w"), indent=1)
    lines = [r"\makeatletter",
             r"\providecommand{\NUM}[1]{\@ifundefined{tsmnum@#1}{\textcolor{red}{TODO-NUM: \detokenize{#1}}}{\@nameuse{tsmnum@#1}}}",
             r"\providecommand{\setnum}[2]{\@namedef{tsmnum@#1}{#2}}",
             r"\makeatother"]
    for e in ENTRIES:
        lines.append(rf"\setnum{{{e['key']}}}{{{e['display']}}}   % {e['source']['run']}{e['source']['file']}")
    txt = "\n".join(lines) + "\n"
    for p in (os.path.join(SB, "numbers.tex"), os.path.join(PAPER, "numbers.tex")):
        open(p, "w").write(txt)


def D(key):
    return next(e["display"] for e in ENTRIES if e["key"] == key)


def write_tables(ctx):
    os.makedirs(os.path.join(OUT, "tables"), exist_ok=True)
    mp = ctx["mp"]
    pick = [("base", "0", "Base instance"),
            ("demand_level", "0.9", r"Demand $\times0.9$"), ("demand_level", "1.1", r"Demand $\times1.1$"),
            ("demand_spread", "0.0", "Demand half-range 0"),
            ("be_capacity", "0.9", r"BE capacity $\times0.9$"), ("be_capacity", "1.1", r"BE capacity $\times1.1$"),
            ("outs_fe_capacity", "150.0", r"$L_G=150$"), ("outs_fe_capacity", "450.0", r"$L_G=450$"),
            ("fe_capacity", "0.6", r"FE capacity $\times0.6$"),
            ("fe_mean", "0.8", r"FE mean 0.80"), ("fe_mean", "0.9", r"FE mean 0.90"),
            ("be_mean", "0.75", r"BE mean 0.75"), ("be_mean", "0.85", r"BE mean 0.85")]
    rows = []
    for fac, lv, lab in pick:
        r = next(x for x in mp if x["factor"] == fac and abs(float(x["level"]) - float(lv)) < 1e-9)
        h_on = num(r["solved_onset_half"])
        pred_h = num(r["pred_onset_half"])
        if h_on is not None and h_on < 1e-3:
            solved = "any"
        else:
            solved = "none" if h_on is None else f"{float(r['solved_onset_ylo']):.3f}"
        pred = "any" if (pred_h is not None and pred_h < 1e-9) else (f"{float(r['pred_onset_ylo']):.3f}" if pred_h is not None else "none")
        v2 = r["vss2_ylo"]
        v2 = {"NA": "$<$" if r["vss2_regime"] == "above_at_first_grid_point" else "none"}.get(v2, None) or f"{float(v2):.3f}"
        if r["vss2_regime"] == "no_crossing":
            v2 = "none"
        rows.append(f"{lab} & {float(r['rho']):.3f} & {pred} & {solved} & {v2} \\\\")
    tex = "\n".join([
        r"% generated by code/tsm_d/summarize.py from results/tsm_d/tsmd_r3_mapping/mapping_table.csv; do not edit by hand",
        r"\begin{tabular}{@{}lcccc@{}}", r"\toprule",
        r" & & \multicolumn{2}{c}{\textbf{Onset $y_{\text{lo}}$}} & \textbf{2\% } \\",
        r"\cmidrule(lr){3-4}",
        r"\textbf{Change} & $\rho$ & \textbf{pred.} & \textbf{solved} & $y_{\text{lo}}$ \\", r"\midrule"] + rows +
        [r"\bottomrule", r"\end{tabular}"]) + "\n"
    open(os.path.join(OUT, "tables", "tab_tsm_d_mapping.tex"), "w").write(tex)
    # supplement: random-instance detail
    opt, thr, hits, misses = ctx["opt"], ctx["thr"], ctx["hits"], ctx["misses"]
    mrows = []
    for r in sorted(misses, key=lambda r: r["id"]):
        p = r["pred_onset_half"]; s = r["solved_onset_half"]
        hg = r["rp_hedge_wafers_at_0.25"]
        hg = 0.0 if abs(hg) < 0.005 else hg
        mrows.append(f"{r['id']} & {r['rho']:.3f} & {'none' if p is None else f'{p:.3f}'} & "
                     f"{'none' if s is None else f'{s:.3f}'} & {hg:.2f} & "
                     f"{r['c_F']:.1f} & {r['fe_cap']:.2f} \\\\")
    tex2 = "\n".join([
        r"% generated by code/tsm_d/summarize.py from results/tsm_d/tsmd_r4_randinst/instances_results.csv; do not edit by hand",
        r"\begin{tabular}{@{}rcccccc@{}}", r"\toprule",
        r"\textbf{Id} & $\rho$ & \textbf{Pred.} & \textbf{Solved} & \textbf{Hedge} & $c_F$ & \textbf{FE cap.} \\", r"\midrule"] + mrows +
        [r"\bottomrule", r"\end{tabular}"]) + "\n"
    open(os.path.join(OUT, "tables", "tab_tsm_d_randinst_misses.tex"), "w").write(tex2)
    for f in ("tab_tsm_d_mapping.tex", "tab_tsm_d_randinst_misses.tex"):
        shutil.copy(os.path.join(OUT, "tables", f), os.path.join(PAPER, f))


def write_figs(ctx):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "axes.labelsize": 8, "legend.fontsize": 7, "xtick.labelsize": 7.5,
                         "ytick.labelsize": 7.5, "axes.titlesize": 8, "pdf.fonttype": 42})
    os.makedirs(os.path.join(OUT, "figs"), exist_ok=True)
    C_RP, C_EV, C_G = "#1f5fa8", "#c0392b", "#555555"
    sw = ctx["sw"]; ev = ctx["ev"]
    h = np.array([float(r["half"]) for r in sw])
    col = lambda k: np.array([float(r[k]) for r in sw])
    fig, ax = plt.subplots(3, 1, figsize=(3.45, 4.1), sharex=True)
    ax[0].plot(h, col("rp_wafers"), color=C_RP, lw=1.3, label="stochastic plan (RP)")
    ax[0].plot(h, col("ev_wafers"), color=C_EV, lw=1.3, label="deterministic plan (EV)")
    ax[0].axhline(18, color=C_G, lw=0.8, ls="--"); ax[0].text(0.06, 18.35, "fab capacity 18", fontsize=6.5, color=C_G)
    ax[0].set_ylabel("wafer starts"); ax[0].set_ylim(8, 20.5); ax[0].legend(loc="lower right", frameon=False)
    lo = col("fe_lo")
    ax[1].plot(h, 100 * lo * col("rp_wafers"), color=C_RP, lw=1.3, label="RP in-house dies")
    ax[1].plot(h, 100 * lo * col("ev_wafers"), color=C_EV, lw=1.3, label="EV in-house dies")
    ax[1].plot(h, 100 * lo * col("ev_wafers") + 300, color=C_EV, lw=1.0, ls=":", label="EV in-house + $L_G$")
    ax[1].axhline(1050, color=C_G, lw=0.8, ls="--"); ax[1].text(0.335, 1110, "$N_{\\max}=1{,}050$", fontsize=6.5, color=C_G)
    ax[1].set_ylabel("dies at low FE yield"); ax[1].set_ylim(450, 1300); ax[1].legend(loc="lower left", frameon=False, fontsize=6.3)
    ax[2].plot(h, col("eev_worst_LG_shadow_cond"), color=C_EV, lw=1.3, label="EV plan: outsourcing cap. $L_G$")
    ax[2].plot(h, col("eev_worst_BE_shadow_cond"), color=C_EV, lw=1.0, ls="--", label="EV plan: BE capacity")
    ax[2].plot(h, col("rp_worst_LG_shadow_cond"), color=C_RP, lw=1.3, label="RP: outsourcing cap. $L_G$")
    ax[2].set_ylabel("shadow price (\\$/die)"); ax[2].set_xlabel("FE yield half-range $h$")
    ax[2].legend(loc="center right", frameon=False, fontsize=6.3); ax[2].set_ylim(-0.5, 8)
    for a in ax:
        for x in (ev["eev_LG_binds"], ev["rp_fe_capacity_binds"], ev["rp_LG_binds"]):
            a.axvline(x, color=C_G, lw=0.6, ls=":")
        a.grid(alpha=0.25, lw=0.4)
    for a, t in zip(ax, ("(a)", "(b)", "(c)")):
        a.text(0.005, 0.9, t, transform=a.transAxes, fontsize=7.5, fontweight="bold", va="top")
    ax[2].set_xlim(0, 0.5)
    fig.tight_layout(h_pad=0.4)
    p = os.path.join(OUT, "figs", "fig_tsm_d_cliff_binding.pdf"); fig.savefig(p); plt.close(fig)

    # random instances
    thr, both, hits = ctx["thr"], ctx["both"], ctx["hits"]
    fig, ax = plt.subplots(1, 2, figsize=(3.45, 1.85))
    t = [r["thr2_half"] for r in thr]
    ax[0].hist(t, bins=np.arange(0, 0.5001, 0.025), color=C_RP, alpha=0.85, edgecolor="white", lw=0.4)
    ax[0].axvline(ctx["B"]["thr2_half"], color=C_EV, lw=1.0, ls="--")
    ax[0].text(ctx["B"]["thr2_half"] + 0.01, ax[0].get_ylim()[1] * 0.88, "base", color=C_EV, fontsize=6.5)
    ax[0].set_xlabel("2% threshold (half-range)"); ax[0].set_ylabel("instances")
    from matplotlib.ticker import MaxNLocator
    ax[0].yaxis.set_major_locator(MaxNLocator(integer=True))
    hid = {r["id"] for r in hits}
    xs = [r["pred_onset_half"] for r in both]; ys = [r["solved_onset_half"] for r in both]
    cs = [C_RP if r["id"] in hid else C_EV for r in both]
    ax[1].scatter(xs, ys, s=5, c=cs, lw=0)
    ax[1].plot([0, 0.5], [0, 0.5], color=C_G, lw=0.6, ls="--")
    ax[1].set_xlabel("predicted onset ($\\rho$ check)"); ax[1].set_ylabel("solved onset")
    ax[1].set_xlim(-0.01, 0.51); ax[1].set_ylim(-0.01, 0.51)
    for a, tt in zip(ax, ("(a)", "(b)")):
        a.text(0.03, 0.97, tt, transform=a.transAxes, fontsize=7.5, fontweight="bold", va="top"); a.grid(alpha=0.25, lw=0.4)
    fig.tight_layout(w_pad=0.6)
    p2 = os.path.join(OUT, "figs", "fig_tsm_d_randinst.pdf"); fig.savefig(p2); plt.close(fig)

    # matched support / matched sd (supplement)
    pts = rcsv("tsmd_r2_matched_var", "matched_points.csv")
    fig, ax = plt.subplots(1, 2, figsize=(3.45, 1.9), sharey=True)
    styles = {("two_point", "2"): (C_EV, "-", "two-point"), ("uniform", "7"): (C_RP, "-", "uniform (7 pts)"),
              ("beta22", "7"): (C_RP, "--", "Beta(2,2) (7 pts)"), ("beta_mean_sd", "7"): ("#2e8b57", ":", "Beta, mean 0.875")}
    for (fam, K), (c, ls, lab) in styles.items():
        rr = [r for r in pts if r["family"] == fam and r["K"] == K]
        if fam != "beta_mean_sd":
            ax[0].plot([float(r["value"]) for r in rr], [float(r["pct_vss"]) for r in rr], color=c, ls=ls, lw=1.1, label=lab)
        ax[1].plot([float(r["sd"]) for r in rr], [float(r["pct_vss"]) for r in rr], color=c, ls=ls, lw=1.1, label=lab)
    for a in ax:
        a.axhline(2.0, color=C_G, lw=0.6, ls=":"); a.grid(alpha=0.25, lw=0.4)
    ax[0].set_xlabel("half-range $h$ (same interval)"); ax[1].set_xlabel("realized std. deviation")
    ax[0].set_ylabel("\\%VSS"); ax[1].legend(frameon=False, fontsize=6, loc="upper left")
    ax[0].set_ylim(0, 6); ax[1].set_xlim(0, 0.2); ax[0].set_xlim(0, 0.5)
    fig.tight_layout(w_pad=0.5)
    p3 = os.path.join(OUT, "figs", "fig_tsm_d_matched.pdf"); fig.savefig(p3); plt.close(fig)
    for f in (p, p2, p3):
        shutil.copy(f, os.path.join(PAPER, os.path.basename(f)))
    return [p, p2, p3]


def main():
    if "--print" in sys.argv:
        build_numbers()
        key = sys.argv[sys.argv.index("--print") + 1]
        e = next(e for e in ENTRIES if e["key"] == key)
        print(key, e["value"], "| display:", e["display"])
        return
    t0, started = time.time(), T.now()
    d = T.run_dir(RUN)
    ctx = build_numbers()
    write_numbers()
    write_tables(ctx)
    figs = write_figs(ctx)
    p = os.path.join(d, "summary.csv")
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["key", "value", "display", "run", "file", "row", "col"])
        for e in ENTRIES:
            w.writerow([e["key"], e["value"], e["display"], e["source"]["run"], e["source"]["file"], e["source"]["row"], e["source"]["col"]])
    ins = [os.path.join(RES, r, f) for r, f in (("tsmd_r1_cliff_binding", "cliff_events.csv"), ("tsmd_r1_cliff_binding", "cliff_binding_sweep.csv"),
                                                 ("tsmd_r2_matched_var", "matched_summary.csv"), ("tsmd_r2_matched_var", "matched_points.csv"),
                                                 ("tsmd_r2_matched_var", "matched_verdict.csv"), ("tsmd_r3_mapping", "mapping_table.csv"),
                                                 ("tsmd_r4_randinst", "instances_results.jsonl"))]
    outs = [p, os.path.join(OUT, "numbers.json"), os.path.join(OUT, "tables", "tab_tsm_d_mapping.tex"),
            os.path.join(OUT, "tables", "tab_tsm_d_randinst_misses.tex")] + figs
    T.write_run_json(RUN, "Registry numbers, generated tables and figures from the TSM-D run files (all TSM-D IDs)",
                     "python code/tsm_d/summarize.py", "none", started, t0, "OK", ins, outs, [os.path.abspath(__file__), T.__file__])
    print(f"{len(ENTRIES)} numbers written")


if __name__ == "__main__":
    main()
