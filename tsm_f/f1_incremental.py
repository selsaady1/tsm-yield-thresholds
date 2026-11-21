"""Follow-up to f1: predict deterioration versus zero spread when service is already short."""
import json
from functools import lru_cache
import pulp as lp
import f1
from common import ROOT, arguments, dump, rc, recorded, sha, tsmb_common

def predict(lag,fw,bw):
    groups = [out for _,out in f1.release_nodes([f1.MU],False,lag)]
    @lru_cache(None)
    def shortage(a):
        # Separate conditional dispatch problem. No FE yield spread or measured onset input.
        prob = lp.LpProblem("native_die_budget",lp.LpMaximize)
        profit,miss = [],[]
        for j,out in enumerate(groups):
            q,net,m = f1.downstream(prob,str(j),out,bw)
            g = lp.LpVariable(f"external_{j}",0,f1.LG)
            prob += q <= a+g
            profit.append(net-f1.INST["c_G"]*g)
            miss.append(m)
        prob += lp.lpSum(profit)
        prob.solve(tsmb_common.solver())
        return lp.value(lp.lpSum(miss))/len(groups)

    @lru_cache(None)
    def ev(h):
        fe = rc.two_point(f1.MU,h)
        _,x,_ = f1.plan(f1.release_nodes(fe,True,lag),fw,bw)
        n_starts = f1.N*sum(x.values())
        return fe[0]*n_starts, fe[1]*n_starts
    a0,_ = ev(0)
    # At this physical upper bound all internal/external BE routes can be filled.
    upper = sum(f1.INST["L_B"].values())+sum(f1.INST["L_A"].values())
    m0 = shortage(a0)
    m_inf = shortage(upper)
    low_target = 2*m0-m_inf
    def exceeds(a):
        return shortage(a) > low_target+2*f1.SERVICE_EPS
    if not exceeds(0):
        critical = 0
    else:
        if exceeds(upper):
            raise ValueError("Abundant-supply breakpoint not bracketed")
        a,b = 0,upper
        while b-a>1e-4:
            mid = (a+b)/2
            if exceeds(mid):
                a = mid
            else:
                b = mid
        critical = (a+b)/2
    def point(h):
        return {"low_short":critical-ev(h)[0]}
    pred = f1.first_cross(point,"low_short",f1.GRID)
    high_miss = None if pred is None else shortage(ev(pred)[1])
    return dict(native_critical=critical,rho=critical/a0,baseline_native=a0,
                baseline_unmet=m0,abundant_unmet=m_inf,low_branch_unmet_target=low_target,
                predicted=pred,high_branch_unmet_at_prediction=high_miss,
                high_saturated=high_miss is not None and abs(high_miss-m_inf)<=f1.SERVICE_EPS)

def main():
    smoke = arguments().smoke
    source = ROOT / "results" / ("f1_smoke" if smoke else "f1")
    source_meta = json.loads((source/"run.json").read_text())
    if source_meta["status"] != "passed" or sha(source/"summary.json") != source_meta["output_sha256"]["summary.json"]:
        raise RuntimeError("Incomplete f1 input")
    with recorded("f1_incremental",smoke) as folder:
        cases = json.loads((source/"summary.json").read_text())
        rows = []
        for case in cases:
            candidate = predict(case["lag"],case["fe_wip"],case["be_wip"])
            actual = case["own_onset"]
            p = candidate["predicted"]
            err = None if p is None or actual is None else abs(p-actual)
            rows.append(dict(config=case["config"],**candidate,observed=actual,error=err,
                             hit=f1.agrees(p,actual)))
        dump(folder/"summary.json",rows)
    path = folder/"run.json"
    meta = json.loads(path.read_text())
    for p in [ROOT/"f1.py",source/"run.json",source/"summary.json"]:
        meta["input_sha256"][str(p.relative_to(ROOT))] = sha(p)
    dump(path,meta)

if __name__ == "__main__":
    main()

