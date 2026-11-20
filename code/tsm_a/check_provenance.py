"""
check_provenance.py  (TSM-A)
Extract every number printed in sec_extA.tex and supplement_extA.tex and match it
to (i) a value in results/tsm_a/figs_tables/numbers.csv (solver output, with
file and row), (ii) an existing paper value (base instance, Table I, earlier
results), or (iii) a design parameter of the TSM-A runs. Writes
results/tsm_a/figs_tables/provenance.csv and prints every UNMATCHED token.

    cd tsm-yield-thresholds && .venv/bin/python code/tsm_a/check_provenance.py
"""
import csv
import os
import re
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PAPER = os.path.join(os.path.dirname(REPO), "TSM-26-0314", "revision", "paper")
NUM = os.path.join(REPO, "results", "tsm_a", "figs_tables", "numbers.csv")

# design parameters of the TSM-A runs (set in the scripts, not results)
DESIGN = {
    "0": "grid/levels", "1": "levels", "2": "criterion 2%", "3": "Gamma", "4": "-", "5": "n", "8": "8 scenarios",
    "9": "Eq. ref", "10": "n / delta 10%", "12": "Eq. (12) / 12 infeasible pts (t2 log)", "15": "15 demand settings",
    "16": "16 scenarios", "18": "FE capacity 18 wafers (Table I)", "19": "t dof", "20": "B=M=20; delta 20%",
    "30": "delta 30%", "50": "50 half-ranges / n", "75": "demand half-range", "100": "n / dies per wafer",
    "120": "unmet floor (t2 log)", "150": "demand half-range", "200": "R replications", "225": "demand half-range",
    "300": "demand half-range / D draws", "675": "demand mean", "750": "demand mean", "825": "demand mean",
    "1800": "D range", "2000": "2,000 replications", "200000": "MC draws", "20261113": "seed",
    "0.01": "grid start", "0.1": "delta", "0.2": "delta", "0.3": "delta", "0.5": "lambda / grid end",
    "0.50": "grid end", "0.9": "alpha", "0.95": "MMW one-sided level", "0.125": "epsilon / scenario prob",
    "0.25": "epsilon", "0.875": "FE mean (Table I)", "0.80": "BE mean (Table I)", "0.15": "truth sd",
    "0.075": "truth sd", "0.07": "paper Beta check sd", "1.50": "c_F base (Table I)", "15": "c_F sensitivity",
    "1.5": "c_F", "3.3.0": "PuLP version", "2.10.13": "CBC version", "13": "-",
    "6": "-", "7": "-", "11": "-", "14": "-", "5.2": "-", "1.0": "-",
    "300": "outsourced FE capacity (Table I) / D draws",
}
PAPER_VALUES = {
    "6,380.66": "paper Sec. VI-A / t0_baseline/baseline.csv rp_obj",
    "6,288.50": "paper Sec. VI-A / t0_baseline/baseline.csv eev_obj",
    "92.16": "paper Sec. VI-A / t0_baseline/baseline.csv vss",
    "92.0": "experiments/beta_results.csv row 0.14,0.07",
    "92.000": "t5_limited_data/validation.csv beta7 row",
    "1,050": "t0_baseline/baseline.csv N_max; t4 summary N_max",
}


def variants(v):
    out = set()
    try:
        d = Decimal(v)
    except InvalidOperation:
        return {v}
    for nd in range(0, 7):
        q = d.quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP)
        out.add(str(q))
        out.add(str(abs(q)))
        p = (d * 100).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP)
        out.add(str(p))
    return out


def main():
    idx = {}
    for r in csv.DictReader(open(NUM)):
        for v in re.split(r"\||;| to ", r["value"]):
            v = v.strip()
            for t in variants(v):
                idx.setdefault(t, []).append(f"{r['key']} [{r['file']}; {r['row_selector']}]")
    import json
    for run in ("t0_baseline", "t2_paradigms", "t3_capacity", "t4_demand_map", "t5_limited_data"):
        m = json.load(open(os.path.join(REPO, "results", "tsm_a", run, "run.json")))
        for k in ("runtime_seconds", "n_points", "n_non_optimal"):
            if k in m:
                for t in variants(str(m[k])):
                    idx.setdefault(t, []).append(f"{run}.{k} [results/tsm_a/{run}/run.json]")
    rows, unmatched = [], []
    for fname in ("sec_extA.tex", "supplement_extA.tex"):
        for ln, line in enumerate(open(os.path.join(PAPER, fname)), 1):
            if line.lstrip().startswith("%"):
                continue
            text = line.replace("{,}", ",")
            text = re.sub(r"\\\{[0-9.,]+\\\}|\[0,18\]|\\in\\\{0,1\\\}", " ", text)
            text = re.sub(r"\\(label|ref|eqref|cite|includegraphics|input)\{[^}]*\}", "", text)
            text = re.sub(r"\\(texttt)\{[^}]*\}", "", text)
            text = re.sub(r"\\setlength\{[^}]*\}\{[^}]*\}", "", text)
            text = re.sub(r"\{@\{\}[^}]*\}|p\{[0-9.]+cm\}|\\vspace\{[^}]*\}|cmidrule\([^)]*\)\{[^}]*\}", "", text)
            text = re.sub(r"S-[IVX]+|Eqs?\.~\([0-9]+\)|\([0-9]+\)\s*to~\([0-9]+\)", "", text)
            for tok in re.findall(r"(?<![A-Za-z\\])\d[\d,]*(?:\.\d+)?", text):
                t = tok.rstrip(",")
                tn = t.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", t) else t
                if t in PAPER_VALUES:
                    src = "PAPER/BASE: " + PAPER_VALUES[t]
                elif tn in idx:
                    src = "RESULT: " + " || ".join(idx[tn][:3])
                elif tn in DESIGN:
                    src = "DESIGN: " + DESIGN[tn]
                else:
                    src = "UNMATCHED"
                    unmatched.append((fname, ln, t))
                rows.append({"file": fname, "line": ln, "number": t, "source": src})
    out = os.path.join(REPO, "results", "tsm_a", "figs_tables", "provenance.csv")
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "line", "number", "source"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} numeric tokens; {len(unmatched)} unmatched -> {out}")
    for u in unmatched:
        print("  UNMATCHED", u)


if __name__ == "__main__":
    main()
