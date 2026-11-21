"""run_r02_aggregation.py: tool-group disaggregation and non-identical fabs (R1.7b).

Configurations (single period, FE half-range sweep, BE 0.70/0.90):
  agg_ref      paper's aggregate model (reference)
  tg3          each fab split into litho / etch / implant tool groups
               (tsmb_sweeps.TOOL_GROUPS); bottleneck = aggregate capacity
  tg3_tight    as tg3 but every non-bottleneck group has only 2% slack
  ni_main      non-identical fabs: FE2 mean yield 0.825 (FE1 0.875), FE2
               wafer cost $1.65 (FE1 $1.50), yields independent across fabs
  ni_yield     FE2 mean yield 0.825, same cost, yields move together
  ni_cost      same yields, FE2 wafer cost $1.65
For each: %VSS and service-gap crossings, solved gap onset and the onset
predicted by the generalised cliff condition from the EV plan.
Usage: nice -n 10 $PY run_r02_aggregation.py [--smoke]
"""
import json
import sys

from tsmb_common import Run, write_csv
import revision_common as rc
import tsmb_static as ts
import tsmb_sweeps as sw

SMOKE = "--smoke" in sys.argv
run = Run("tsmb_r02_aggregation" + ("_smoke" if SMOKE else ""),
          "R1.7b: tool-group disaggregation and non-identical fabs; threshold and rho check",
          [__file__, sw.__file__, ts.__file__, rc.__file__])
halves = [0.075, 0.20, 0.40] if SMOKE else sw.HALVES
base = rc.base_inst()
tight = {"load": sw.TOOL_GROUPS["load"],
         "cap": {"FE1": {"litho": 10.0, "etch": 0.8 * 10 * 1.02, "implant": 0.5 * 10 * 1.02},
                 "FE2": {"litho": 1.0 * 8 * 1.02, "etch": 6.4, "implant": 0.5 * 8 * 1.02}}}
CONFIGS = [
    {"name": "agg_ref", "inst": base},
    {"name": "tg3", "inst": base, "groups": sw.TOOL_GROUPS},
    {"name": "tg3_tight", "inst": base, "groups": tight},
    {"name": "ni_main", "inst": base, "fe2_mean": 0.825, "corr": False,
     "c_F_f": {"FE1": 1.50, "FE2": 1.65}},
    {"name": "ni_yield", "inst": base, "fe2_mean": 0.825, "corr": True},
    {"name": "ni_cost", "inst": base, "c_F_f": {"FE1": 1.50, "FE2": 1.65}},
]
run.log("tool groups: " + json.dumps(sw.TOOL_GROUPS) + " | tight: " + json.dumps(tight))
rows, summary = [], []
ref_rows = None
for cfg in CONFIGS:
    rs = sw.sweep(cfg, halves, run.progress)
    if cfg["name"] == "agg_ref":
        ref_rows = rs
    s = sw.summarize(cfg, rs)
    s.update(sw.cliff(cfg, rs))
    if ref_rows is not None and cfg["name"].startswith("tg"):
        s["max_abs_dev_rp_obj_vs_agg"] = max(abs(a["rp_obj"] - b["rp_obj"]) for a, b in zip(rs, ref_rows))
        s["max_abs_dev_eev_obj_vs_agg"] = max(abs(a["eev_obj"] - b["eev_obj"]) for a, b in zip(rs, ref_rows))
    summary.append(s)
    for r in rs:
        r.pop("_raw", None)
        r["config"] = cfg["name"]
    rows += rs
    run.log(f"{cfg['name']}: %VSS(0.075)={s['pct_vss_at_0.075']:.3f} 2%@{s['vss2_half']} "
            f"gap>1@{s['gap1_half']} onset solved {s['gap_onset_solved']} pred {s['gap_onset_pred']} "
            f"util RP {s['rp_u1_at_0.075']:.3f}/{s['rp_u2_at_0.075']:.3f} nonopt {s['nonoptimal']}")

fields = ["config"] + [k for k in rows[0] if k != "config"]
write_csv(run.path("sweep.csv"), rows, fields)
sf = sorted({k for s in summary for k in s}, key=lambda k: (k != "config", k))
write_csv(run.path("summary.csv"), summary, sf)
ok = all(r["ok"] for r in rows)
run.finish("OK" if ok else "PARTIAL", ["sweep.csv", "summary.csv", "log.txt"],
           notes=f"all optimal: {ok}; smoke={SMOKE}")
