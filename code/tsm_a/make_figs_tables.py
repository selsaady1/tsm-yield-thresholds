"""
make_figs_tables.py  (TSM-A)   run_id: figs_tables
Reads ONLY results/tsm_a/<run_id>/*.csv and writes
  results/tsm_a/figs_tables/fig_extA_*.pdf     figures for sec:extA and S-XV
  results/tsm_a/figs_tables/tab_*.tex          LaTeX table bodies (copied into the paper)
  results/tsm_a/figs_tables/numbers.csv        every number quoted in the text, with its source cell
No solver call; no number is typed by hand.

    cd tsm-yield-thresholds && .venv/bin/python code/tsm_a/make_figs_tables.py
"""
import csv
import os
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from tsa_common import RESULTS, write_run_json  # noqa: E402

OUT = os.path.join(RESULTS, "figs_tables")
COL = {"hatch.linewidth": 0.5, "hatch.color": "#222222", "font.family": "serif", "font.serif": ["Times New Roman", "Times", "Nimbus Roman", "DejaVu Serif"],
       "mathtext.fontset": "stix", "font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 7.5,
       "ytick.labelsize": 7.5, "legend.fontsize": 7, "pdf.fonttype": 42}
OK = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#000000"]
NUM = []   # (key, value, source file, selector)


def rd(run, name):
    return list(csv.DictReader(open(os.path.join(RESULTS, run, name))))


def note(key, val, run, name, sel):
    NUM.append({"key": key, "value": val, "file": f"results/tsm_a/{run}/{name}", "row_selector": sel})
    return val


def neg(x):
    """Typeset a minus sign in LaTeX math mode."""
    return x.replace("-", "$-$", 1) if isinstance(x, str) and x.startswith("-") else x


def f2(x, nd=3):
    """Round half-up from the decimal string in the CSV (avoids binary-float ties)."""
    from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
    try:
        return str(Decimal(str(x)).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return x


# ---------------------------------------------------------------------------
# T2: paradigms
# ---------------------------------------------------------------------------
LABEL = {"RP": "Stochastic (RP)", "EEV": "Deterministic (EEV)",
         "BOX_Y": r"Box robust, yields low", "BOX_YD": r"Box robust, yields low, demand high",
         "ARO_ALL": "Adj.\\ robust, all 8 scen.", "ARO_Y": "Adj.\\ robust in yields",
         "BUD_G0": r"Budget $\Gamma=0$", "BUD_G1": r"Budget $\Gamma=1$", "BUD_G2": r"Budget $\Gamma=2$",
         "BUD_G3": r"Budget $\Gamma=3$", "CC_e0": r"Chance, $\epsilon=0$",
         "CC_e0.125": r"Chance, $\epsilon=0.125$", "CC_e0.25": r"Chance, $\epsilon=0.25$",
         "CVAR_l0": r"CVaR, $\lambda=0$", "CVAR_l0.5": r"CVaR, $\lambda=0.5$", "CVAR_l1": r"CVaR, $\lambda=1$"}


def t2():
    run = "t2_paradigms"
    pts = rd(run, "points.csv")
    cr = rd(run, "crossings.csv")
    out = {}
    for cf in ("1.5", "15.0"):
        rows = []
        for c in [c for c in cr if c["c_F"] == cf]:
            m = c["method"]
            sub = [p for p in pts if float(p["c_F"]) == float(cf) and p["method"] == m and p["status"] == "Optimal"]
            gaps = [(float(p["half"]), float(p["pct_gap_to_rp"])) for p in sub]
            mx = max(gaps, key=lambda t: t[1])
            above = [h for h, v in gaps if v > 2.0]
            svc = max(float(p["svc_gap_vs_rp"]) for p in sub)
            infe = c["infeasible_or_failed_halves"]
            rows.append({"method": m, "max_gap": mx[1], "max_gap_at": mx[0],
                         "above2": (f"{min(above):.2f} to {max(above):.2f}" if above else "none"),
                         "ben": c["benefit_over_det_gt2pct_half"],
                         "wst": c["worstcase_benefit_over_det_gt2pct_half"],
                         "svc1": c["svc_gap_vs_rp_gt1_half"], "svc_max": svc, "infeasible": infe})
            for k, v in rows[-1].items():
                if k != "method":
                    note(f"t2.cF{cf}.{m}.{k}", f2(v, 4) if isinstance(v, float) else v, run,
                         "crossings.csv+points.csv", f"c_F={cf},method={m}")
        out[cf] = rows
    # summary table body (base costs, grouped methods with identical rows merged by label)
    order = ["EEV", "RP", "BOX_Y", "BOX_YD", "ARO_Y", "ARO_ALL", "BUD_G0", "BUD_G1", "BUD_G2", "BUD_G3",
             "CC_e0", "CC_e0.125", "CC_e0.25", "CVAR_l0.5", "CVAR_l1"]
    fmt = lambda s: "never" if s in ("never",) else ("$<$0.01" if s == "below_grid" else f2(s))
    for cf, fname in (("1.5", "tab_t2_main.tex"), ("15.0", "tab_t2_cf15.tex")):
        by = {r["method"]: r for r in out[cf]}
        lines = []
        for m in order:
            r = by[m]
            lines.append(f"{LABEL[m]} & {r['max_gap']:.2f} & {r['above2']} & "
                         f"{fmt(r['ben'])} & {fmt(r['wst'])} & {fmt(r['svc1'])} \\\\")
        open(os.path.join(OUT, fname), "w").write("\n".join(lines) + "\n")

    # supplement: every plan, both wafer costs, one row per plan
    b1 = {r["method"]: r for r in out["1.5"]}
    b2 = {r["method"]: r for r in out["15.0"]}
    cell = lambda r: (f"{r['max_gap']:.2f} & {r['above2']} & {fmt(r['ben'])} & {fmt(r['wst'])} & {fmt(r['svc1'])}")
    lines = [f"{LABEL[m]} & {cell(b1[m])} & {cell(b2[m])} \\\\" for m in order]
    open(os.path.join(OUT, "tab_t2_supp.tex"), "w").write("\n".join(lines) + "\n")

    # merged main-text table: plans whose printed row (all five columns) is identical
    # are listed in one row; the full per-plan table is in the supplement
    for cf, fname in (("1.5", "tab_t2_main_merged.tex"),):
        by = {r["method"]: r for r in out[cf]}
        cells = lambda r: (f"{r['max_gap']:.2f} & {r['above2']} & "
                           f"{fmt(r['ben'])} & {fmt(r['wst'])} & {fmt(r['svc1'])}")
        groups = {}
        for m in order:
            groups.setdefault(cells(by[m]), []).append(m)
        lines = []
        for c, g in groups.items():
            note(f"t2.cF{cf}.merged_group", "|".join(g), run, "crossings.csv+points.csv", "identical printed row")
            lines.append(" / ".join(LABEL[m] for m in g) + " & " + c + " \\\\")
        open(os.path.join(OUT, fname), "w").write("\n".join(lines) + "\n")
    # where the max-min plan is worse than the deterministic plan (expected profit)
    for cf in ("1.5", "15.0"):
        a = {p["half"]: float(p["exp_profit"]) for p in pts if float(p["c_F"]) == float(cf) and p["method"] == "ARO_ALL"}
        d = {p["half"]: float(p["exp_profit"]) for p in pts if float(p["c_F"]) == float(cf) and p["method"] == "EEV"}
        worse = sorted(float(h) for h in a if a[h] < d[h] - 1e-6)
        note(f"t2.cF{cf}.ARO_ALL.worse_than_EEV_halves", f"{worse[0]:.2f} to {worse[-1]:.2f}" if worse else "none",
             run, "points.csv", f"c_F={cf}, ARO_ALL exp_profit < EEV exp_profit")
        for m in ("BOX_Y", "BOX_YD", "ARO_Y", "BUD_G3", "BUD_G2"):
            mx = max(float(p["pct_gap_to_rp"]) for p in pts if float(p["c_F"]) == float(cf)
                     and p["method"] == m and p["status"] == "Optimal")
            note(f"t2.cF{cf}.{m}.max_gap_to_rp_4dp", f"{mx:.4f}", run, "points.csv", f"c_F={cf},method={m}")
    # budget Gamma = 0 and Gamma = 1: same total wafer starts at every half-range?
    for cf in ("1.5", "15.0"):
        w0 = {p["half"]: float(p["wafers"]) for p in pts if float(p["c_F"]) == float(cf) and p["method"] == "BUD_G0"}
        w1 = {p["half"]: float(p["wafers"]) for p in pts if float(p["c_F"]) == float(cf) and p["method"] == "BUD_G1"}
        note(f"t2.cF{cf}.max_abs_wafer_diff_G0_G1", f"{max(abs(w0[h] - w1[h]) for h in w0):.6f}", run, "points.csv",
             f"c_F={cf}, BUD_G0 vs BUD_G1 total wafers")
    # wafer starts of the plans at the smallest spread (h = 0.01), base costs
    for m in ("RP", "EEV", "ARO_ALL", "BOX_Y"):
        p = next(p for p in pts if float(p["c_F"]) == 1.5 and p["method"] == m and abs(float(p["half"]) - 0.01) < 1e-9)
        note(f"t2.cF1.5.{m}.wafers_at_h0.01", f"{float(p['wafers']):.2f}", run, "points.csv", f"c_F=1.5,method={m},half=0.01")
        note(f"t2.cF1.5.{m}.pct_gap_at_h0.01", f"{float(p['pct_gap_to_rp']):.2f}", run, "points.csv", f"c_F=1.5,method={m},half=0.01")

    # figure: loss vs RP for selected methods, two wafer costs (supplement)
    sel = [("EEV", 0, "-"), ("BOX_Y", 1, "--"), ("ARO_ALL", 3, "-"), ("BUD_G1", 4, "-."),
           ("BUD_G2", 2, ":"), ("ARO_Y", 5, "--")]
    with plt.rc_context(COL):
        fig, axs = plt.subplots(1, 2, figsize=(7.0, 1.9), sharey=True)
        for ax, cf in zip(axs, (1.5, 15.0)):
            for m, ci, ls in sel:
                sub = sorted([p for p in pts if float(p["c_F"]) == cf and p["method"] == m and p["status"] == "Optimal"],
                             key=lambda p: float(p["half"]))
                ax.plot([float(p["half"]) for p in sub], [float(p["pct_gap_to_rp"]) for p in sub],
                        ls, color=OK[ci], lw=1.1, label=LABEL[m].replace("\\ ", " ").replace("Adj.", "Adj."))
            ax.axhline(2.0, color="0.35", ls=":", lw=0.8)
            ax.set_xlabel("FE yield half-range $h$")
            ax.set_title(f"$c_F$ = \\${cf:.2f} per wafer", fontsize=8)
            ax.grid(True, alpha=0.25, lw=0.5)
            ax.set_xlim(0, 0.5)
        axs[0].set_ylabel("Loss vs. RP (% of RP)")
        axs[1].legend(loc="upper left", frameon=False, ncol=2, handlelength=1.8, labelspacing=0.2)
        fig.tight_layout(pad=0.3)
        fig.savefig(os.path.join(OUT, "fig_extA_paradigms.pdf"))
        plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# T3: capacity
# ---------------------------------------------------------------------------
def t3():
    run = "t3_capacity"
    sm = rd(run, "summary.csv")
    pts = rd(run, "points.csv")
    lines = []
    for d in ("0.0", "0.1", "0.2", "0.3"):
        g = next(r for r in sm if r["kind"] == "LG" and r["delta"] == d)
        f = next(r for r in sm if r["kind"] == "LF" and r["delta"] == d)
        lines.append(f"{int(round(float(d) * 100))} & {f2(g['vss2_half'])} & {f2(g['gap_onset_half'])} & "
                     f"{f2(g['pred_onset_half_Lglow'])} & {f2(g['pred_onset_half_Lgmean'])} & "
                     f"{f2(f['vss2_half'])} & {f2(f['gap_onset_half'])} & {f2(f['rp_unmet_first_rise_grid_half'], 2)} \\\\")
        for kind, r in (("LG", g), ("LF", f)):
            for k, v in r.items():
                note(f"t3.{kind}.d{d}.{k}", v, run, "summary.csv", f"kind={kind},delta={d}")
    open(os.path.join(OUT, "tab_t3_main.tex"), "w").write("\n".join(lines) + "\n")
    lines = []
    for r in sm:
        kind = "$L_G$" if r["kind"] == "LG" else "In-house"
        lines.append(f"{kind} & {int(round(float(r['delta']) * 100))} & {f2(r['vss2_half'])} & {f2(r['gap1_half'])} & "
                     f"{f2(r['gap_onset_half'])} & {f2(r['pred_onset_half_Lglow'])} & {f2(r['abs_err_pred_vs_solved'], 5)} & "
                     f"{f2(r['rp_unmet_first_rise_grid_half'], 2)} & {f2(r['gap_at_0.50'], 1)} \\\\")
    open(os.path.join(OUT, "tab_t3_supp.tex"), "w").write("\n".join(lines) + "\n")
    errs = [float(r["abs_err_pred_vs_solved"]) for r in sm if r["abs_err_pred_vs_solved"] != "NA"]
    note("t3.max_abs_err_pred_Lglow_vs_solved", f"{max(errs):.5f}", run, "summary.csv", "max over 8 rows")
    miss = max(float(r["pred_onset_half_Lgmean"]) - float(r["gap_onset_half"]) for r in sm if r["kind"] == "LG")
    note("t3.LG.max_miss_pred_with_mean_LG", f"{miss:.4f}", run, "summary.csv", "max over LG rows of pred(mean L_G) - solved")
    # expected-value wafer starts near the deterministic onset under LF uncertainty
    for d in ("0.3",):
        p = next(p for p in pts if p["kind"] == "LF" and float(p["delta"]) == float(d) and abs(float(p["half"]) - 0.16) < 1e-9)
        note(f"t3.LF.d{d}.ev_wafers_at_h0.16", f"{float(p['ev_wafers']):.2f}", run, "points.csv", f"kind=LF,delta={d},half=0.16")
        mx = max(float(p["ev_wafers"]) for p in pts if p["kind"] == "LF" and float(p["delta"]) == float(d))
        note(f"t3.LF.d{d}.ev_wafers_max", f"{mx:.2f}", run, "points.csv", f"kind=LF,delta={d},max over half")
    # split check: CBC split vs balanced split for LF
    for d in ("0.1", "0.2", "0.3"):
        sub = [p for p in pts if p["kind"] == "LF" and float(p["delta"]) == float(d)]
        diff = max(abs(float(p["pct_vss_cbc_split"]) - float(p["pct_vss"])) for p in sub)
        note(f"t3.LF.d{d}.max_abs_diff_pctvss_cbc_vs_balanced_split", f"{diff:.4f}", run, "points.csv",
             f"kind=LF,delta={d},max over half")
        sub.sort(key=lambda p: float(p["half"]))
        from tsa_common import crossing_up
        c, nn = crossing_up([float(p["half"]) for p in sub], [float(p["pct_vss_cbc_split"]) for p in sub], 2.0)
        note(f"t3.LF.d{d}.min_pct_vss_cbc_split", f"{min(float(p['pct_vss_cbc_split']) for p in sub):.4f}", run,
             "points.csv", f"kind=LF,delta={d},min over half")
        note(f"t3.LF.d{d}.vss2_half_cbc_split", f"{c:.4f}" if c is not None else nn, run, "points.csv",
             f"kind=LF,delta={d},crossing of pct_vss_cbc_split")
    # figure (supplement): service gap for LG, %VSS for LF
    with plt.rc_context(COL):
        fig, axs = plt.subplots(1, 2, figsize=(7.0, 1.9))
        for i, d in enumerate(("0.0", "0.1", "0.2", "0.3")):
            s = sorted([p for p in pts if p["kind"] == "LG" and float(p["delta"]) == float(d)], key=lambda p: float(p["half"]))
            axs[0].plot([float(p["half"]) for p in s], [float(p["unmet_gap"]) for p in s], color=OK[i], lw=1.1,
                        label=f"$L_G$ $\\pm${int(round(float(d) * 100))}%")
            s = sorted([p for p in pts if p["kind"] == "LF" and float(p["delta"]) == float(d)], key=lambda p: float(p["half"]))
            axs[1].plot([float(p["half"]) for p in s], [float(p["pct_vss"]) for p in s], color=OK[i], lw=1.1,
                        label=f"FE cap. $\\pm${int(round(float(d) * 100))}%")
        axs[0].set_ylabel("Service gap (units)")
        axs[1].set_ylabel("%VSS")
        axs[1].axhline(2.0, color="0.35", ls=":", lw=0.8)
        for ax in axs:
            ax.set_xlabel("FE yield half-range $h$")
            ax.grid(True, alpha=0.25, lw=0.5)
            ax.set_xlim(0, 0.5)
            ax.legend(loc="upper left", frameon=False, handlelength=1.6, labelspacing=0.2)
        fig.tight_layout(pad=0.3)
        fig.savefig(os.path.join(OUT, "fig_extA_capacity.pdf"))
        plt.close(fig)


# ---------------------------------------------------------------------------
# T4: demand map
# ---------------------------------------------------------------------------
def t4():
    run = "t4_demand_map"
    g = rd(run, "grid.csv")
    sm = rd(run, "summary.csv")
    for r in sm:
        for k, v in r.items():
            note(f"t4.q{r['demand_mean']}.dh{r['demand_half']}.{k}", v, run, "summary.csv",
                 f"demand_mean={r['demand_mean']},demand_half={r['demand_half']}")
    errs = [float(r["abs_err_pred_vs_solved"]) for r in sm if r["abs_err_pred_vs_solved"] != "NA"]
    note("t4.max_abs_err_pred_vs_solved", f"{max(errs):.5f}", run, "summary.csv", "max over rows")
    note("t4.n_configs_with_onset", str(len(errs)), run, "summary.csv", "rows with onset")
    rc = rd(run, "reuse_check.csv")
    note("t4.reuse_max_abs_diff_pct_vss", f"{max(float(r['max_abs_diff_pct_vss']) for r in rc):.6f}", run,
         "reuse_check.csv", "max over rows")
    means = sorted({float(r["demand_mean"]) for r in g})
    dhs = sorted({float(r["demand_half"]) for r in g})
    hs = sorted({float(r["half"]) for r in g})
    vmax = max(float(r["pct_vss"]) for r in g)
    with plt.rc_context(COL):
        fig, axs = plt.subplots(1, 3, figsize=(3.5, 1.75), sharey=True)
        for ax, q in zip(axs, means):
            Z = np.full((len(dhs), len(hs)), np.nan)
            G = np.full((len(dhs), len(hs)), np.nan)
            for r in g:
                if float(r["demand_mean"]) == q:
                    i, j = dhs.index(float(r["demand_half"])), hs.index(float(r["half"]))
                    Z[i, j], G[i, j] = float(r["pct_vss"]), float(r["unmet_gap"])
            hx = np.array(hs)
            xe = np.concatenate([[hx[0] - 0.005], (hx[:-1] + hx[1:]) / 2, [hx[-1] + 0.005]])
            ye = np.arange(len(dhs) + 1) - 0.5
            im = ax.pcolormesh(xe, ye, Z, cmap="viridis", vmin=0, vmax=vmax, shading="flat",
                               linewidth=0, edgecolors="face", rasterized=True)
            # service gap > 1 unit: hatched overlay
            ax.contourf(hx, np.arange(len(dhs)), (G > 1.0).astype(float), levels=[0.5, 1.5],
                        colors="none", hatches=["////"])
            srow = [r for r in sm if float(r["demand_mean"]) == q]
            ys = [dhs.index(float(r["demand_half"])) for r in srow]
            pred = [float(r["pred_onset_half"]) if r["pred_onset_half"] != "NA" else np.nan for r in srow]
            sol = [float(r["gap_onset_half"]) if r["gap_onset_half"] != "NA" else np.nan for r in srow]
            v2 = [float(r["vss2_half"]) if r["vss2_half"] not in ("below_grid", "never") else
                  (0.0 if r["vss2_half"] == "below_grid" else np.nan) for r in srow]
            ax.plot(pred, ys, "w--", lw=1.0)
            ax.plot(sol, ys, "o", color="w", ms=2.6, mec="k", mew=0.4)
            ax.plot(v2, ys, "x", color="#D55E00", ms=3.2, mew=1.0)
            ax.set_title(f"$\\bar q$ = {q:g}", fontsize=7.5, pad=2)
            ax.set_xticks([0, 0.25, 0.5])
            ax.set_xticklabels(["0", ".25", ".5"])
            ax.set_xlim(0, 0.505)
        axs[0].set_yticks(range(len(dhs)))
        axs[0].set_yticklabels([f"{d:g}" for d in dhs])
        axs[0].set_ylabel("Demand half-range")
        axs[1].set_xlabel("FE yield half-range $h$", labelpad=1)
        cb = fig.colorbar(im, ax=axs, fraction=0.05, pad=0.02)
        cb.set_label("%VSS", labelpad=1)
        fig.subplots_adjust(left=0.15, right=0.83, bottom=0.22, top=0.88, wspace=0.12)
        fig.savefig(os.path.join(OUT, "fig_extA_demand_map.pdf"))
        plt.close(fig)
    # supplement table body: all 15 configurations
    lines = []
    for r in sm:
        lines.append(f"{float(r['demand_mean']):g} & {float(r['demand_half']):g} & {f2(r['rho'])} & "
                     f"{f2(r['vss2_half']).replace('below_grid', '$<$')} & {f2(r['gap_onset_half'])} & "
                     f"{f2(r['pred_onset_half'])} & {f2(r['gap1_half'])} \\\\")
    open(os.path.join(OUT, "tab_t4_supp.tex"), "w").write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# T5: limited data
# ---------------------------------------------------------------------------
def t5():
    run = "t5_limited_data"
    if not os.path.exists(os.path.join(RESULTS, run, "summary.csv")):
        print("t5 results missing; skipped")
        return
    sm = rd(run, "summary.csv")
    tr = rd(run, "truth.csv")
    va = rd(run, "validation.csv")
    for r in tr:
        for k, v in r.items():
            note(f"t5.truth.s{r['sigma']}.{k}", v, run, "truth.csv", f"sigma={r['sigma']}")
    for r in va:
        note(f"t5.validation.{r['check']}", r["value"], run, "validation.csv", f"check={r['check']}")
    for r in sm:
        for k, v in r.items():
            note(f"t5.s{r['sigma']}.n{r['n']}.{k}", v, run, "summary.csv", f"sigma={r['sigma']},n={r['n']}")
    # main text: sigma = 0.15 truth
    lines = []
    for r in [r for r in sm if float(r["sigma"]) == 0.15]:
        lines.append(f"{r['n']} & {neg(f2(r['vss_in_mean'], 1))} & {neg(f2(r['vss_real_mean'], 1))} "
                     f"[{neg(f2(r['vss_real_ci_lo'], 1))}, {neg(f2(r['vss_real_ci_hi'], 1))}] & "
                     f"{neg(f2(r['optimism_obj_mean'], 1))} & {neg(f2(r['gap_saa_exact_mean'], 1))} & "
                     f"{f2(100 * float(r['share_vss_in_gt_2pct']), 1)} & "
                     f"{f2(100 * float(r['mmw_truth_coverage']), 1)} / {f2(100 * float(r['mmw_boot_coverage']), 1)} \\\\")
    open(os.path.join(OUT, "tab_t5_main.tex"), "w").write("\n".join(lines) + "\n")
    # supplement: both truths, all statistics
    lines = []
    for r in sm:
        lines.append(f"{float(r['sigma']):g} & {r['n']} & {neg(f2(r['vss_in_mean'], 1))} & {neg(f2(r['vss_real_mean'], 1))} & "
                     f"{neg(f2(r['optimism_vss_mean'], 1))} [{neg(f2(r['optimism_vss_ci_lo'], 1))}, {neg(f2(r['optimism_vss_ci_hi'], 1))}] & "
                     f"{neg(f2(r['optimism_obj_mean'], 1))} & {neg(f2(r['vss_boot_corrected_mean'], 1))} & "
                     f"{neg(f2(r['vss_real_bag_mean'], 1))} & {neg(f2(r['gap_saa_exact_mean'], 2))} & {neg(f2(r['gap_det_exact_mean'], 1))} & "
                     f"{f2(100 * float(r['share_vss_in_gt_2pct']), 1)} & {f2(100 * float(r['share_vss_real_gt_2pct']), 1)} & "
                     f"{f2(100 * float(r['mmw_truth_coverage']), 1)} & {f2(100 * float(r['mmw_boot_coverage']), 1)} \\\\")
    open(os.path.join(OUT, "tab_t5_supp.tex"), "w").write("\n".join(lines) + "\n")
    reps_all = rd(run, "replications.csv")
    note("t5.n_replications_total", str(len(reps_all)), run, "replications.csv", "all rows")
    note("t5.n_vss_real_negative", str(sum(float(x["vss_real"]) < 0 for x in reps_all)), run, "replications.csv",
         "rows with vss_real < 0")
    import statistics as stx
    for n in ("5", "20"):
        x = [z for z in reps_all if float(z["sigma"]) == 0.15 and z["n"] == n]
        sd = [float(z["sample_sd"]) for z in x]
        vi = [float(z["vss_in"]) for z in x]
        note(f"t5.s0.15.n{n}.median_sample_sd", f"{stx.median(sd):.4f}", run, "replications.csv", f"sigma=0.15,n={n}")
        note(f"t5.s0.15.n{n}.corr_sample_sd_vss_in", f"{stx.correlation(sd, vi):.3f}", run, "replications.csv",
             f"sigma=0.15,n={n}")
    for r in sm:
        if float(r["sigma"]) == 0.15:
            note(f"t5.s0.15.n{r['n']}.realized_share_of_true_vss",
                 f"{float(r['vss_real_mean']) / float(r['true_vss']):.3f}", run, "summary.csv",
                 f"sigma=0.15,n={r['n']}: vss_real_mean / true_vss")
            note(f"t5.s0.15.n{r['n']}.gap_saa_pct_of_Fstar",
                 f"{100 * float(r['gap_saa_exact_mean']) / float(next(t for t in tr if float(t['sigma']) == 0.15)['F_star']):.2f}",
                 run, "summary.csv+truth.csv", f"sigma=0.15,n={r['n']}: gap_saa_exact_mean / F_star")
    # figure (supplement): in-sample vs realized VSS by n
    reps = rd(run, "replications.csv")
    with plt.rc_context(COL):
        fig, axs = plt.subplots(1, 2, figsize=(7.0, 1.9), sharey=False)
        for ax, sg in zip(axs, ("0.075", "0.15")):
            ns = sorted({int(r["n"]) for r in reps})
            pos = np.arange(len(ns))
            vin = [[float(r["vss_in"]) for r in reps if float(r["sigma"]) == float(sg) and int(r["n"]) == n] for n in ns]
            vre = [[float(r["vss_real"]) for r in reps if float(r["sigma"]) == float(sg) and int(r["n"]) == n] for n in ns]
            b1 = ax.boxplot(vin, positions=pos - 0.18, widths=0.3, showfliers=False, patch_artist=True)
            b2 = ax.boxplot(vre, positions=pos + 0.18, widths=0.3, showfliers=False, patch_artist=True)
            for b, c in ((b1, OK[1]), (b2, OK[0])):
                for p in b["boxes"]:
                    p.set_facecolor(c)
                    p.set_alpha(0.6)
                for k in ("medians",):
                    for l in b[k]:
                        l.set_color("k")
            tv = float(next(r for r in tr if float(r["sigma"]) == float(sg))["true_vss"])
            ax.axhline(tv, color=OK[3], ls="--", lw=0.9)
            ax.axhline(0, color="0.4", lw=0.5)
            ax.set_xticks(pos)
            ax.set_xticklabels([str(n) for n in ns])
            ax.set_xlabel("Number of lot yields $n$")
            ax.set_title(f"Truth: Beta, mean 0.875, sd {sg}", fontsize=8)
            ax.grid(True, alpha=0.25, lw=0.5)
        axs[0].set_ylabel("VSS (\\$)")
        axs[1].plot([], [], "s", color=OK[1], alpha=0.6, label="in-sample VSS")
        axs[1].plot([], [], "s", color=OK[0], alpha=0.6, label="realized VSS")
        axs[1].plot([], [], "--", color=OK[3], label="true VSS")
        axs[1].legend(loc="upper right", frameon=False, labelspacing=0.2)
        fig.tight_layout(pad=0.3)
        fig.savefig(os.path.join(OUT, "fig_extA_limited_data.pdf"))
        plt.close(fig)


def main():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    t2()
    t3()
    t4()
    t5()
    with open(os.path.join(OUT, "numbers.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["key", "value", "file", "row_selector"])
        w.writeheader()
        w.writerows(NUM)
    print(f"wrote {len(NUM)} numbers and figures/tables to {OUT}")
    write_run_json(OUT, "figs_tables", "cd tsm-yield-thresholds && .venv/bin/python code/tsm_a/make_figs_tables.py",
                   0, t0, time.time())


if __name__ == "__main__":
    main()
