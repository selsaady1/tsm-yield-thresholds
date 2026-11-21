"""Regenerate both registries and all supplement fragments from completed full runs."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
RUNS = ("baseline","f1_smoke","f2_smoke","f1","f2","f1_incremental_smoke","f1_incremental","f2_ties_smoke","f2_ties")

def load(path):
    return json.loads(path.read_text())

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def checked_runs():
    records = {}
    for name in RUNS:
        folder = ROOT/"results"/name
        meta = load(folder/"run.json")
        if meta["status"] != "passed" or meta["nonoptimal_solve_count"] != 0:
            raise RuntimeError(f"Results did not pass: {name}")
        for base,field in ((ROOT,"input_sha256"),(folder,"output_sha256")):
            for file,expected in meta[field].items():
                if digest(base/file) != expected:
                    raise RuntimeError(f"Hash mismatch in {name}: {file}")
        for copied,original in meta["import_sources"].items():
            if digest(ROOT/copied) != digest(ROOT.parents[1]/original):
                raise RuntimeError(f"Upstream import differs: {original}")
        records[name] = meta
    return records

class Registry:
    def __init__(self):
        self.data = {}
        self.display = {}
    def add(self, key, value, digits=None):
        key = "TSMF_"+key
        if key in self.data:
            raise ValueError(key)
        self.data[key] = value
        if value is None:
            text = "--"
        elif digits is None:
            text = str(value)
        else:
            text = f"{value:.{digits}f}"
            if text.startswith("-") and float(text)==0:
                text = text[1:]
        self.display[key] = text
        return r"\NUM{"+key+"}"

def table(caption,cols,header,rows):
    lines = ["% "+caption,r"\begingroup\setlength{\tabcolsep}{2pt}",r"\begin{tabular}{"+cols+"}",r"\hline",
             " & ".join(header)+r" \\",r"\hline"]
    lines.extend(" & ".join(row)+r" \\" for row in rows)
    lines += [r"\hline",r"\end{tabular}",r"\endgroup",""]
    return "\n".join(lines)

def render():
    runs = checked_runs()
    reg = Registry()
    add = reg.add
    baseline = load(ROOT/"results/baseline/values.json")
    for key,k in (("RP","rp_obj"),("EEV","eev_obj"),("VSS","vss")):
        add("BASE_"+key,baseline[k],2)
    for mode,meta in runs.items():
        add(mode.upper()+"_SOLVES",meta["solve_count"])
        add(mode.upper()+"_NONOPT",meta["nonoptimal_solve_count"])
        add(mode.upper()+"_SECONDS",meta["runtime_seconds"],2)
    add("ALL_SOLVES",sum(x["solve_count"] for x in runs.values()))
    add("ALL_NONOPT",sum(x["nonoptimal_solve_count"] for x in runs.values()))
    def rows(run):
        return load(ROOT/"results"/run/"summary.json")
    f1 = rows("f1")
    follow = {x["config"]:x for x in rows("f1_incremental")}
    f2 = rows("f2")
    if len(f1)!=8 or set(follow)!={x["config"] for x in f1}:
        raise ValueError("Incomplete f1")
    designs = [x for x in f2 if x["kind"]=="designed"]
    randoms = [x for x in f2 if x["kind"]=="random"]
    if len(designs)!=18 or len(randoms)!=30 or len({x["case"] for x in f2})!=48:
        raise ValueError("Incomplete f2")
    with (ROOT/"results/f2/sweep.csv").open() as fp:
        points = list(csv.DictReader(fp))
    if len(points)!=48*51 or len({(r["case"],r["h"]) for r in points})!=len(points):
        raise ValueError("Incomplete f2 half-range grid")
    add("F1_CASES",len(f1))
    add("F1_ABUNDANT_HITS",sum(x["hit"] for x in f1))
    add("F1_ORIGINAL_HITS",sum(x["old_hit"] for x in f1))
    add("F1_ALREADY_SHORT",sum(x["observed"]==0 for x in f1))
    add("F1_INCREMENTAL_HITS",sum(x["hit"] for x in follow.values()))
    add("F1_INCREMENTAL_HIGH_SATURATED",sum(x["high_saturated"] for x in follow.values()))
    add("F1_INCREMENTAL_MAX_ERROR",max(x["error"] for x in follow.values()),5)
    add("F1_ORIGINAL_INCREMENTAL_HITS",sum(abs(x["original_pred"]-x["own_onset"])<=.005 for x in f1))
    add("F1_REF_MAX_DOLLAR_ERROR",max(x["crosscheck_error"] for x in f1 if x["crosscheck_error"] is not None),7)
    mu = load(ROOT/"results/f2/design.json")[0]["params"]["fe_mean"]
    def closed_form(rho):
        if rho <= 0:
            return None
        if rho >= 1:
            return 0.0
        h = (1-rho)*mu
        if h > 1-mu:
            h = mu-rho/(2-rho)
        return h if h <= .50 else None
    analytic_errors = []
    f1rows = []
    for case in f1:
        name = case["config"]
        inc = follow[name]
        def field(k,v,dec=4):
            return add("F1_"+name+"_"+k,v,dec)
        first = field("RHO_REFERENCE",case["rho"])
        pred = field("PRED_REFERENCE",case["generalized_pred"])
        obs = field("OBS_REFERENCE",case["observed"])
        inc_rho = field("RHO_INCREMENT",inc["rho"])
        field("PRED_INCREMENT",inc["predicted"])
        analytic = closed_form(inc["rho"])
        inc_pred = field("ANALYTIC_INCREMENT",analytic)
        analytic_errors.append(abs(analytic-inc["observed"]))
        own = field("OBS_INCREMENT",case["own_onset"])
        field("ORIGINAL",case["original_pred"])
        field("GAP_ONSET",case["gap_onset"])
        field("BASE_VSS_PCT",case["base_vss_pct"],2)
        f1rows.append([str(case["lag"]),str(case["fe_wip"]),str(case["be_wip"]),first,pred,obs,inc_rho,inc_pred,own])
    add("F1_ANALYTIC_INCREMENTAL_HITS",sum(e<=.005 for e in analytic_errors))
    add("F1_ANALYTIC_INCREMENTAL_MAX_ERROR",max(analytic_errors),7)
    tables = {"f1_cliffs":table("Single-cohort service cliffs; lead, FE and BE are switches. "
            "The first target is service with abundant native dies; the second is own zero-spread service.",
            "cccrrrrrr",["Lead","FE","BE",r"$\rho_{\rm ref}$","Pred.","Obs.",
            r"$\rho_{\rm inc}$","Pred.","Obs."],f1rows)}
    def mix_table(group,label):
        output = []
        for x in group:
            def val(k,field,dec):
                return add("F2_"+x["case"]+"_"+k,x[field],dec)
            def threshold(model):
                key = "F2_"+x["case"]+"_"+model.upper()
                add(key+"_CLASS",x[model+"_class"])
                macro = add(key+"_H2",x[model+"_threshold"],3)
                return {"at_first":r"$\leq .01$","crossed":macro,"unreached":"--"}[x[model+"_class"]]
            output.append([x["case"],val("SHARE","share",2),val("CONTRAST","contrast",2),
                           val("PREMIUM","premium",2),val("LOSS","base_loss",2),
                           val("VSS_AGG","base_agg_vss_pct",2),val("VSS_TOOLS","base_tools_vss_pct",2),
                           threshold("agg"),threshold("tools")])
            val("MIN_TOOL_UTIL","base_min_tool_util",4)
            val("MAX_LOSS","max_loss",2)
        return table(label+" paired product mixes. Profit and VSS at h=.075. h2 is the first 2% crossing.", 
                     "lrrrrrrrr",["ID",r"$s_A$",r"$\delta$",r"$\pi$",r"$\Delta$ RP (\$)",
                     r"\%VSS A",r"\%VSS T",r"$h_2$ A",r"$h_2$ T"],output)
    tables["f2_configs"] = mix_table(designs,"Designed")
    tables["f2_random"] = mix_table(randoms,"Random")
    groups = (("DESIGNED",designs),("RANDOM",randoms))
    summary_rows = []
    for label,group in groups:
        def stat(k,v,dec=None):
            return add("F2_"+label+"_"+k,v,dec)
        summary_rows.append([label.title(),stat("N",len(group)),
            stat("BASE_LOSSES",sum(x["base_loss"]>.01 for x in group)),
            stat("ANY_LOSSES",sum(x["max_loss"]>.01 for x in group)),
            stat("BASE_UNROUTABLE",sum(x["base_agg_infeasible"] for x in group)),
            stat("MEDIAN_BASE_LOSS",median(x["base_loss"] for x in group),2),
            stat("MAX_BASE_LOSS",max(x["base_loss"] for x in group),2),
            stat("CLASS_CHANGES",sum(x["agg_class"]!=x["tools_class"] for x in group))])
        stat("MAX_BASE_LOSS_PCT",max(x["base_loss_pct"] for x in group),2)
        stat("MAX_GRID_LOSS",max(x["max_loss"] for x in group),2)
        stat("AT_FIRST",sum(x["tools_class"]=="at_first" for x in group))
        stat("CROSSED",sum(x["tools_class"]=="crossed" for x in group))
        stat("UNREACHED",sum(x["tools_class"]=="unreached" for x in group))
    neutral = [x for x in designs if x["contrast"]==0]
    add("F2_NEUTRAL_N",len(neutral))
    add("F2_NEUTRAL_MAX_RP_DIFF",max(abs(float(r["tools_rp"])-float(r["agg_rp"]))
        for r in points if r["case"] in {x["case"] for x in neutral}),7)
    add("F2_NEUTRAL_MAX_EEV_DIFF",max(x["max_eev_absdiff"] for x in neutral),7)
    ties = load(ROOT/"results/f2_ties/checks.json")
    add("F2_NEUTRAL_TIE_POINTS",len(ties))
    add("F2_NEUTRAL_TIE_CASES",len({x["case"] for x in ties}))
    add("F2_NEUTRAL_TIE_EV_MAX_DIFF",max((x["ev_obj_difference"] for x in ties),default=0),7)
    add("F2_NEUTRAL_TIE_CROSS_EEV_MAX_DIFF",max((x[k] for x in ties for k in
        ("agg_fixed_gap","tools_fixed_gap")),default=0),7)
    add("F2_GRID_PAIRS",len(points))
    tables["f2_summary"] = table("Counts by design. Loss means aggregate RP exceeds tool RP by more than one cent. "
        "Unroutable is the aggregate optimal mix returned by CBC at h=.075, after optimal fab reassignment.",
        "lrrrrrrr",["Set","Cases",r"Loss$_{.075}$","Any loss","Unroutable","Median (\\$)",
                    "Max (\\$)",r"Changed $h_2$ class"],summary_rows)
    return reg,tables

def main():
    cli = argparse.ArgumentParser()
    group = cli.add_mutually_exclusive_group()
    group.add_argument("--print",dest="key",metavar="KEY")
    group.add_argument("--check",action="store_true")
    args = cli.parse_args()
    reg,tables = render()
    if args.key:
        if args.key not in reg.data:
            cli.error("unknown number: "+args.key)
        print(reg.display[args.key])
        return
    tex = [r"\makeatletter",r"\providecommand{\NUM}[1]{\@nameuse{tsmnum@#1}}",
           r"\providecommand{\setnum}[2]{\@namedef{tsmnum@#1}{#2}}",r"\makeatother"]
    for k,v in reg.display.items():
        texval = v.replace("_",r"\_")
        tex.append(r"\setnum{"+k+"}{"+texval+"}")
    outputs = {"numbers.json":json.dumps(reg.data,indent=2,allow_nan=False)+"\n",
               "numbers.tex":"\n".join(tex)+"\n"}
    outputs.update({"tables/tab_tsm_f_"+k+".tex":v for k,v in tables.items()})
    for name,body in outputs.items():
        path = ROOT/name
        if args.check:
            if path.read_text()!=body:
                raise ValueError("Stale generated file: "+name)
        else:
            path.parent.mkdir(exist_ok=True)
            path.write_text(body)
    print(f"{len(reg.data)} keys, {len(tables)} tables; verified input/output hashes for {len(RUNS)} runs.")

if __name__ == "__main__":
    main()

