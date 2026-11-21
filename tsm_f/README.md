# TSM-F experiments (f1 and f2)

These are the runs behind Subsections D and E of the supplement section on Extensions II of the revised TSM-26-0314 manuscript Its outputs feed the supplement tables written to `tables/tab_tsm_f_*.tex`.

- **f1** (`f1.py`, `f1_incremental.py`): what counts as a cliff. Tests whether condition (12), with a coverage cutoff computed from the BE supply that can actually be used, locates the service loss when there is a BE lead time and FE/BE clearing functions (one FE release cohort, one demand epoch, 8 configurations).
- **f2** (`f2.py`, `f2_ties.py`): paired two-product models, wafer-capacity aggregate against tool-hour constrained, on 18 designed and 30 random instances; `f2_ties.py` checks that the EEV differences in the neutral-route controls come from alternative optimal product mixes.
- `baseline.py` is the gate: it must reproduce RP 6,380.66, EEV 6,288.50 and VSS 92.16 before any other run starts. `make_numbers.py` writes `numbers.json`, `numbers.tex` and the table fragments in `tables/`.

## What is in this folder

- `results/<run>/run.json`: command, seed, Python/PuLP/CBC versions, CBC binary hash, SHA-256 of every input and output, runtime, solve count and non-optimal count. Folders ending in `_smoke` are reduced test runs. `results/*-progress.log` are the progress logs of the full runs.
- `results/<run>/summary.json`, `sweep.csv`, `design.json`, `checks.json`: the outputs the tables are built from.
- `imports/`: byte-for-byte copies of the model files the runs imported. `imports/repo/` matches `src/step2_freeze_model.py`, `experiments/revision_common.py` and `code/tsm_a/tsa_common.py` in this repository. `imports/code/tsm_b/` and `imports/code/tsm_d/` match `code/tsm_b/` and `code/tsm_d/`, except `tsmb_common.py` and `tsmd_common.py`, which are the versions from before the repository-root fallback was added to those two files. The model code in them is the same.

The scripts are kept byte-identical to the versions that produced the results (their hashes are in each `run.json`), so they still expect the original project layout described below.

## Rerunning from this repository

Requirements: Python 3 with PuLP 3.3.0 and CBC 2.10.13 (the scripts refuse other versions), numpy and scipy. The original runs used Python 3.14.5, numpy 2.5.4 and scipy 1.18.1 on an Apple-silicon Mac, with CBC from Homebrew.

`common.py` checks each file in `imports/` against its original and `run.sh` uses the interpreter in `../.venv`. From a clone named `tsm-yield-thresholds`:

```sh
cd tsm-yield-thresholds
python3 -m venv .venv && .venv/bin/pip install pulp==3.3.0 numpy scipy matplotlib
mkdir -p tsm_b/OUT/code tsm_d/code/tsm_d
cp tsm_f/imports/code/tsm_b/*.py tsm_b/OUT/code/
cp tsm_f/imports/code/tsm_d/*.py tsm_d/code/tsm_d/
cd tsm_f
```

PuLP must find CBC 2.10.13 (for example `brew install cbc`, or set PuLP to that binary). Then run the commands below. The original full runs took about 41 s (f1), 11 s (f1_incremental) and 4 min (f2) on one core.

## Original run notes

Use the existing environment from the project root. From this directory, the commands below run serially. The wrapper selects the project's virtual environment, applies nice +10 and keeps solver temporary files and plotting caches here. The nine files in `imports/` are byte-for-byte copies. Each run checks them against their supplied originals. The baseline gate requires all three frozen-model objectives to match at cent precision and every solve to be optimal.

```sh
./run.sh baseline.py
./run.sh f1.py --smoke
./run.sh f2.py --smoke
./run.sh f1_incremental.py --smoke
./run.sh f1.py
./run.sh f1_incremental.py
./run.sh f2.py
./run.sh f2_ties.py --smoke
./run.sh f2_ties.py
./run.sh make_numbers.py
./run.sh make_numbers.py --check
./run.sh make_numbers.py --print TSMF_BASE_VSS
```

The full-run outputs live under `results/f1`, `results/f1_incremental` and `results/f2`. The separate smoke folders contain reduced designs. Each run records its command, seed, PuLP and CBC versions, solver binary and file hashes, elapsed time and individual CBC solve counts. The two f1 variants use deterministic data. The f2 seed is 20261120, with seed +1 for its three mix coordinates. The entry points use one solver at a time.

## Results

The frozen baseline reproduced RP 6,380.66, EEV 6,288.50 and VSS 92.16. All 17,538 completed solves were optimal, including smoke runs and diagnostic checks.

The original coverage formula located additional service loss in two of eight f1 configurations. The conditional-dispatch extension located it in eight of eight, with maximum absolute error 0.00000472 in FE yield half-range. The observed half-ranges were 0.16072 without a lead or BE congestion, 0.27466 with BE congestion alone, 0.30409 with a one-period lead alone, and 0.37297 with both. Turning FE congestion on at the chosen weight preserved those onsets, but reduced baseline percent VSS from 1.44% to 0.33% in the no-lead, no-BE-congestion case. Six of eight configurations already had a shortfall against abundant-die service at zero spread. This explains why the two definitions of onset diverge.

At the frozen half-range of 0.075, tool-hour constraints reduced optimal RP profit by more than one cent in 5/18 designed and 11/30 random instances. Across the full grid they reduced profit in 12/18 and 27/30, respectively. The largest baseline losses were 60.46 and 568.94 dollars per cohort; the largest swept losses were 512.20 and 847.32 dollars. No 2% threshold class changed in these 48 pairs, but the threshold moved from 0.132 to 0.437 in D18. The random tool-constrained cases comprised 16 already at or above 2% at the first point, nine with an interior upward crossing and five without one.

The six neutral-route controls matched in RP to within 0.000002 dollars. In one of them, D08, EEV differed by more than one cent at 16 grid points and by up to 9.46 dollars. Swapping the returned EV plans between formulations gave identical deterministic objective values and identical scenario values for each fixed plan. The apparent EEV difference comes from alternative optimal product mixes.

## F1: what counts as a cliff

The experiment covers one FE release cohort and one demand epoch. It crosses a zero- or one-period BE lead time with FE and BE congestion independently off/on. The waiting-time cost uses the imported TSM-B clearing-function tangents, unit raw process time, FE WIP cost 4.375 per wafer-period and BE WIP cost 0.05 per die-period. With zero lead, releases can use realized demand and BE yield. A one-period lead forces the same release decision across the four future demand/yield outcomes at the given FE node. Excess and lost sales retain their frozen costs. There is no inherited die-bank stock. The four no-lead cases are checked against the original static builder. The no-congestion lead-time case is checked against the original scenario tree.

For each spread, the full stochastic model solves RP, a deterministic mean-input plan (EV), and EEV using that plan's fixed starts. For validation the observed incremental cliff is the first FE half-range at which EEV expected unmet demand exceeds its own zero-spread value by 0.0001 device. The primary grid is 0 to .50 by .01, plus .075, with first-crossing bisection to .00001. The independent outcomes for the loss of abundant-die service and the first positive EEV minus RP service gap are also saved. First-crossing scans do not certify the absence of sub-grid excursions.

### Coverage and the abundant-die target

For low FE yield \(y_-\), the coverage check is \(n\,y_- W_{\rm EV}(h)<C\), with cutoff \(C\) in *native* dies after accounting for external sourcing. At each release-information node, solve a downstream profit-maximizing dispatch at die prices zero and \(c_G\), yielding release quantities \(Q_0,Q_g\) and unmet demands \(m_0,m_g\). Try the candidate \(C_z=\max(0,Q_g-L_G,Q_0\,\mathbf1[m_g>m_0+10^{-4}])\); use the largest node cutoff. This is a proposed economic breakpoint, not a universal identity. Loss of service is assessed against the abundant native-die solution with the same release information and congestion costs. The unadjusted comparator uses the frozen \(N_{\max}-L_G\) in every case. Both supply tests re-solve the EV plan as the realized mean changes.

### Predicting additional deterioration

The follow-up addresses cases already short relative to abundant supply at zero spread. Let \(m(a)\) be expected lost sales from downstream economic dispatch given \(a\) native dies and access to the capped, priced external source. Compute \(a_0=n\mu W_{\rm EV}(0)\), the zero-spread native supply, and \(m_\infty\) at enough dies to fill every BE route. With equiprobable FE outcomes, if the high branch achieves abundant service at the cliff, the low branch there must satisfy

\[
m(a_*)=2m(a_0)-m_\infty.
\]

The implementation finds the lower budget boundary by bisection of conditional dispatch to 0.0001 die, allowing twice the full-model service tolerance on the low branch. The calibration uses no observed spread-onset values. The method assumes monotone conditional shortage near that boundary and subsequently checks whether the high branch actually saturates. Let \(\rho=a_*/a_0\). When \(n\bar y(h) W_{\rm EV}(h)=a_0\) near the crossing, the coverage inequality reduces to \(y_-/\bar y(h)<\rho\). For \(0<\rho<1\), the predicted half-range is

\[
h_*=\begin{cases}
(1-\rho)\mu,&(1-\rho)\mu\le 1-\mu,\\
\mu-\rho/(2-\rho),&\text{upper yield clipped at 1}.
\end{cases}
\]

The output compares both this closed-form prediction and the test using the actual EV starts against the independent full-model service sweep. The high-branch check, eight configurations and single-cohort horizon bound the claim. The follow-up is a within-model diagnostic on the same configurations. Its critical native supply is calibrated by optimization.

## F2: paired product-mix models

Both models retain separate, nonfungible products, wafer starts by product and fab, a shared external FE die budget, and shared BE capacity. They experience the same eight equiprobable FE-yield, BE-yield and total-demand combinations. Product demand shares are fixed within an instance; both products see the same yields. As in the earlier static model, unused native yield can be discarded. With identical BE yields/costs across sites, their capacities can be combined exactly. Free outsourcing contracts are open. Each comparator optimizes its own RP and EV plan, then values the fixed EV starts under the scenarios. VSS is RP minus EEV. Percent VSS uses the absolute RP denominator.

The aggregate comparator has the two fab wafer limits. The detailed model adds a tool-hour constraint for each fab and each of lithography, etch and implant. It takes the TSM-B capacities and scales them with the fab capacity factor in random cases. At contrast \(\delta\), product A's route is \((1+\delta,\,0.8(1-\delta/2),\,0.5)\) hours per wafer. Product B's route is \((1-\delta/2,\,0.8(1+\delta),\,0.5)\). The zero-contrast recipes recover the TSM-B bottleneck controls. Within each model, CBC's returned optimal EV allocation is used without a secondary tie-break; alternative EV-optimal product allocations can have different EEV.

The 18 designed cases cross demand share \(s_A\in\{.25,.5,.75\}\), route contrast \(\delta\in\{0,.5,1\}\), and price premium \(\pi\in\{0,2\}\) (prices \(10+\pi,10-\pi\)). The 30 random cases use the imported TSM-D Latin hypercube for 11 economic, capacity and yield dimensions. A separate three-dimensional Latin hypercube selects \(s_A\in[.2,.8]\), \(\delta\in[.2,1]\), and \(\pi\in[0,3]\). These are constructed scenarios, not fab observations.

The full paired grid is the paper's .01 to .50 half-ranges by .01 plus .075. Reported baseline losses use .075. “Any loss” means the tools reduce optimal RP profit by more than one cent anywhere on this grid. The 2% VSS threshold uses the first upward crossing and linear interpolation. An “at first point” case can fall below 2% later. A separate feasibility LP determines whether the aggregate-optimal product totals at .075 can be reassigned across the fabs within all tool-hour budgets; a minimum peak utilization above 1.00001 is flagged. This is a check of the selected optimal mix, including cases with ties.

The f2 tie diagnostic selects all neutral-route grid points at which EEV differs by more than one cent. It fixes each returned EV plan in the other formulation and solves it under both mean inputs and the full scenario distribution. The full diagnostic output records the product starts, EV objective differences and fixed-policy EEV differences.

## Numbers and tables

`numbers.json` holds raw numeric precision or an explicit null when a threshold has no interior crossing. `numbers.tex` and the print command use the same displayed precision. The supplement-ready tabular fragments live in `tables/` and use the paper's `\NUM{TSMF_...}` convention. Input the local number definitions before a table when compiling separately. A = wafer-capacity aggregate, T = tool-constrained. The f2 case tables show the first 2% point as \(\le .01\) when already above at the first grid point and “--” when unreached. The f1 table lists the reference and incremental predictions separately. Each column pair is predicted/observed. Monetary values are per modeled cohort.

