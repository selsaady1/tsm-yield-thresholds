"""
tsmb_common.py  (prompt tsm_b, TSM-26-0314 revision, R1.7b / R1.7c / R1.8)

Shared helpers: paths, solver call (CBC through PuLP, 1 thread), run folder
bookkeeping (run.json with the fields of rule S4), progress logging, and
the crossing / bisection rules of the repository (revision_common.py).

No result is hard-coded here. Every number written by the tsm_b scripts is a
solver output or arithmetic on solver outputs.
"""
import datetime
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SANDBOX = os.path.abspath(os.path.join(HERE, "..", ".."))
REPO = os.path.join(SANDBOX, "repo")
for p in (os.path.join(REPO, "src"), os.path.join(REPO, "experiments"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import pulp  # noqa: E402
from pulp import PULP_CBC_CMD  # noqa: E402

SEED = 0                      # no random numbers are drawn; stated for S4
random.seed(SEED)
THREADS = 1
SOLVER_OPTS = {"solver": "CBC via PuLP PULP_CBC_CMD", "threads": THREADS,
               "msg": 0, "gapRel": "CBC default (models are LPs apart from two "
               "inert binaries in the single-period model)", "timeLimit": None}
RESULTS_ROOT = os.path.join(SANDBOX, "results", "tsm_b")
PROJECT_RESULTS = os.path.abspath(os.path.join(SANDBOX, "..", "..", "TSM-26-0314",
                                               "results", "tsm_b"))


def solver():
    return PULP_CBC_CMD(msg=0, threads=THREADS)


def az_now():
    tz = datetime.timezone(datetime.timedelta(hours=-7))
    return datetime.datetime.now(tz).replace(microsecond=0).isoformat()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cbc_version():
    try:
        exe = pulp.PULP_CBC_CMD().path
        out = subprocess.run([exe, "-quit"], capture_output=True, text=True, timeout=20).stdout
        for line in out.splitlines():
            if line.strip().startswith("Version"):
                return line.split(":", 1)[1].strip() + f" ({os.path.realpath(exe)})"
    except Exception as exc:  # pragma: no cover
        return f"unknown ({exc!r})"
    return "unknown"


class Run:
    """One run folder results/tsm_b/<run_id>/ with log.txt and run.json."""

    def __init__(self, run_id, purpose, scripts, inputs=()):
        self.run_id = run_id
        self.purpose = purpose
        self.dir = os.path.join(RESULTS_ROOT, run_id)
        os.makedirs(self.dir, exist_ok=True)
        self.scripts = [os.path.abspath(s) for s in scripts]
        self.inputs = [os.path.abspath(s) for s in inputs]
        self.t0 = time.time()
        self.started = az_now()
        self.log_fh = open(os.path.join(self.dir, "log.txt"), "a")
        self.last_progress = 0.0
        self.notes = []
        self.log(f"run {run_id} started {self.started}  pid {os.getpid()}")
        self.log(f"command: {' '.join(sys.argv)}")

    def path(self, name):
        return os.path.join(self.dir, name)

    def log(self, msg, force=True):
        line = f"[{az_now()}] {msg}"
        print(line, flush=True)
        self.log_fh.write(line + "\n")
        self.log_fh.flush()

    def progress(self, msg):
        """Write progress at most every 60 s (rule S9 asks for <= 5 min)."""
        if time.time() - self.last_progress > 60:
            self.last_progress = time.time()
            self.log("progress: " + msg)

    def finish(self, status, outputs, notes=""):
        finished = az_now()
        outs = {}
        for o in outputs:
            p = o if os.path.isabs(o) else self.path(o)
            if os.path.exists(p):
                outs[os.path.relpath(p, SANDBOX)] = sha256(p)
        rec = {
            "prompt_id": "tsm_b",
            "run_id": self.run_id,
            "purpose": self.purpose,
            "command": "nice -n 10 " + " ".join([os.path.relpath(sys.executable, SANDBOX)
                                                   if sys.executable.startswith(SANDBOX)
                                                   else sys.executable] + sys.argv),
            "cwd": os.getcwd(),
            "seed": SEED,
            "started_at": self.started,
            "finished_at": finished,
            "runtime_s": round(time.time() - self.t0, 1),
            "status": status,
            "python": platform.python_version(),
            "pulp": pulp.__version__,
            "cbc": cbc_version(),
            "solver_options": SOLVER_OPTS,
            "input_files": {os.path.relpath(p, SANDBOX): sha256(p) for p in self.inputs},
            "output_files": outs,
            "git_commit": "none (not a git repo)",
            "code_sha256": {os.path.relpath(p, SANDBOX): sha256(p) for p in self.scripts},
            "notes": notes + (" | " + " | ".join(self.notes) if self.notes else ""),
        }
        with open(self.path("run.json"), "w") as fh:
            json.dump(rec, fh, indent=1)
        self.log(f"run {self.run_id} finished {finished} status {status} "
                 f"runtime {rec['runtime_s']} s")
        self.log_fh.close()
        return rec


def write_csv(path, rows, fields=None):
    import csv
    if not rows:
        with open(path, "w") as fh:
            fh.write("")
        return
    fields = fields or list(rows[0].keys())
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def crossing(rows, metric, level, xkey="half"):
    """First upward crossing of `level` by `metric` (linear interpolation).

    Same rule as revision_common.crossing / step5 find_threshold.
    Returns the interpolated x, 'below_grid' if already above at the first
    point, or None if never crossed.
    """
    rows = [r for r in rows if r.get("ok", True)]
    if not rows:
        return None
    if rows[0][metric] >= level:
        return "below_grid"
    for a, b in zip(rows, rows[1:]):
        if a[metric] < level <= b[metric]:
            t = (level - a[metric]) / (b[metric] - a[metric])
            return a[xkey] + t * (b[xkey] - a[xkey])
    return None


def bisect_first(f, a, b, tol=1e-4):
    """Smallest x in (a, b] with f(x) True, f monotone on the bracket; None if f(b) False."""
    if not f(b):
        return None
    if f(a + tol):
        return a + tol
    while b - a > tol:
        m = 0.5 * (a + b)
        if f(m):
            b = m
        else:
            a = m
    return 0.5 * (a + b)
