from pulp import (LpProblem, LpMaximize, LpVariable, LpBinary, lpSum, LpStatus, value, PULP_CBC_CMD)
from step2_freeze_model import FrozenInstance as FI
FE, BE, G, A = list(FI.FE_SET), list(FI.BE_SET), list(FI.G_SET), list(FI.A_SET)
L_F, L_B, L_G, L_A = FI.L_F, FI.L_B, FI.L_G, FI.L_A
n, c_F, c_G, c_B, c_A, c_K, c_D = FI.N_F_I, FI.C_F, FI.C_G, FI.C_B, FI.C_A, FI.C_K, FI.C_D
v_d = FI.V_D
def scen8(fl, fh, dlo, dhi, bl, bh, prices, dem_nom):
    return [{"fe":fy,"be":by,"dem":{p:dem_nom[p]*df for p in prices},"prob":0.125}
            for fy in (fl,fh) for df in (dlo,dhi) for by in (bl,bh)]
def solve(prices, S, fix=None, tag="RP"):
    prob=LpProblem(tag,LpMaximize); P=list(prices); Sx=list(range(len(S)))
    if fix is None:
        XF={(f,p):LpVariable(f"XF_{f}_{p}",0) for f in FE for p in P}
        OG={g:LpVariable(f"OG_{g}",0,1,LpBinary) for g in G}; OA={a:LpVariable(f"OA_{a}",0,1,LpBinary) for a in A}
    else:
        XF={(f,p):LpVariable(f"XF_{f}_{p}",fix['XF'][(f,p)],fix['XF'][(f,p)]) for f in FE for p in P}
        OG={g:LpVariable(f"OG_{g}",fix['OG'][g],fix['OG'][g],LpBinary) for g in G}
        OA={a:LpVariable(f"OA_{a}",fix['OA'][a],fix['OA'][a],LpBinary) for a in A}
    XFK={(s,f,p):LpVariable(f"XFK_{s}_{f}_{p}",0) for s in Sx for f in FE for p in P}
    XGK={(s,g,p):LpVariable(f"XGK_{s}_{g}_{p}",0) for s in Sx for g in G for p in P}
    Z={(s,p):LpVariable(f"Z_{s}_{p}",0) for s in Sx for p in P}
    XKB={(s,b,p):LpVariable(f"XKB_{s}_{b}_{p}",0) for s in Sx for b in BE for p in P}
    XKA={(s,a,p):LpVariable(f"XKA_{s}_{a}_{p}",0) for s in Sx for a in A for p in P}
    XBD={(s,b,p):LpVariable(f"XBD_{s}_{b}_{p}",0) for s in Sx for b in BE for p in P}
    XAD={(s,a,p):LpVariable(f"XAD_{s}_{a}_{p}",0) for s in Sx for a in A for p in P}
    M={(s,p):LpVariable(f"M_{s}_{p}",0) for s in Sx for p in P}
    Wv={(s,p):LpVariable(f"W_{s}_{p}",0) for s in Sx for p in P}
    s1=lpSum(c_F*XF[(f,p)] for f in FE for p in P); obj=[]
    for s in Sx:
        for p in P:
            rev=prices[p]*(S[s]["dem"][p]-M[(s,p)]); pen=v_d*M[(s,p)]
            cg=lpSum(c_G*XGK[(s,g,p)] for g in G); cb=lpSum(c_B*XKB[(s,b,p)] for b in BE); ca=lpSum(c_A*XKA[(s,a,p)] for a in A)
            obj.append(S[s]["prob"]*(rev-pen-c_K*Z[(s,p)]-c_D*Wv[(s,p)]-cg-cb-ca))
    prob+=lpSum(obj)-s1
    for f in FE: prob+=lpSum(XF[(f,p)] for p in P)<=L_F[f]
    for s in Sx:
        for f in FE:
            for p in P: prob+=XFK[(s,f,p)]<=S[s]["fe"]*n*XF[(f,p)]
        for g in G: prob+=lpSum(XGK[(s,g,p)] for p in P)<=L_G[g]*OG[g]
        for p in P:
            prob+=lpSum(XFK[(s,f,p)] for f in FE)+lpSum(XGK[(s,g,p)] for g in G)-lpSum(XKB[(s,b,p)] for b in BE)-lpSum(XKA[(s,a,p)] for a in A)-Z[(s,p)]==0
        for b in BE: prob+=lpSum(XKB[(s,b,p)] for p in P)<=L_B[b]
        for a in A: prob+=lpSum(XKA[(s,a,p)] for p in P)<=L_A[a]*OA[a]
        for p in P:
            for b in BE: prob+=XBD[(s,b,p)]<=S[s]["be"]*XKB[(s,b,p)]
            for a in A: prob+=XAD[(s,a,p)]==XKA[(s,a,p)]
            prob+=lpSum(XBD[(s,b,p)] for b in BE)+lpSum(XAD[(s,a,p)] for a in A)+M[(s,p)]-Wv[(s,p)]==S[s]["dem"][p]
    prob.solve(PULP_CBC_CMD(msg=0))
    return {"status":LpStatus[prob.status],"obj":value(prob.objective),
            "XF":{(f,p):value(XF[(f,p)]) for f in FE for p in P},"OG":{g:value(OG[g]) for g in G},"OA":{a:value(OA[a]) for a in A}}
def vss(prices,S):
    rp=solve(prices,S,tag="RP")
    mfe=sum(s["prob"]*s["fe"] for s in S); mbe=sum(s["prob"]*s["be"] for s in S); mdem={p:sum(s["prob"]*s["dem"][p] for s in S) for p in prices}
    ev=solve(prices,[{"fe":mfe,"be":mbe,"dem":mdem,"prob":1.0}],tag="EV")
    eev=solve(prices,S,fix={"XF":ev["XF"],"OG":ev["OG"],"OA":ev["OA"]},tag="EEV")
    v=rp["obj"]-eev["obj"]; return v,100*v/abs(rp["obj"]),rp
