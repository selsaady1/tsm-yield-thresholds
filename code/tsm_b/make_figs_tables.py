"""make_figs_tables.py: figures and LaTeX tables for sec:extB and S-XVI, written
only from the run folders results/tsm_b/tsmb_r0{1,2,3}_*/.  Every literal in a
generated table is read from those CSV files.

Outputs (in OUT/figs and OUT/tables, copied next to the .tex sources):
  fig_tsm_b_extB.pdf          three panels: (a) %VSS, (b) per-period service gap
                              for the multi-period variants, (c) utilisation of
                              FE1/FE2 in the stochastic plan with and without congestion
  tab_tsm_b_extB.tex          main-text summary table
  tab_tsm_b_S_leadtime.tex    supplement: all multi-period configurations
  tab_tsm_b_S_aggcong.tex     supplement: tool groups, non-identical fabs, congestion
  tab_tsm_b_S_ct.tex          supplement: per-scenario utilisation and cycle-time proxy (BE congestion)
Usage: $PY make_figs_tables.py
"""
import csv
import os
import shutil

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from tsmb_common import RESULTS_ROOT, SANDBOX  # noqa: E402

OUT = os.path.join(SANDBOX, "OUT")
PAPER = os.path.join(SANDBOX, "revision", "paper")
for d in ("figs", "tables"):
    os.makedirs(os.path.join(OUT, d), exist_ok=True)


def read(run, name):
    with open(os.path.join(RESULTS_ROOT, run, name)) as fh:
        return list(csv.DictReader(fh))


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


lt = read("tsmb_r01_leadtime", "sweep.csv")
lts = {r["config"]: r for r in read("tsmb_r01_leadtime", "summary.csv")}
ag = {r["config"]: r for r in read("tsmb_r02_aggregation", "summary.csv")}
cg = read("tsmb_r03_congestion", "sweep.csv")
cgs = {r["config"]: r for r in read("tsmb_r03_congestion", "summary.csv")}
ct = read("tsmb_r03_congestion", "scenario_ct.csv")


def series(rows, cfg, y):
    pts = [(num(r["half"]), num(r[y])) for r in rows if r["config"] == cfg]
    pts.sort()
    return [p[0] for p in pts], [p[1] for p in pts]


# ------------------------------------------------------------------ figure
plt.rcParams.update({"font.size": 7, "axes.titlesize": 7, "legend.fontsize": 6,
                     "font.family": "serif"})
fig, ax = plt.subplots(1, 3, figsize=(7.16, 1.75))
styles = [("P1_l0", "single period (paper)", "k", "-"),
          ("P4_l0", "4 periods, inventory", "tab:blue", "-"),
          ("P1_l1", "1 period, BE lead time", "tab:orange", "--"),
          ("P4_l1", "4 periods, inventory + lead time", "tab:red", "-"),
          ("P4_l1_m1", "same, multistage ($\\ell_F=1$)", "tab:green", ":")]
for cfg, lab, col, ls in styles:
    x, y = series(lt, cfg, "pct_vss")
    ax[0].plot(x, y, color=col, ls=ls, lw=1)
    ax[1].plot([], [], color=col, ls=ls, lw=1, label=lab)
    x, y = series(lt, cfg, "unmet_gap_pp")
    ax[1].plot(x, y, color=col, ls=ls, lw=1)
ax[0].axhline(2.0, color="gray", lw=0.6, ls=":")
ax[0].set_xlabel("FE yield half-range")
ax[0].set_ylabel("%VSS")
ax[0].set_title("(a) value of the stochastic solution")
ax[1].legend(loc="upper left", frameon=False, fontsize=5.5)
ax[1].set_xlabel("FE yield half-range")
ax[1].set_ylabel("service gap per period (units)")
ax[1].set_title("(b) service gap (EEV minus RP)")
for cfg, lab, col, ls in [("nocong", "no congestion", "k", "-"),
                          ("cf_k1", "clearing function", "tab:red", "-")]:
    x, y1 = series(cg, cfg, "rp_u1")
    _, y2 = series(cg, cfg, "rp_u2")
    ax[2].plot(x, y1, color=col, ls="-", lw=1, label=f"FE1, {lab}")
    ax[2].plot(x, y2, color=col, ls="--", lw=1, label=f"FE2, {lab}")
ax[2].set_xlabel("FE yield half-range")
ax[2].set_ylabel("utilisation, stochastic plan")
ax[2].set_title("(c) facility loading")
ax[2].set_ylim(0, 1.05)
ax[2].legend(loc="lower right", frameon=False)
for a in ax:
    a.grid(alpha=0.3, lw=0.4)
fig.tight_layout(pad=0.4)
fpath = os.path.join(OUT, "figs", "fig_tsm_b_extB.pdf")
fig.savefig(fpath)
shutil.copy(fpath, os.path.join(PAPER, "fig_tsm_b_extB.pdf"))


# ------------------------------------------------------------------ tables
def f2(x, d=2):
    v = num(x)
    if v is None:
        return {"below_grid": "$<$0.01", "none": "none", "None": "none", "": "n/a"}.get(str(x), str(x))
    return f"{v:.{d}f}"


def f3(x):
    return f2(x, 3)


def write(name, text):
    p = os.path.join(OUT, "tables", name)
    with open(p, "w") as fh:
        fh.write(text)
    shutil.copy(p, os.path.join(PAPER, name))


# main-text table: one row per variant
rows = [
    ("Single period (paper)", lts["P1_l0"]["pct_vss_at_0.075"], lts["P1_l0"]["vss2_half"],
     lts["P1_l0"]["gap_onset_solved"], lts["P1_l0"]["gap_onset_pred_rho"]),
    ("4 periods, inventory", lts["P4_l0"]["pct_vss_at_0.075"], lts["P4_l0"]["vss2_half"],
     lts["P4_l0"]["gap_onset_solved"], lts["P4_l0"]["gap_onset_pred_rho"]),
    ("1 period, BE lead time", lts["P1_l1"]["pct_vss_at_0.075"], lts["P1_l1"]["vss2_half"],
     lts["P1_l1"]["gap_onset_solved"], lts["P1_l1"]["gap_onset_pred_rho"]),
    ("4 periods, inv.\\ + lead time", lts["P4_l1"]["pct_vss_at_0.075"], lts["P4_l1"]["vss2_half"],
     lts["P4_l1"]["gap_onset_solved"], lts["P4_l1"]["gap_onset_pred_rho"]),
    ("\\quad multistage, $\\ell_F{=}1$", lts["P4_l1_m1"]["pct_vss_at_0.075"],
     lts["P4_l1_m1"]["vss2_half"], lts["P4_l1_m1"]["gap_onset_solved"],
     lts["P4_l1_m1"]["gap_onset_pred_rho"]),
    ("Tool groups", ag["tg3"]["pct_vss_at_0.075"], ag["tg3"]["vss2_half"],
     ag["tg3"]["gap_onset_solved"], ag["tg3"]["gap_onset_pred"]),
    ("Non-identical fabs", ag["ni_main"]["pct_vss_at_0.075"], ag["ni_main"]["vss2_half"],
     ag["ni_main"]["gap_onset_solved"], ag["ni_main"]["gap_onset_pred"]),
    ("Congestion (clearing fn.)", cgs["cf_k1"]["pct_vss_at_0.075"], cgs["cf_k1"]["vss2_half"],
     cgs["cf_k1"]["gap_onset_solved"], cgs["cf_k1"]["gap_onset_pred"]),
    ("\\quad tool-group congestion", cgs["tg_cf_k1"]["pct_vss_at_0.075"],
     cgs["tg_cf_k1"]["vss2_half"], cgs["tg_cf_k1"]["gap_onset_solved"],
     cgs["tg_cf_k1"]["gap_onset_pred"]),
]
body = "\n".join(f"{a} & {f2(b)} & {f3(c)} & {f3(d)} & {f3(e)} \\\\" for a, b, c, d, e in rows)
write("tab_tsm_b_extB.tex",
      "% generated by code/tsm_b/make_figs_tables.py from results/tsm_b/ (do not edit)\n"
      "\\begin{tabular}{@{}lcccc@{}}\n\\toprule\n"
      " & \\%VSS at & \\%VSS$=$2\\% & \\multicolumn{2}{c}{Gap onset $h$} \\\\\n"
      "\\cmidrule(l){4-5}\n"
      "\\textbf{Variant} & $h{=}0.075$ & at $h$ & solved & by~\\eqref{eq:cliff} \\\\\n\\midrule\n"
      + body + "\n\\bottomrule\n\\end{tabular}\n")

# supplement: multi-period configurations
names = {"P1_l0": "$T{=}1$, $\\ell_B{=}0$", "P4_l0": "$T{=}4$, $\\ell_B{=}0$",
         "P1_l1": "$T{=}1$, $\\ell_B{=}1$", "P3_l1": "$T{=}3$, $\\ell_B{=}1$",
         "P3_l1_m1": "$T{=}3$, multistage, $\\ell_F{=}1$",
         "P3_l1_m2": "$T{=}3$, multistage, $\\ell_F{=}2$",
         "P4_l1": "$T{=}4$, $\\ell_B{=}1$", "P4_l1_m1": "$T{=}4$, multistage, $\\ell_F{=}1$",
         "P4_l1_m2": "$T{=}4$, multistage, $\\ell_F{=}2$"}
lines = []
for k, lab in names.items():
    s = lts[k]
    lines.append(f"{lab} & {f2(s['pct_vss_at_0.075'])} & {f3(s['vss2_half'])} & "
                 f"{f2(s['gap_pp_at_0.075'])} & {f3(s['gaprise1_half'])} & "
                 f"{f3(s['gap_onset_solved'])} & {f3(s['gap_onset_pred_rho'])} & "
                 f"{f2(s['gap_rise_0.01_to_0.50'])} & {f2(s.get('vms_max', ''))} \\\\")
write("tab_tsm_b_S_leadtime.tex",
      "% generated by code/tsm_b/make_figs_tables.py from results/tsm_b/tsmb_r01_leadtime/summary.csv\n"
      "\\setlength{\\tabcolsep}{2pt}\n\\begin{tabular}{@{}lcccccccc@{}}\n\\toprule\n"
      "Configuration & \\%VSS & 2\\% & gap & rise$>$1 & onset & pred. & rise to & VMS \\\\\n"
      " & $h{=}.075$ & at $h$ & $h{=}.075$ & at $h$ & solved & (12) & $h{=}.50$ & max \\\\\n\\midrule\n"
      + "\n".join(lines) + "\n\\bottomrule\n\\end{tabular}\n")

# supplement: aggregation, non-identical fabs, congestion
lab2 = [("agg_ref", ag, "Aggregate (paper)"), ("tg3", ag, "Tool groups"),
        ("tg3_tight", ag, "Tool groups, 2\\% slack"), ("ni_main", ag, "Non-ident.\\ (yield, cost, indep.)"),
        ("ni_yield", ag, "Non-ident.\\ (yield)"), ("ni_cost", ag, "Non-ident.\\ (cost)"),
        ("cf_k025", cgs, "Clearing fn., $c_W\\times0.25$"), ("cf_k1", cgs, "Clearing fn., $c_W$"),
        ("cf_k4", cgs, "Clearing fn., $c_W\\times4$"), ("pwl_k1", cgs, "Convex cost (check)"),
        ("cf_k1_be", cgs, "Clearing fn., FE and BE"), ("tg_cf_k1", cgs, "Clearing fn.\\ per tool group"),
        ("ni_cf_k1", cgs, "Non-ident.\\ + clearing fn.")]
lines = []
for k, src, lab in lab2:
    s = src[k]
    lines.append(f"{lab} & {f2(s['pct_vss_at_0.075'])} & {f2(s['rp_u1_at_0.075'])}/{f2(s['rp_u2_at_0.075'])} & "
                 f"{f2(s['ev_u1_at_0.075'])}/{f2(s['ev_u2_at_0.075'])} & {f2(s['hedge_at_0.075'])} & "
                 f"{f3(s['vss2_half'])} & {f3(s['gap1_half'])} & {f3(s['gap_onset_solved'])} & "
                 f"{f3(s['gap_onset_pred'])} \\\\")
write("tab_tsm_b_S_aggcong.tex",
      "% generated by code/tsm_b/make_figs_tables.py from results/tsm_b/tsmb_r02_aggregation and tsmb_r03_congestion summary.csv\n"
      "\\setlength{\\tabcolsep}{2pt}\n\\begin{tabular}{@{}lcccccccc@{}}\n\\toprule\n"
      "Variant & \\%VSS & util.\\ RP & util.\\ EV & hedge & 2\\% & gap$>$1 & onset & pred. \\\\\n"
      " & $h{=}.075$ & FE1/FE2 & FE1/FE2 & wafers & at $h$ & at $h$ & solved & (12) \\\\\n\\midrule\n"
      + "\n".join(lines) + "\n\\bottomrule\n\\end{tabular}\n")

# supplement: per-scenario BE utilisation and cycle-time proxy (cf_k1_be, base half-range)
lines = []
for r in ct:
    if r["config"] != "cf_k1_be":
        continue
    lines.append(f"{r['plan'].upper()} & {f2(r['fe1_yield'])} & {int(float(r['demand']))} & "
                 f"{f2(r['be_yield'])} & {f2(r['ct_fe1'])}/{f2(r['ct_fe2'])} & "
                 f"{f2(r['u_be1'])}/{f2(r['u_be2'])} & {f2(r['ct_be1'])}/{f2(r['ct_be2'])} & "
                 f"{f2(r['unmet'], 1)} \\\\")
write("tab_tsm_b_S_ct.tex",
      "% generated by code/tsm_b/make_figs_tables.py from results/tsm_b/tsmb_r03_congestion/scenario_ct.csv (config cf_k1_be, h = 0.075)\n"
      "\\setlength{\\tabcolsep}{2.5pt}\n\\begin{tabular}{@{}lccccccc@{}}\n\\toprule\n"
      "Plan & $y^F$ & $q$ & $y^B$ & CT FE1/FE2 & util.\\ BE1/BE2 & CT BE1/BE2 & unmet \\\\\n\\midrule\n"
      + "\n".join(lines) + "\n\\bottomrule\n\\end{tabular}\n")
# supplement: tool-group data (from the constants of tsmb_sweeps.py)
import tsmb_sweeps as sw  # noqa: E402
tg = sw.TOOL_GROUPS
lines = []
for k in tg["load"]:
    lines.append(f"{k.capitalize()} & {tg['load'][k]:.1f} & {tg['cap']['FE1'][k]:.1f} & "
                 f"{tg['cap']['FE1'][k] / tg['load'][k]:.1f} & {tg['cap']['FE2'][k]:.1f} & "
                 f"{tg['cap']['FE2'][k] / tg['load'][k]:.1f} & {sw.T0_SHARE[k]:.2f} \\\\")
write("tab_tsm_b_S_tg.tex",
      "% generated by code/tsm_b/make_figs_tables.py from tsmb_sweeps.TOOL_GROUPS and T0_SHARE\n"
      "\\setlength{\\tabcolsep}{3pt}\n\\begin{tabular}{@{}lcccccc@{}}\n\\toprule\n"
      " & Load & \\multicolumn{2}{c}{FE1} & \\multicolumn{2}{c}{FE2} & Share \\\\\n"
      "Group & h/wafer & hours & wafers & hours & wafers & of $t_0$ \\\\\n\\midrule\n"
      + "\n".join(lines) + "\n\\bottomrule\n\\end{tabular}\n")
print("wrote", fpath, "and 5 tables")
