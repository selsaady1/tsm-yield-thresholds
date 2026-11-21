"""check_scope.py: every changed line of the sandbox .tex files must lie inside a marker pair."""
import difflib, os, sys
SB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
tot = 0
for f in ("main.tex", "supplement.tex", "supplement_detail.tex"):
    a = open(f"{SB}/_base/revision/paper/{f}").read().splitlines(); b = open(f"{SB}/revision/paper/{f}").read().splitlines()
    inside = [False] * len(b); st = False
    for i, l in enumerate(b):
        if l.startswith("% >>> BEGIN "): st = True
        inside[i] = st
        if l.startswith("% <<< END "): st = False
    bad = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal": continue
        if tag == "delete" and not (inside[min(j1, len(b) - 1)] or (j1 > 0 and inside[j1 - 1])): bad += 1
        bad += sum(1 for j in range(j1, j2) if not inside[j])
    print(f, "changed lines outside markers:", bad); tot += bad
sys.exit(1 if tot else 0)
