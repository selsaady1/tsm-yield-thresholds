"""Local execution, immutable model imports, and solve-level provenance."""
import argparse
import contextlib
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
REPO = ROOT / "imports/repo"
SOURCES = {}
for local in sorted((ROOT / "imports").rglob("*.py")):
    if local.is_relative_to(REPO):
        original = PROJECT / "tsm-yield-thresholds" / local.relative_to(REPO)
    elif local.parent.name == "tsm_b":
        original = ROOT.parent / "tsm_b/OUT/code" / local.name
    else:
        original = ROOT.parent / "tsm_d/code/tsm_d" / local.name
    SOURCES[local] = original

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def dump(path, obj):
    path.write_text(json.dumps(obj, allow_nan=False, indent=2) + "\n")

def csv_rows(path, rows):
    with path.open("w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

for local, original in SOURCES.items():
    if sha(local) != sha(original):
        raise RuntimeError(f"Read-only input mismatch: {original}")
sys.path[:0] = [str(REPO / "src"), str(REPO / "experiments"), str(REPO / "code/tsm_a"),
                str(ROOT / "imports/code/tsm_d"), str(ROOT / "imports/code/tsm_b")]
import pulp
import numpy
import scipy
import step2_freeze_model as frozen
import revision_common as rc
import tsa_common
import tsmb_common
import tsmb_static
import tsmb_multiperiod
import tsmb_sweeps
import tsmd_common
import r4_randinst as random_instances

TARGET = {"rp_obj": "6380.66", "eev_obj": "6288.50", "vss": "92.16"}
SEED = 20261120

def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    return parser.parse_args()

@contextlib.contextmanager
def recorded(name, smoke=False, seed=0):
    folder = ROOT / "results" / (name + ("_smoke" if smoke else ""))
    folder.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    solver_path = Path(pulp.PULP_CBC_CMD().path).resolve()
    version = re.search(r"Version:\s*([^\s]+)", subprocess.check_output([solver_path, "-quit"], text=True))[1]
    if (pulp.__version__, version) != ("3.3.0", "2.10.13"):
        raise RuntimeError("PuLP/CBC version mismatch")
    if Path(sys.prefix) != PROJECT / "tsm-yield-thresholds/.venv" or os.getpriority(os.PRIO_PROCESS,0) < 10:
        raise RuntimeError("Use ./run.sh to select the requested environment and priority.")
    if name != "baseline":
        gate = json.loads((ROOT / "results/baseline/run.json").read_text())
        vals = ROOT / "results/baseline/values.json"
        if gate["status"] != "passed" or gate["output_sha256"].get(vals.name) != sha(vals):
            raise RuntimeError("Baseline reproduction must pass before experiments.")
        if any(f"{json.loads(vals.read_text())[k]:.2f}" != v for k,v in TARGET.items()):
            raise RuntimeError("Frozen baseline mismatch.")
    stats = {"solve_count": 0, "nonoptimal_solve_count": 0}
    original = pulp.LpProblem.solve
    def audited(problem, *args, **kwargs):
        status = original(problem, *args, **kwargs)
        stats["solve_count"] += 1
        if status != pulp.LpStatusOptimal or problem.sol_status != pulp.LpSolutionOptimal:
            stats["nonoptimal_solve_count"] += 1
            raise RuntimeError(f"{problem.name} did not solve to optimality: {status}, {problem.sol_status}")
        return status
    pulp.LpProblem.solve = audited
    status = "failed"
    files = [ROOT / "common.py", ROOT / "run.sh", Path(sys.argv[0]).resolve(), *SOURCES]
    if name != "baseline":
        files += [ROOT / "results/baseline/run.json", vals]
    meta = {"run": name, "smoke": smoke, "seed": seed, "started_utc": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(), "venv": sys.prefix, "pulp": pulp.__version__,
            "cbc": version, "cbc_executable": str(solver_path), "cbc_sha256": sha(solver_path),
            "numpy": numpy.__version__, "scipy": scipy.__version__, "workers": 1,
            "nice": os.getpriority(os.PRIO_PROCESS,0), "command": ["./run.sh", *sys.argv],
            "input_sha256": {str(p.relative_to(ROOT)): sha(p) for p in files},
            "import_sources": {str(p.relative_to(ROOT)): str(q.relative_to(PROJECT)) for p,q in SOURCES.items()}}
    try:
        yield folder
        status = "passed"
    except BaseException as exc:
        meta["error"] = repr(exc)
        raise
    finally:
        pulp.LpProblem.solve = original
        meta.update(stats, status=status, runtime_seconds=round(time.monotonic()-start,3),
                    finished_utc=datetime.now(timezone.utc).isoformat(),
                    output_sha256={p.name:sha(p) for p in sorted(folder.iterdir())
                                   if p.is_file() and p.name != "run.json"})
        dump(folder / "run.json", meta)

