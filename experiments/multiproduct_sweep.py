import numpy as np, csv, os, sys
from mp_model import scen8, vss
PRICES={"D1":12,"D2":8}; DEM={"D1":300,"D2":300}; MEAN=0.875; OUT="mp_sweep_results.csv"
grid=list(np.round(np.arange(0.02,0.501,0.01),4))
done=set()
if os.path.exists(OUT):
    for r in csv.DictReader(open(OUT)): done.add(float(r["full_spread"]))
else: open(OUT,"w").write("full_spread,half_spread,vss,pct_vss\n")
budget=int(sys.argv[1]) if len(sys.argv)>1 else 12; nq=0
for sp in grid:
    if sp in done or nq>=budget: continue
    fl=max(0.01,round(MEAN-sp/2,4)); fh=min(1.00,round(MEAN+sp/2,4))
    v,pct,_=vss(PRICES,scen8(fl,fh,1.0,1.5,0.70,0.90,PRICES,DEM))
    open(OUT,"a").write(f"{sp},{round(sp/2,4)},{round(v,3)},{round(pct,4)}\n"); nq+=1
print(f"mp progress {len(done)+nq}/{len(grid)}",flush=True)
