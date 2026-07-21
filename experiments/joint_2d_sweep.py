import numpy as np, csv, os, sys
from step2_freeze_model import FrozenInstance, solve_rp, solve_rp_fixed
DL,DH=FrozenInstance.DEMAND_LO,FrozenInstance.DEMAND_HI
OUT="sweep2d_results.csv"
def crossing(mean,vd,target=2.0):
    xs,ys=[],[]
    for sp in np.round(np.arange(0.02,0.451,0.01),4):
        fl=max(0.01,round(mean-sp/2,4)); fh=min(1.00,round(mean+sp/2,4))
        inst=FrozenInstance(fl,fh,0.70,0.90).to_inst_dict(); inst["v_d"]=vd
        scen=[{"name":f"{a}{b}{c}","prob":0.125,"fe_yield":fy,"demand":dv,"be_yield":by}
              for a,fy in [("l",fl),("h",fh)] for b,dv in [("l",DL),("h",DH)] for c,by in [("l",0.70),("h",0.90)]]
        rp=solve_rp(inst,scen,tag="R"); m=lambda k:sum(s["prob"]*s[k] for s in scen)
        ev=solve_rp(inst,[{"name":"E","prob":1.0,"fe_yield":m("fe_yield"),"demand":m("demand"),"be_yield":m("be_yield")}],tag="E")
        ee=solve_rp_fixed(inst,scen,ev["X_F"],ev["O_G"],ev["O_A"]); v=rp["obj"]-ee["obj"]
        xs.append(sp); ys.append(100*v/abs(rp["obj"]))
    for i in range(1,len(xs)):
        if ys[i-1]<target<=ys[i]: fr=(target-ys[i-1])/(ys[i]-ys[i-1]); return xs[i-1]+fr*(xs[i]-xs[i-1])
    return None
cells=[(m,v) for m in [0.82,0.85,0.875,0.90,0.92] for v in [1,3,5,8]]
done=set()
if os.path.exists(OUT):
    for r in csv.DictReader(open(OUT)): done.add((float(r["fe_mean"]),float(r["penalty"])))
else: open(OUT,"w").write("fe_mean,penalty,full_spread,half_spread,worstcase_fe_yield\n")
budget=int(sys.argv[1]) if len(sys.argv)>1 else 3; nq=0
for m,v in cells:
    if (m,v) in done or nq>=budget: continue
    c=crossing(m,v); half=round(c/2,4) if c else None; wc=round(m-c/2,4) if c else "NA"
    open(OUT,"a").write(f"{m},{v},{round(c,4) if c else 'NA'},{half},{wc}\n")
    print(f"cell mean={m} v={v} half={half} worstcase={wc}",flush=True); nq+=1
print(f"progress {len(done)+nq}/20",flush=True)
