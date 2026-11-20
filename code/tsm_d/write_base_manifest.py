import hashlib, json, os, sys, datetime
from zoneinfo import ZoneInfo
sb = sys.argv[1]
files = {}
for root, dirs, fs in os.walk(sb):
    rel = os.path.relpath(root, sb)
    if rel.split(os.sep)[0] in ("_base", "OUT", "results", "code"):
        continue
    for f in fs:
        if f.endswith((".tex", ".bib", ".py", ".csv", ".json", ".sh")):
            p = os.path.join(root, f)
            files[os.path.relpath(p, sb)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
json.dump({"source_paper": "PROJECT/TSM-26-0314/ (no TSM-26-0314_backup_Nov13 existed)",
           "source_repo": "PROJECT/tsm-yield-thresholds/ (copied to SANDBOX/repo/, .venv and __pycache__ excluded; the original .venv python is used read-only to run)",
           "copy_time": "2026-11-13T16:00:21-07:00",
           "manifest_written": datetime.datetime.now(ZoneInfo("America/Phoenix")).isoformat(timespec="seconds"),
           "n_files": len(files), "sha256": files}, open(os.path.join(sb, "OUT", "BASE_MANIFEST.json"), "w"), indent=1)
print(len(files))
