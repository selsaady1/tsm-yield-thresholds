"""One release cohort; test a release-node extension of the paper's die-coverage cliff."""
from functools import lru_cache
from itertools import product

import pulp as lp
from common import (arguments, csv_rows, dump, rc, recorded, tsmb_common, tsmb_static as static,
                    tsmb_multiperiod as multi, tsmb_sweeps as sweeps)

INST = rc.base_inst()
MU = rc.FE_MEAN
GRID = sorted({0.0, 0.075, *rc.HALF_GRID})
# CBC solution text has limited precision. Units are devices per cohort and FE half-spread.
SERVICE_EPS = 1e-4
BISECT_TOL = 1e-5
HIT_TOL = 0.005
DEMAND = (INST["demand_lo"], INST["demand_hi"])
BE = (rc.BE_LO, rc.BE_HI)
LG = sum(INST["L_G"].values())
N = INST["n_f_i"]

def release_nodes(fe, deterministic, lag):
    levels = list(product(DEMAND, BE))
    if deterministic:
        return [(sum(fe)/2, [(sum(DEMAND)/2, sum(BE)/2)])]
    if lag:
        return [(y, levels) for y in fe]
    return [(y, [outcome]) for y in fe for outcome in levels]

def downstream(model, label, outcomes, be_wip):
    """One release decision, followed by its equiprobable demand/yield realizations."""
    release = {b: lp.LpVariable(f"k_{label}_{b}", 0, cap) for b,cap in INST["L_B"].items()}
    outside = lp.LpVariable(f"a_{label}", 0, sum(INST["L_A"].values()))
    k = lp.lpSum(release.values())
    cost = INST["c_B"] * k + INST["c_A"] * outside
    if be_wip:
        for b, x in release.items():
            wip = lp.LpVariable(f"wip_{label}_{b}", 0)
            static._cf_tangents(model, x, wip, INST["L_B"][b], 1, f"{label}_{b}")
            cost += INST["c_K"] * wip
    unmet, revenue = [], []
    for j,(d,by) in enumerate(outcomes):
        good = lp.LpVariable(f"good_{label}_{j}", 0)
        miss = lp.LpVariable(f"miss_{label}_{j}", 0)
        excess = lp.LpVariable(f"excess_{label}_{j}", 0)
        model += good <= by * k
        model += good + outside + miss - excess == d
        unmet.append(miss)
        revenue.append(INST["p_d"]*d - (INST["p_d"]+INST["v_d"])*miss - INST["c_D"]*excess)
    return k + outside, lp.lpSum(revenue)/len(outcomes) - cost, lp.lpSum(unmet)/len(outcomes)

def dispatch_need(outcomes, be_wip, price):
    model = lp.LpProblem("release_target", lp.LpMaximize)
    q, profit, unmet = downstream(model, "node", outcomes, be_wip)
    model += profit - price*q
    model.solve(tsmb_common.solver())
    return lp.value(q), lp.value(unmet)

def plan(nodes, fe_wip, be_wip, fixed=None):
    model = lp.LpProblem("one_cohort", lp.LpMaximize)
    starts = {}
    front_cost = lp.LpAffineExpression()
    for f,cap in INST["L_F"].items():
        bounds = (0,cap) if fixed is None else (fixed[f], fixed[f])
        x = starts[f] = lp.LpVariable(f"x_{f}", *bounds)
        front_cost += INST["c_F"] * x
        if fe_wip:
            w = lp.LpVariable(f"W_{f}", 0)
            static._cf_tangents(model, x, w, cap, 1, f"front_{f}")
            front_cost += sweeps.C_W_BASE*w
    profits, losses = [], []
    for i,(y,outcomes) in enumerate(nodes):
        q,profit,unmet = downstream(model, str(i), outcomes, be_wip)
        purchased = lp.LpVariable(f"g_{i}", 0, LG)
        model += q <= N*y*lp.lpSum(starts.values()) + purchased
        profits.append(profit - INST["c_G"]*purchased)
        losses.append(unmet)
    model += lp.lpSum(profits)/len(nodes) - front_cost
    model.solve(tsmb_common.solver())
    return (lp.value(model.objective), {f:x.value() for f,x in starts.items()},
            lp.value(lp.lpSum(losses)/len(nodes)))

def first_cross(point, field, grid):
    def active(h):
        return point(h)[field] > (1e-6 if field.endswith("_short") else SERVICE_EPS)
    if active(0):
        return 0.0
    for a,b in zip(grid,grid[1:]):
        if active(b):
            while b-a > BISECT_TOL:
                mid = (a+b)/2
                if active(mid):
                    b = mid
                else:
                    a = mid
            return (a+b)/2
    return None

def agrees(a,b):
    if a is None or b is None:
        return a is None and b is None
    return abs(a-b) <= HIT_TOL

def check_reference(lag, fw, bw, row):
    fe = rc.two_point(MU,0.075)
    if not lag:
        congestion = {"mode":"cf","c_W":sweeps.C_W_BASE,"fe":bool(fw),"be":bool(bw),
                      "c_W_be":INST["c_K"]} if fw or bw else None
        sc = static.scenarios(*fe,*DEMAND,*BE)
        ref = static.evaluate(INST, sc, cong=congestion)
    elif not (fw or bw):
        ref = multi.evaluate(INST,1,1,fe,BE,DEMAND)
    else:
        return None
    error = max(abs(ref["rp_obj"]-row["rp"]), abs(ref["eev_obj"]-row["eev"]))
    if error > 0.002:
        raise AssertionError(f"f1 vs original model at base half-range: {error}")
    return error

def experiment(lag, fw, bw, grid):
    name = f"L{lag}_FE{fw}_BE{bw}"
    groups = [out for _,out in release_nodes([MU],False,lag)]
    unlimited_loss = 0
    records = []
    for i,out in enumerate(groups):
        q0,m0 = dispatch_need(out,bw,0)
        qg,mg = dispatch_need(out,bw,INST["c_G"])
        unlimited_loss += m0/len(groups)
        # If paying for dies changes sales, nominal outsourcing may not protect the
        # last unit of service. Test the zero-price target as a conservative breakpoint.
        need = max(0, qg-LG, q0 if mg-m0 > SERVICE_EPS else 0)
        records.append(dict(config=name,node=i,outcomes=out,q_free=q0,q_at_cG=qg,
                            unmet_free=m0,unmet_at_cG=mg,native_target=need))
    native = max(r["native_target"] for r in records)
    original_need = rc.max_die_requirement(INST) - LG

    @lru_cache(None)
    def point(h):
        fe = rc.two_point(MU,h)
        nodes = release_nodes(fe,False,lag)
        _,x,_ = plan(release_nodes(fe,True,lag),fw,bw)
        rp,_,mr = plan(nodes,fw,bw)
        eev,_,me = plan(nodes,fw,bw,x)
        low_supply = N*fe[0]*sum(x.values())
        return dict(config=name,h=h,rp=rp,eev=eev,vss=rp-eev,ev_wafers=sum(x.values()),
                    rp_unmet=mr,eev_unmet=me,service_gap=me-mr,reference_loss=me-unlimited_loss,
                    own_loss=me-(point(0)["eev_unmet"] if h else me),
                    generalized_short=native-low_supply,original_short=original_need-low_supply)

    rows = [point(h) for h in grid]
    ref_error = check_reference(lag,fw,bw,point(.075))
    pred = first_cross(point,"generalized_short",grid)
    old = first_cross(point,"original_short",grid)
    observed = first_cross(point,"reference_loss",grid)
    own = first_cross(point,"own_loss",grid)
    gap = first_cross(point,"service_gap",grid)
    def error(a,b):
        return None if a is None or b is None else abs(a-b)
    summary = dict(config=name,lag=lag,fe_wip=fw,be_wip=bw,
                   rho=native/(N*MU*point(0)["ev_wafers"]),native_target=native,
                   original_pred=old,generalized_pred=pred,observed=observed,own_onset=own,
                   gap_onset=gap,original_error=error(old,observed),error=error(pred,observed),
                   hit=agrees(pred,observed),old_hit=agrees(old,observed),
                   reference_unmet=unlimited_loss,base_vss=point(.075)["vss"],
                   base_vss_pct=100*point(.075)["vss"]/abs(point(.075)["rp"]),
                   crosscheck_error=ref_error)
    return summary,rows,records

def main():
    smoke = arguments().smoke
    grid = [0,.075,.20,.50] if smoke else GRID
    configs = [(0,0,0),(1,1,1)] if smoke else list(product((0,1), repeat=3))
    with recorded("f1",smoke) as folder:
        summaries,points,targets = [],[],[]
        for case in configs:
            summary,rows,nodes = experiment(*case,grid)
            summaries.append(summary)
            points.extend(rows)
            targets.extend(nodes)
            print(summary["config"],summary["generalized_pred"],summary["observed"],flush=True)
        dump(folder/"summary.json",summaries)
        dump(folder/"node_targets.json",targets)
        csv_rows(folder/"sweep.csv",points)

if __name__ == "__main__":
    main()

