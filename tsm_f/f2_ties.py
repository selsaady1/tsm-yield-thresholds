"""Cross-evaluate the EV policies in neutral-route controls with material EEV differences."""
import csv
import json
import math
from common import ROOT, arguments, dump, recorded, sha
import f2

def main():
    smoke = arguments().smoke
    inputs = ROOT / "results/f2"
    design = {r["case"]:r for r in json.loads((inputs/"design.json").read_text())}
    with (inputs/"sweep.csv").open() as stream:
        rows = [r for r in csv.DictReader(stream) if design[r["case"]]["contrast"]==0
                and abs(float(r["tools_eev"])-float(r["agg_eev"]))>.01]
    rows.sort(key=lambda r:-abs(float(r["tools_eev"])-float(r["agg_eev"])))
    with recorded("f2_ties",smoke) as folder:
        checks = []
        for row in rows[:1] if smoke else rows:
            case = design[row["case"]]
            inst,mu,bl,bh = f2.ri.build(case["params"])
            h = float(row["h"])
            S = f2.scenarios(inst,mu,bl,bh,h,case["share"])
            mean = [(math.fsum(s[0] for s in S)/len(S),math.fsum(s[1] for s in S)/len(S),
                     tuple(math.fsum(s[2][j] for s in S)/len(S) for j in (0,1)))]
            pars = ((10+case["premium"],10-case["premium"]),f2.recipes(0),f2.caps(inst))
            evs = {}
            for flag in (False,True):
                evs[flag] = f2.model_solve(inst,mean,*pars,flag)[:2]
            primary_diff = abs(evs[False][0]-evs[True][0])
            if primary_diff>.001:
                raise AssertionError("EV solutions do not tie")
            detail = dict(case=row["case"],h=h,ev_obj_difference=primary_diff)
            for flag,label in ((False,"agg"),(True,"tools")):
                _,x = evs[flag]
                detail[label+"_ev_A"] = sum(v for (f,p),v in x.items() if p=="A")
                detail[label+"_ev_B"] = sum(v for (f,p),v in x.items() if p=="B")
                alt_ev = f2.model_solve(inst,mean,*pars,not flag,fixed=x)[0]
                alt_eev = f2.model_solve(inst,S,*pars,not flag,fixed=x)[0]
                detail[label+"_cross_eev"] = alt_eev
                detail[label+"_fixed_gap"] = abs(alt_eev-float(row[label+"_eev"]))
                if abs(alt_ev-evs[not flag][0])>.001 or detail[label+"_fixed_gap"]>.001:
                    raise AssertionError("A fixed EV policy failed the cross-model check")
            checks.append(detail)
        dump(folder/"checks.json",checks)
    meta_path = folder/"run.json"
    meta = json.loads(meta_path.read_text())
    for p in [ROOT/"f2.py",inputs/"run.json",inputs/"design.json",inputs/"sweep.csv"]:
        meta["input_sha256"][str(p.relative_to(ROOT))] = sha(p)
    dump(meta_path,meta)

if __name__=="__main__":
    main()

