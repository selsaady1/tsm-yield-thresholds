"""make_numbers.py: NUMBERS REGISTRY for prompt tsm_b.

Reads only the run folders results/tsm_b/<run_id>/ (and design constants of
the tsm_b scripts) and writes
  OUT/numbers.json      one entry per key (rule R2)
  numbers.tex           \\setnum lines (SANDBOX root and revision/paper/)
Usage:
  $PY code/tsm_b/make_numbers.py               write the files
  $PY code/tsm_b/make_numbers.py --print KEY   print one key's value and display
"""
import csv
import json
import math
import os
import sys

from tsmb_common import RESULTS_ROOT, SANDBOX
import tsmb_sweeps as sw
import tsmb_static as ts

OUT = os.path.join(SANDBOX, "OUT")
REC = "$PY code/tsm_b/make_numbers.py --print {key}"
NUMS = []


def rows(run, name):
    with open(os.path.join(RESULTS_ROOT, run, name)) as fh:
        return list(csv.DictReader(fh))


def cell(run, name, config, col):
    r = next(r for r in rows(run, name) if r["config"] == config)
    return r[col]


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def disp(v, dec, kind="plain"):
    if v is None:
        return None
    if kind == "pct100":
        return f"{100 * v:.{dec}f}\\%"
    if v < 0 and round(v, dec) != 0:
        return f"${v:.{dec}f}$"
    return f"{v:.{dec}f}"


def add(key, value, display, decimals, unit, meaning, run, file, row, col, typ="number"):
    NUMS.append({"key": key, "display": display, "value": value, "decimals": decimals,
                 "unit": unit, "type": typ, "meaning": meaning, "producer": "tsm_b",
                 "source": {"run": f"results/tsm_b/{run}/" if run else "code/tsm_b/",
                            "file": file, "row": row, "col": col},
                 "recompute": REC.format(key=key)})


def from_summary(key, run, config, col, dec, unit, meaning, kind="plain",
                 special=None):
    raw = cell(run, "summary.csv", config, col)
    v = fnum(raw)
    if v is None:
        special = special or {}
        d = special.get(raw, raw)
        add(key, raw, d, None, unit, meaning + f" (non-numeric outcome '{raw}')", run,
            "summary.csv", f"config=={config}", col)
    else:
        add(key, v, disp(v, dec, kind), dec, unit, meaning, run, "summary.csv",
            f"config=={config}", col)
    return v if v is not None else raw


R1, R2, R3, R0 = "tsmb_r01_leadtime", "tsmb_r02_aggregation", "tsmb_r03_congestion", "tsmb_r00_validate"
NEVER = {"none": "not reached by 0.50",
         "below_grid": "below 0.01"}

# ---------------------------------------------------------------- reference (paper model, recomputed)
from_summary("TSMB_ref_thr", R1, "P1_l0", "vss2_half", 3, "FE half-range",
             "paper's single-period model recomputed in run r01: %VSS=2% crossing")
from_summary("TSMB_ref_cliff_hr", R1, "P1_l0", "gap1_half", 3, "FE half-range",
             "paper's model: service gap > 1 unit")
from_summary("TSMB_ref_onset", R1, "P1_l0", "gap_onset_solved", 3, "FE half-range",
             "paper's model: solved onset of the service gap (bisection)")
from_summary("TSMB_ref_gap50", R1, "P1_l0", "gap_pp_at_0.50", 1, "units",
             "paper's model: service gap at half-range 0.50")

# ---------------------------------------------------------------- R1.7c lead time and inventory
from_summary("TSMB_lt_vss_pct_2stage", R1, "P4_l1", "pct_vss_at_0.075", 2, "%",
             "%VSS at the base half-range 0.075, T=4, BE lead time 1, two-stage (all starts fixed now)")
from_summary("TSMB_lt_vss_pct_multi", R1, "P4_l1_m1", "pct_vss_at_0.075", 2, "%",
             "%VSS at 0.075, T=4, BE lead time 1, multistage with FE lead time 1 (versus EEV)")
from_summary("TSMB_lt_thr", R1, "P4_l1", "vss2_half", 3, "FE half-range",
             "%VSS=2% crossing, T=4, BE lead time 1, two-stage", special=NEVER)
v = from_summary("TSMB_lt_cliff_hr", R1, "P4_l1", "gaprise1_half", 3, "FE half-range",
                 "cliff onset in the multi-period model (T=4, BE lead time 1): first half-range where the "
                 "per-period service gap rises more than one unit above its value at half-range 0.01",
                 special={"none": "none in sweep"})
from_summary("TSMB_lt_gap_base", R1, "P4_l1", "gap_pp_at_0.075", 1, "units per period",
             "per-period service gap at 0.075, T=4, BE lead time 1")
from_summary("TSMB_lt_onset", R1, "P4_l1", "gap_onset_solved", 3, "FE half-range",
             "solved start of the rise of the per-period gap, T=4, BE lead time 1")
from_summary("TSMB_lt_pred", R1, "P4_l1", "gap_onset_pred_rho", 3, "FE half-range",
             "onset predicted by condition (12) applied per period to the EV plan, T=4, BE lead time 1")
from_summary("TSMB_lt_rise50", R1, "P4_l1", "gap_rise_0.01_to_0.50", 1, "units per period",
             "rise of the per-period gap from half-range 0.01 to 0.50, T=4, BE lead time 1")
from_summary("TSMB_lt1_vss_pct", R1, "P1_l1", "pct_vss_at_0.075", 2, "%",
             "%VSS at 0.075, one period with BE lead time 1")
from_summary("TSMB_lt1_gap_base", R1, "P1_l1", "gap_pp_at_0.075", 1, "units",
             "service gap at 0.075, one period with BE lead time 1")
from_summary("TSMB_lt1_cliff_hr", R1, "P1_l1", "gaprise1_half", 3, "FE half-range",
             "cliff onset (gap rise > 1), one period with BE lead time 1", special={"none": "none in sweep"})
from_summary("TSMB_lt1_rise50", R1, "P1_l1", "gap_rise_0.01_to_0.50", 1, "units",
             "rise of the gap from 0.01 to 0.50, one period with BE lead time 1")
from_summary("TSMB_inv_vss_pct", R1, "P4_l0", "pct_vss_at_0.075", 2, "%",
             "%VSS at 0.075, T=4 with die-bank inventory, no lead time")
from_summary("TSMB_inv_thr", R1, "P4_l0", "vss2_half", 3, "FE half-range",
             "%VSS=2% crossing, T=4 with inventory, no lead time", special=NEVER)
from_summary("TSMB_inv_cliff_hr", R1, "P4_l0", "gap1_half", 3, "FE half-range",
             "per-period service gap > 1, T=4 with inventory, no lead time", special={"none": "none in sweep"})
from_summary("TSMB_inv_onset", R1, "P4_l0", "gap_onset_solved", 3, "FE half-range",
             "solved onset of the gap, T=4 with inventory, no lead time")
from_summary("TSMB_inv_pred", R1, "P4_l0", "gap_onset_pred_rho", 3, "FE half-range",
             "onset predicted by (12) per period, T=4 with inventory, no lead time")
from_summary("TSMB_inv_gap50", R1, "P4_l0", "gap_pp_at_0.50", 1, "units per period",
             "per-period gap at 0.50, T=4 with inventory, no lead time")
from_summary("TSMB_inv_rp_inv_max", R1, "P4_l0", "max_rp_inv_pp", 1, "dies per period",
             "largest average die-bank stock per period of the stochastic plan over the sweep, T=4, no lead time")
from_summary("TSMB_inv_eev_inv_max", R1, "P4_l0", "max_eev_inv_pp", 1, "dies per period",
             "largest average die-bank stock per period of the deterministic plan (EEV) over the sweep, T=4, no lead time")
# stock of each plan (T=4, no lead time) and the half-range at which the stochastic plan starts holding stock
swl = [r for r in rows(R1, "sweep.csv") if r["config"] == "P4_l0"]
swl.sort(key=lambda r: float(r["half"]))
b = next(r for r in swl if abs(float(r["half"]) - 0.075) < 1e-9)
add("TSMB_inv_eev_inv_base", float(b["eev_inv_pp"]), f"{float(b['eev_inv_pp']):.0f}", 0, "dies per period",
    "average die-bank stock per period of the deterministic plan (EEV), T=4, no lead time, h=0.075",
    R1, "sweep.csv", "config==P4_l0, half==0.075", "eev_inv_pp")
add("TSMB_inv_rp_inv_base", float(b["rp_inv_pp"]), f"{abs(float(b['rp_inv_pp'])):.0f}", 0, "dies per period",
    "average die-bank stock per period of the stochastic plan, T=4, no lead time, h=0.075 (solver value of order 1e-12)",
    R1, "sweep.csv", "config==P4_l0, half==0.075", "rp_inv_pp")
first = next(r for r in swl if float(r["rp_inv_pp"]) > 1e-6)
prev = swl[swl.index(first) - 1]
assert float(first["rp_starts_pp"]) >= 18.0 - 1e-6 and float(prev["rp_starts_pp"]) < 18.0 - 1e-6, "stock onset != FE saturation"
add("TSMB_inv_rp_stock_first", float(first["half"]), f"{float(first['half']):.2f}", 2, "FE half-range",
    "first grid half-range at which the stochastic plan holds die-bank stock (T=4, no lead time); checked to be the "
    "first grid point at which its wafer starts equal the FE capacity of 18 wafers per period",
    R1, "sweep.csv", "config==P4_l0", "rp_inv_pp, rp_starts_pp")
vms = [abs(float(r["vms"])) for r in rows(R1, "sweep.csv") if r.get("vms")]
add("TSMB_lt_vms_absmax", max(vms), f"{max(vms):.2f}", 2, "$",
    "largest |RP multistage - RP two-stage| over all half-ranges, T=3 and T=4, FE lead time 1 and 2 (solver precision)",
    R1, "sweep.csv", "config in (P4_l1_m1,P4_l1_m2,P3_l1_m1,P3_l1_m2)", "vms")
for cfg, key in [("P4_l1_m1", "TSMB_lt_vms_max_m1"), ("P4_l1_m2", "TSMB_lt_vms_max_m2"),
                 ("P3_l1_m1", "TSMB_lt3_vms_max_m1"), ("P3_l1_m2", "TSMB_lt3_vms_max_m2")]:
    from_summary(key, R1, cfg, "vms_max", 2, "$",
                 f"largest value of the multistage over the two-stage solution over the sweep ({cfg})")
from_summary("TSMB_lt_rh_vss_pct", R1, "P4_l1_m1", "pct_vss_vs_rh_at_0.075", 2, "%",
             "%VSS of the multistage plan against a rolling deterministic plan, 0.075, T=4, lB=1, lF=1")
from_summary("TSMB_lt_rh_thr", R1, "P4_l1_m1", "vss2_vs_rh_half", 3, "FE half-range",
             "2% crossing against the rolling deterministic plan", special=NEVER)
from_summary("TSMB_lt_vss_pct_multi2", R1, "P4_l1_m2", "pct_vss_at_0.075", 2, "%",
             "%VSS at 0.075, multistage with FE lead time 2")


def effect(single, multi, onset_col):
    """Rule for TSMB_*_cliff_effect: compare the multi-period configuration with
    the single-period one with the same BE lead time.
      removes : no onset in the sweep for the multi-period model
      softens : onset later by >= 0.01, or (|diff| < 0.01 and the rise of the
                per-period gap from h=0.01 to h=0.50 is >10% smaller)
      sharpens: onset earlier by >= 0.01, or (|diff| < 0.01 and the rise >10% larger)
      does not change: otherwise"""
    s1 = next(r for r in rows(R1, "summary.csv") if r["config"] == single)
    s4 = next(r for r in rows(R1, "summary.csv") if r["config"] == multi)
    o1, o4 = fnum(s1[onset_col]), fnum(s4[onset_col])
    r1, r4 = fnum(s1["gap_rise_0.01_to_0.50"]), fnum(s4["gap_rise_0.01_to_0.50"])
    if o4 is None:
        return "removes", o1, o4, r1, r4
    if o4 - o1 >= 0.01:
        return "softens", o1, o4, r1, r4
    if o1 - o4 >= 0.01:
        return "sharpens", o1, o4, r1, r4
    if r4 < 0.9 * r1:
        return "softens", o1, o4, r1, r4
    if r4 > 1.1 * r1:
        return "sharpens", o1, o4, r1, r4
    return "does not change", o1, o4, r1, r4


for key, single, multi in [("TSMB_lt_cliff_effect", "P1_l1", "P4_l1"),
                           ("TSMB_inv_cliff_effect", "P1_l0", "P4_l0")]:
    word, o1, o4, r1, r4 = effect(single, multi, "gaprise1_half")
    NUMS.append({"key": key, "display": word, "value": word, "decimals": None, "unit": "",
                 "type": "text",
                 "meaning": f"effect of four periods with die-bank inventory on the cliff ({multi} vs {single}); "
                            f"onsets {o1} -> {o4}, gap rise {r1:.2f} -> {r4:.2f}; rule: " + effect.__doc__.split("\n", 1)[1].strip(),
                 "producer": "tsm_b",
                 "source": {"run": f"results/tsm_b/{R1}/", "file": "summary.csv",
                            "row": f"config in ({single},{multi})",
                            "col": "gaprise1_half, gap_rise_0.01_to_0.50"},
                 "recompute": REC.format(key=key)})

# ---------------------------------------------------------------- R1.7b tool groups and non-identical fabs
from_summary("TSMB_agg_thr", R2, "tg3", "vss2_half", 3, "FE half-range",
             "%VSS=2% crossing with three tool groups per fab")
sol = fnum(cell(R2, "summary.csv", "tg3", "gap_onset_solved"))
pre = fnum(cell(R2, "summary.csv", "tg3", "gap_onset_pred"))
err = abs(sol - pre)
add("TSMB_agg_rho_err", err, f"{math.ceil(max(err, 1e-12) * 1e4) / 1e4:.4f}", 4, "FE half-range",
    "|solved - predicted| gap onset with tool groups; display rounded up to the bisection tolerance 1e-4",
    R2, "summary.csv", "config==tg3", "gap_onset_solved - gap_onset_pred")
dev = max(fnum(cell(R2, "summary.csv", c, k)) for c in ("tg3", "tg3_tight")
          for k in ("max_abs_dev_rp_obj_vs_agg", "max_abs_dev_eev_obj_vs_agg"))
add("TSMB_agg_maxdev", dev, f"{dev:.2f}", 2, "$",
    "largest absolute difference of RP or EEV objective, tool-group vs aggregate model, over all half-ranges",
    R2, "summary.csv", "config in (tg3,tg3_tight)", "max_abs_dev_*_obj_vs_agg")
from_summary("TSMB_nonid_thr", R2, "ni_main", "vss2_half", 3, "FE half-range",
             "%VSS=2% crossing, non-identical fabs (FE2 mean yield 0.825, wafer cost 1.65, independent yields)",
             special=NEVER)
from_summary("TSMB_nonid_gap1", R2, "ni_main", "gap1_half", 3, "FE half-range",
             "service gap > 1, non-identical fabs")
sol = fnum(cell(R2, "summary.csv", "ni_main", "gap_onset_solved"))
pre = fnum(cell(R2, "summary.csv", "ni_main", "gap_onset_pred"))
err = abs(sol - pre)
add("TSMB_nonid_rho_err", err, f"{math.ceil(max(err, 1e-12) * 1e4) / 1e4:.4f}", 4, "FE half-range",
    "|solved - predicted| gap onset, non-identical fabs (generalised condition); display rounded up to 1e-4",
    R2, "summary.csv", "config==ni_main", "gap_onset_solved - gap_onset_pred")
from_summary("TSMB_nonid_onset", R2, "ni_main", "gap_onset_solved", 3, "FE half-range",
             "solved gap onset, non-identical fabs")
from_summary("TSMB_nonid_u1", R2, "ni_main", "rp_u1_at_0.075", 1, "%", "stochastic plan FE1 utilisation, non-identical fabs, 0.075", kind="pct100")
from_summary("TSMB_nonid_u2", R2, "ni_main", "rp_u2_at_0.075", 1, "%", "stochastic plan FE2 utilisation, non-identical fabs, 0.075", kind="pct100")
from_summary("TSMB_nonid_yield_thr", R2, "ni_yield", "vss2_half", 3, "FE half-range",
             "2% crossing, FE2 mean yield 0.825 only, yields move together")
from_summary("TSMB_nonid_cost_thr", R2, "ni_cost", "vss2_half", 3, "FE half-range",
             "2% crossing, FE2 wafer cost 1.65 only")

# ---------------------------------------------------------------- R1.8 congestion
P = lambda c, col: cell(R3, "summary.csv", c, col)
from_summary("TSMB_cong_util_fe1", R3, "cf_k1", "rp_u1_at_0.075", 1, "%", "stochastic plan FE1 utilisation with clearing function, 0.075", kind="pct100")
from_summary("TSMB_cong_util_fe2", R3, "cf_k1", "rp_u2_at_0.075", 1, "%", "stochastic plan FE2 utilisation with clearing function, 0.075", kind="pct100")
from_summary("TSMB_nocong_util_fe1", R3, "nocong", "rp_u1_at_0.075", 1, "%", "stochastic plan FE1 utilisation without congestion (solver's split), 0.075", kind="pct100")
from_summary("TSMB_nocong_util_fe2", R3, "nocong", "rp_u2_at_0.075", 1, "%", "stochastic plan FE2 utilisation without congestion (solver's split), 0.075", kind="pct100")
from_summary("TSMB_cong_evutil_fe1", R3, "cf_k1", "ev_u1_at_0.075", 1, "%", "deterministic plan FE1 utilisation with clearing function, 0.075", kind="pct100")
from_summary("TSMB_cong_evutil_fe2", R3, "cf_k1", "ev_u2_at_0.075", 1, "%", "deterministic plan FE2 utilisation with clearing function, 0.075", kind="pct100")
md = fnum(P("cf_k1", "max_abs_util_diff_rp"))
word = "becomes balanced" if md <= 0.02 else "does not become balanced"
NUMS.append({"key": "TSMB_cong_balanced", "display": word, "value": word, "decimals": None, "unit": "",
             "type": "text",
             "meaning": f"rule: 'becomes balanced' if the largest |u_FE1 - u_FE2| of the stochastic plan over all "
                        f"51 half-ranges is <= 0.02 (twice the 0.01 spacing of the linearisation points); "
                        f"observed {md:.4f}",
             "producer": "tsm_b", "source": {"run": f"results/tsm_b/{R3}/", "file": "summary.csv",
                                            "row": "config==cf_k1", "col": "max_abs_util_diff_rp"},
             "recompute": REC.format(key="TSMB_cong_balanced")})
add("TSMB_cong_maxdiff", md, f"{md:.3f}", 3, "utilisation", "largest |u_FE1-u_FE2| of the stochastic plan with clearing function over the sweep",
    R3, "summary.csv", "config==cf_k1", "max_abs_util_diff_rp")
from_summary("TSMB_cong_vss_pct", R3, "cf_k1", "pct_vss_at_0.075", 2, "%", "%VSS at 0.075 with clearing function")
from_summary("TSMB_cong_thr", R3, "cf_k1", "vss2_half", 3, "FE half-range", "%VSS=2% crossing with clearing function", special=NEVER)
from_summary("TSMB_cong_hedge_drop_pct", R3, "cf_k1", "hedge_drop_pct_vs_nocong", 0, "%",
             "reduction of the hedge (RP minus EV wafer starts) at 0.075 relative to no congestion")
from_summary("TSMB_cong_hedge", R3, "cf_k1", "hedge_at_0.075", 2, "wafers", "hedge with clearing function, 0.075")
from_summary("TSMB_nocong_hedge", R3, "nocong", "hedge_at_0.075", 2, "wafers", "hedge without congestion, 0.075")
from_summary("TSMB_cong_ct_rp", R3, "cf_k1", "rp_ct1_at_0.075", 2, "periods (x raw process time)", "cycle-time proxy W/x, stochastic plan, 0.075")
from_summary("TSMB_cong_ct_ev", R3, "cf_k1", "ev_ct1_at_0.075", 2, "periods (x raw process time)", "cycle-time proxy W/x, deterministic plan, 0.075")
from_summary("TSMB_cong_gap50", R3, "cf_k1", "gap_at_0.50", 1, "units", "service gap at 0.50 with clearing function")
from_summary("TSMB_cong_onset", R3, "cf_k1", "gap_onset_solved", 3, "FE half-range", "solved gap onset with clearing function")
from_summary("TSMB_cong_gap1", R3, "cf_k1", "gap1_half", 3, "FE half-range", "service gap > 1 with clearing function")
err = abs(fnum(P("cf_k1", "gap_onset_solved")) - fnum(P("cf_k1", "gap_onset_pred")))
add("TSMB_cong_rho_err", err, f"{math.ceil(max(err, 1e-12) * 1e4) / 1e4:.4f}", 4, "FE half-range",
    "|solved - predicted| gap onset with clearing function; display rounded up to 1e-4",
    R3, "summary.csv", "config==cf_k1", "gap_onset_solved - gap_onset_pred")
from_summary("TSMB_cong025_vss_pct", R3, "cf_k025", "pct_vss_at_0.075", 2, "%", "%VSS at 0.075, c_W x 0.25")
from_summary("TSMB_cong025_thr", R3, "cf_k025", "vss2_half", 3, "FE half-range", "2% crossing, c_W x 0.25", special=NEVER)
from_summary("TSMB_cong025_hedge_drop_pct", R3, "cf_k025", "hedge_drop_pct_vs_nocong", 0, "%", "hedge reduction, c_W x 0.25")
from_summary("TSMB_cong4_vss_pct", R3, "cf_k4", "pct_vss_at_0.075", 2, "%", "%VSS at 0.075, c_W x 4")
from_summary("TSMB_cong4_thr", R3, "cf_k4", "vss2_half", 3, "FE half-range", "2% crossing, c_W x 4", special=NEVER)
from_summary("TSMB_cong4_hedge", R3, "cf_k4", "hedge_at_0.075", 2, "wafers", "hedge (RP minus EV starts), c_W x 4")
from_summary("TSMB_cong4_onset", R3, "cf_k4", "gap_onset_solved", 3, "FE half-range", "solved gap onset, c_W x 4")
from_summary("TSMB_cong4_pred", R3, "cf_k4", "gap_onset_pred", 3, "FE half-range", "predicted onset of the deterministic plan's loss, c_W x 4")
# deterministic plan's own loss of service under c_W x 4: grid bracket
sw4 = [r for r in rows(R3, "sweep.csv") if r["config"] == "cf_k4"]
sw4.sort(key=lambda r: float(r["half"]))
e0 = float(sw4[0]["eev_unmet"])
i = next(i for i, r in enumerate(sw4) if float(r["eev_unmet"]) > e0 + 1e-6)
lo_h, hi_h = float(sw4[i - 1]["half"]), float(sw4[i]["half"])
add("TSMB_cong4_eevloss_lo", lo_h, f"{lo_h:.2f}", 2, "FE half-range",
    "c_W x 4: last grid half-range at which the deterministic plan's expected unmet demand equals its smallest-spread value",
    R3, "sweep.csv", "config==cf_k4", "eev_unmet")
add("TSMB_cong4_eevloss_hi", hi_h, f"{hi_h:.2f}", 2, "FE half-range",
    "c_W x 4: first grid half-range at which the deterministic plan's expected unmet demand exceeds its smallest-spread value",
    R3, "sweep.csv", "config==cf_k4", "eev_unmet")
from_summary("TSMB_congbe_vss_pct", R3, "cf_k1_be", "pct_vss_at_0.075", 2, "%", "%VSS at 0.075, clearing functions at FE and BE")
from_summary("TSMB_congbe_gap1", R3, "cf_k1_be", "gap1_half", 3, "FE half-range", "service gap > 1, FE and BE congestion")
from_summary("TSMB_congbe_onset", R3, "cf_k1_be", "gap_onset_solved", 4, "FE half-range", "solved gap onset, FE and BE congestion")
from_summary("TSMB_congbe_pred", R3, "cf_k1_be", "gap_onset_pred", 3, "FE half-range", "predicted onset with N_max solved under BE congestion")
from_summary("TSMB_congbe_nmax", R3, "cf_k1_be", "N_max", 0, "dies", "N_max solved under BE congestion")
from_summary("TSMB_tgcong_hedge_drop_pct", R3, "tg_cf_k1", "hedge_drop_pct_vs_nocong", 0, "%", "hedge reduction with one clearing function per tool group")
from_summary("TSMB_tgcong_thr", R3, "tg_cf_k1", "vss2_half", 3, "FE half-range", "2% crossing, clearing function per tool group", special=NEVER)
from_summary("TSMB_tgcong_vss_pct", R3, "tg_cf_k1", "pct_vss_at_0.075", 2, "%", "%VSS at 0.075, clearing function per tool group")
from_summary("TSMB_nicong_u1", R3, "ni_cf_k1", "rp_u1_at_0.075", 1, "%", "stochastic plan FE1 utilisation, non-identical fabs with congestion", kind="pct100")
from_summary("TSMB_nicong_u2", R3, "ni_cf_k1", "rp_u2_at_0.075", 1, "%", "stochastic plan FE2 utilisation, non-identical fabs with congestion", kind="pct100")
from_summary("TSMB_nicong_thr", R3, "ni_cf_k1", "vss2_half", 3, "FE half-range", "2% crossing, non-identical fabs with congestion", special=NEVER)
# clearing function versus convex-cost cross-check
swr = rows(R3, "sweep.csv")
a = {r["half"]: r for r in swr if r["config"] == "cf_k1"}
b = {r["half"]: r for r in swr if r["config"] == "pwl_k1"}
d = max(abs(float(a[h][c]) - float(b[h][c])) for h in a for c in ("rp_obj", "eev_obj"))
add("TSMB_pwl_maxdev", d, f"{d:.2f}", 2, "$", "largest |objective difference|, clearing function vs convex congestion cost, RP and EEV, all half-ranges",
    R3, "sweep.csv", "config in (cf_k1,pwl_k1)", "rp_obj, eev_obj")

# ---------------------------------------------------------------- design constants (inputs, stated in code)
const = [("TSMB_param_cW", sw.C_W_BASE, 3, "$ per wafer-period", "WIP cost c_W = c_K n mean FE yield", "tsmb_sweeps.py", "C_W_BASE"),
         ("TSMB_param_ntan", len(ts.U_GRID), 0, "count", "tangent points of each linearised clearing function", "tsmb_static.py", "U_GRID"),
         ("TSMB_param_fe2mean", 0.825, 3, "yield", "FE2 mean yield in the non-identical-fab variants", "run_r02_aggregation.py", "fe2_mean"),
         ("TSMB_param_fe2cost", 1.65, 2, "$ per wafer", "FE2 wafer cost in the non-identical-fab variants", "run_r02_aggregation.py", "c_F_f"),
         ("TSMB_param_leaves", 8 ** 4, 0, "scenarios", "leaves of the four-period tree (8 outcomes per period)", "tsmb_multiperiod.py", "Tree"),
         ("TSMB_param_nhalves", len(sw.HALVES), 0, "count", "half-ranges per sweep (0.01..0.50 step 0.01 plus 0.075)", "tsmb_sweeps.py", "HALVES")]
for key, val, dec, unit, meaning, f, r in const:
    add(key, val, (f"{val:,.0f}".replace(",", "{,}") if dec == 0 else f"{val:.{dec}f}"), dec, unit,
        meaning, None, f, r, "constant")

# run-size facts used in the text
nsolves = 0
for run in (R1, R2, R3):
    nsolves += len(rows(run, "sweep.csv"))
add("TSMB_n_points", nsolves, f"{nsolves:,}".replace(",", "{,}"), 0, "RP-EEV comparisons",
    "sweep points (each an RP, EV and EEV solve) in runs r01-r03, excluding bisection steps",
    "tsmb_r01..r03", "sweep.csv", "all rows", "count")

TABLES = {"tables": {"tab_tsm_b_extB.tex": "code/tsm_b/make_figs_tables.py",
                     "tab_tsm_b_S_leadtime.tex": "code/tsm_b/make_figs_tables.py",
                     "tab_tsm_b_S_aggcong.tex": "code/tsm_b/make_figs_tables.py",
                     "tab_tsm_b_S_ct.tex": "code/tsm_b/make_figs_tables.py",
                     "fig_tsm_b_extB.pdf": "code/tsm_b/make_figs_tables.py"}}

if "--print" in sys.argv:
    k = sys.argv[sys.argv.index("--print") + 1]
    e = next(e for e in NUMS if e["key"] == k)
    print(k, "value =", e["value"], "display =", e["display"])
    sys.exit(0)

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "numbers.json"), "w") as fh:
    json.dump(NUMS + [TABLES], fh, indent=1)
tex = ["\\makeatletter",
       "\\providecommand{\\NUM}[1]{\\@ifundefined{tsmnum@#1}{\\textcolor{red}{TODO-NUM: \\detokenize{#1}}}{\\@nameuse{tsmnum@#1}}}",
       "\\providecommand{\\setnum}[2]{\\@namedef{tsmnum@#1}{#2}}",
       "\\makeatother"]
for e in NUMS:
    if e["display"] is not None:
        tex.append(f"\\setnum{{{e['key']}}}{{{e['display']}}}")
for p in (os.path.join(SANDBOX, "numbers.tex"), os.path.join(SANDBOX, "revision", "paper", "numbers.tex")):
    with open(p, "w") as fh:
        fh.write("\n".join(tex) + "\n")
print(f"{len(NUMS)} keys written")
