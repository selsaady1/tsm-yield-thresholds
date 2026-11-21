"""Paired product-mix experiment with product-specific first-stage starts and shared tools."""
from itertools import product
import math

import pulp as lp
from scipy.stats import qmc

from common import (SEED, TARGET, arguments, csv_rows, dump, random_instances as ri, rc,
                    recorded, tsmb_common, tsmb_sweeps)

TOOLS = tsmb_sweeps.TOOL_GROUPS
GRID = sorted({.075,*rc.HALF_GRID})
OBJ_TOL = .01
PRODUCTS = ("A","B")

def recipes(s):
    return {"A":{"litho":1+s,"etch":.8*(1-s/2),"implant":.5},
            "B":{"litho":1-s/2,"etch":.8*(1+s),"implant":.5}}

def scenarios(inst, mu, bl, bh, h, share):
    fe = rc.two_point(mu,h)
    return [(y,b,(d*share,d*(1-share))) for y,b,d in
            product(fe,(bl,bh),(inst["demand_lo"],inst["demand_hi"]))]

def caps(inst):
    return {f:{k:cap*inst["L_F"][f]/ri.BASE["L_F"][f] for k,cap in limits.items()}
            for f,limits in TOOLS["cap"].items()}

def front_constraints(model,x,inst,load,tool_limits,grouped):
    for f,cap in inst["L_F"].items():
        model += lp.lpSum(x[f,p] for p in PRODUCTS) <= cap
        if grouped:
            for k,limit in tool_limits[f].items():
                model += lp.lpSum(load[p][k]*x[f,p] for p in PRODUCTS) <= limit

def model_solve(inst,states,prices,load,tool_limits,grouped,fixed=None):
    model = lp.LpProblem("product_mix",lp.LpMaximize)
    fabs = inst["FE_set"]
    if fixed is None:
        x = {(f,p):lp.LpVariable(f"x_{f}_{p}",0) for f in fabs for p in PRODUCTS}
        front_constraints(model,x,inst,load,tool_limits,grouped)
    else:
        # Use the same certified feasible starts as the EV solve, including CBC's
        # printed precision. Check those capacities explicitly before evaluating.
        x = fixed
        for f in fabs:
            if sum(x[f,p] for p in PRODUCTS) > inst["L_F"][f]+2e-6:
                raise AssertionError("Fixed EV plan exceeds fab capacity.")
            for k,limit in tool_limits[f].items():
                if grouped and sum(load[p][k]*x[f,p] for p in PRODUCTS) > limit+2e-6:
                    raise AssertionError("Fixed EV plan exceeds tool capacity.")
    starts = {p:lp.lpSum(x[f,p] for f in fabs) for p in PRODUCTS}
    profits,unmet = [],[]
    # Identical BE yields and costs make the two parallel BE capacities additive.
    # Starts stay product-specific. Unused FE yield may be discarded in the parent model.
    for i,(fy,by,demand) in enumerate(states):
        g,k,a = {},{},{}
        for j,p in enumerate(PRODUCTS):
            g[p] = lp.LpVariable(f"g_{i}_{p}",0)
            k[p] = lp.LpVariable(f"k_{i}_{p}",0)
            a[p] = lp.LpVariable(f"a_{i}_{p}",0)
            sold = lp.LpVariable(f"sold_{i}_{p}",0,demand[j])
            model += k[p]+a[p] <= fy*inst["n_f_i"]*starts[p]+g[p]
            model += sold <= by*k[p]+a[p]
            missed = demand[j]-sold
            unmet.append(missed)
            profits.append(prices[j]*sold-inst["v_d"]*missed-inst["c_G"]*g[p]
                           -inst["c_B"]*k[p]-inst["c_A"]*a[p])
        model += lp.lpSum(g.values()) <= sum(inst["L_G"].values())
        model += lp.lpSum(k.values()) <= sum(inst["L_B"].values())
        model += lp.lpSum(a.values()) <= sum(inst["L_A"].values())
    model += lp.lpSum(profits)/len(states)-inst["c_F"]*lp.lpSum(starts.values())
    model.solve(tsmb_common.solver())
    plan = fixed or {key:var.value() for key,var in x.items()}
    return lp.value(model.objective),plan,lp.value(lp.lpSum(unmet))/len(states)

def evaluate(inst,states,prices,load,tool_limits,grouped):
    avg = lambda values: math.fsum(values)/len(states)
    mean = [(avg(s[0] for s in states), avg(s[1] for s in states),
             tuple(avg(s[2][j] for s in states) for j in (0,1)))]
    args = prices,load,tool_limits,grouped
    rp,x,mr = model_solve(inst,states,*args)
    _,ev,_ = model_solve(inst,mean,*args)
    eev,_,me = model_solve(inst,states,*args,fixed=ev)
    if rp-eev < -OBJ_TOL:
        raise AssertionError("RP below the evaluated EV policy")
    return dict(rp=rp,eev=eev,vss=rp-eev,pct=100*(rp-eev)/abs(rp),gap=me-mr,
                rp_A=sum(v for (f,p),v in x.items() if p=="A"),
                rp_B=sum(v for (f,p),v in x.items() if p=="B"))

def minimum_tool_util(inst,totals,load,tool_limits):
    """Best reassignment across fabs of the aggregate RP product totals."""
    m = lp.LpProblem("routing_feasibility",lp.LpMinimize)
    u = lp.LpVariable("max_tool_util",0)
    x = {(f,p):lp.LpVariable(f"x_{f}_{p}",0) for f in inst["FE_set"] for p in PRODUCTS}
    for p,target in zip(PRODUCTS,totals):
        m += lp.lpSum(x[f,p] for f in inst["FE_set"]) == target
    for f,cap in inst["L_F"].items():
        m += lp.lpSum(x[f,p] for p in PRODUCTS) <= cap+2e-6
        for k,limit in tool_limits[f].items():
            m += lp.lpSum(load[p][k]*x[f,p] for p in PRODUCTS) <= limit*u
    m += u
    m.solve(tsmb_common.solver())
    return u.value()

def designs():
    cases = []
    for j,(share,s,premium) in enumerate(product((.25,.5,.75),(0,.5,1),(0,2)),1):
        cases.append(dict(case=f"D{j:02}",kind="designed",share=share,contrast=s,premium=premium,
                          params=ri.base_params()))
    # LHS over the original 11 economic dimensions, independently stratified mix dimensions.
    extra = qmc.LatinHypercube(d=3,seed=SEED+1).random(30)
    for p,(u,v,w) in zip(ri.sample(30,seed=SEED),extra):
        cases.append(dict(case=f"R{p['id']:02}",kind="random",share=.2+.6*u,
                          contrast=.2+.8*v,premium=3*w,params=p))
    return cases

def first_threshold(rows,key):
    if rows[0][key] >= 2:
        return "at_first",None
    for a,b in zip(rows,rows[1:]):
        if a[key] < 2 <= b[key]:
            return "crossed", a["h"]+(2-a[key])*(b["h"]-a["h"])/(b[key]-a[key])
    return "unreached",None

def experiment(case,grid):
    inst,mu,bl,bh = ri.build(case["params"])
    load = recipes(case["contrast"])
    limits = caps(inst)
    prices = (10+case["premium"],10-case["premium"])
    rows = []
    for h in grid:
        states = scenarios(inst,mu,bl,bh,h,case["share"])
        result = {key:evaluate(inst,states,prices,load,limits,flag)
                  for key,flag in (("agg",False),("tools",True))}
        row = dict(case=case["case"],h=h)
        row.update({f"{key}_{k}":v for key,r in result.items() for k,v in r.items()})
        loss = row["agg_rp"]-row["tools_rp"]
        if loss < -OBJ_TOL or (case["contrast"] == 0 and abs(loss)>OBJ_TOL):
            raise AssertionError(f"Nested feasible set / neutral control failed: {loss}")
        rows.append(row)
    base = next(r for r in rows if r["h"]==.075)
    util = minimum_tool_util(inst,(base["agg_rp_A"],base["agg_rp_B"]),load,limits)
    ath,ah = first_threshold(rows,"agg_pct")
    gth,gh = first_threshold(rows,"tools_pct")
    base_loss = base["agg_rp"]-base["tools_rp"]
    out = {k:case[k] for k in ("case","kind","share","contrast","premium")}
    out.update(base_agg_rp=base["agg_rp"],base_tools_rp=base["tools_rp"],base_loss=base_loss,
               base_loss_pct=100*base_loss/abs(base["agg_rp"]),
               base_agg_vss_pct=base["agg_pct"],base_tools_vss_pct=base["tools_pct"],
               max_loss=max(r["agg_rp"]-r["tools_rp"] for r in rows),
               max_eev_absdiff=max(abs(r["agg_eev"]-r["tools_eev"]) for r in rows),
               max_vss_delta_pp=max(abs(r["agg_pct"]-r["tools_pct"]) for r in rows),
               base_min_tool_util=util,base_agg_infeasible=util>1+1e-5,
               agg_class=ath,agg_threshold=ah,tools_class=gth,tools_threshold=gh,
               tools_crossings=sum((a["tools_pct"]<2)!=(b["tools_pct"]<2)
                                   for a,b in zip(rows,rows[1:])))
    return out,rows

def main():
    smoke = arguments().smoke
    all_cases = designs()
    cases = [all_cases[i] for i in (0,5,18)] if smoke else all_cases
    grid = [.01,.075,.25,.50] if smoke else GRID
    with recorded("f2",smoke,seed=SEED) as folder:
        # Exact one-product and neutral-route reduction before the factorial design.
        inst,mu,bl,bh = ri.build(ri.base_params())
        states = scenarios(inst,mu,bl,bh,.075,1)
        control = evaluate(inst,states,(10,10),recipes(0),caps(inst),True)
        for k,dest in (("rp","rp_obj"),("eev","eev_obj"),("vss","vss")):
            if format(control[k],".2f") != TARGET[dest]:
                raise AssertionError("One-product reduction failed")
        dump(folder/"control.json",control)
        dump(folder/"design.json",cases)
        summaries,points = [],[]
        for case in cases:
            summary,rows = experiment(case,grid)
            summaries.append(summary)
            points.extend(rows)
            print(case["case"],round(summary["base_loss"],3),flush=True)
        dump(folder/"summary.json",summaries)
        csv_rows(folder/"sweep.csv",points)

if __name__ == "__main__":
    main()

