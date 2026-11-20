"""run_r00_validate.py: reproduce the published baseline before any new experiment.

Checks
  1. revision_common.self_check() (repo builder vs step2_freeze_model).
  2. tsmb_static.self_check() (extended builder with extensions off).
  3. tsmb_multiperiod.check_T1() (multi-period model, T=1, lB=0).
  4. Baseline RP, EEV, VSS, %VSS, wafer starts versus the repo's
     results/Step1/step1_summary_table.csv (published values).
  5. Cliff quantities of the base instance (N_bar, N_max, L_G, rho).
Usage: nice -n 10 $PY run_r00_validate.py
"""
import csv
import os

from tsmb_common import Run, REPO, write_csv
import revision_common as rc
import tsmb_static as ts
import tsmb_multiperiod as mp

STEP1 = os.path.join(REPO, "results", "Step1", "step1_summary_table.csv")
run = Run("tsmb_r00_validate", "Baseline reproduction (RP, EEV, VSS) before new runs; "
          "checks for R1.7b/R1.7c/R1.8 builders",
          [__file__, ts.__file__, mp.__file__, rc.__file__,
           os.path.join(os.path.dirname(__file__), "tsmb_common.py")], [STEP1])

dev_rc = rc.self_check()
dev_st = ts.self_check()
dev_mp = mp.check_T1()
run.log(f"self-checks: revision_common {dev_rc:.2e}, tsmb_static {dev_st:.2e}, multiperiod T=1 {dev_mp:.2e}")

inst = rc.base_inst()
r = rc.evaluate(inst, 0.80, 0.95)
pub = {}
with open(STEP1) as fh:
    for row in csv.reader(fh):
        if row and row[0]:
            pub[row[0]] = row[1:]
checks = [
    ("RP_profit", r["rp_obj"], float(pub["Expected Profit ($)"][0])),
    ("EEV_profit", r["eev_obj"], float(pub["Expected Profit ($)"][1])),
    ("VSS", r["vss"], float(pub["VSS ($)"][2])),
    ("pct_VSS", r["pct_vss"], float(pub["%VSS"][2].rstrip("%"))),
    ("RP_total_wafers", r["rp_fe1"] + r["rp_fe2"], float(pub["Total Wafer Starts"][0])),
    ("EV_total_wafers", r["ev_fe1"] + r["ev_fe2"], float(pub["Total Wafer Starts"][1])),
]
rows, ok = [], True
for name, mine, published in checks:
    match = abs(round(mine, 2) - published) < 1e-9
    ok &= match
    rows.append({"quantity": name, "reproduced": f"{mine:.6f}", "published_step1_csv": published,
                 "match_to_2dp": match})
    run.log(f"{name}: reproduced {mine:.4f}  published {published}  match {match}")

nmax = rc.max_die_requirement(inst)
w_ev = r["ev_fe1"] + r["ev_fe2"]
nbar = inst["n_f_i"] * 0.875 * w_ev
lg = sum(inst["L_G"].values())
rho = (nmax - lg) / nbar
for name, val in [("N_max", nmax), ("N_bar", nbar), ("L_G", lg), ("rho", rho),
                  ("RP_FE1_util", r["rp_fe1"] / inst["L_F"]["FE1"]),
                  ("RP_FE2_util", r["rp_fe2"] / inst["L_F"]["FE2"]),
                  ("EV_FE1_util", r["ev_fe1"] / inst["L_F"]["FE1"]),
                  ("EV_FE2_util", r["ev_fe2"] / inst["L_F"]["FE2"]),
                  ("RP_total_util", (r["rp_fe1"] + r["rp_fe2"]) / 18.0),
                  ("EV_total_util", w_ev / 18.0)]:
    rows.append({"quantity": name, "reproduced": f"{val:.6f}", "published_step1_csv": "",
                 "match_to_2dp": ""})
run.log(f"N_max={nmax:.2f} N_bar={nbar:.2f} L_G={lg} rho={rho:.4f}")
write_csv(run.path("baseline_check.csv"), rows)
run.finish("OK" if ok else "FAILED", ["baseline_check.csv", "log.txt"],
           notes=f"self-check deviations {dev_rc:.1e}/{dev_st:.1e}/{dev_mp:.1e}; "
                 f"baseline matches published Step 1 CSV: {ok}")
