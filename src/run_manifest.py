"""
run_manifest.py
===============
Utility to record run metadata (Python, PuLP, solver, machine, timestamps)
for reproducibility. Each step writes its entry to run_manifest.json.
"""

import json
import os
import platform
import sys
from datetime import datetime

MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "run_manifest.json",
)


def _get_env_info():
    """Collect Python, PuLP, solver, and machine info."""
    info = {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "pulp": "N/A",
        "solver": "CBC",
        "machine": {
            "system": platform.system(),
            "machine": platform.machine(),
            "processor": platform.processor() or "N/A",
            "python_impl": platform.python_implementation(),
        },
    }
    try:
        import pulp as p
        info["pulp"] = getattr(p, "__version__", "unknown")
    except ImportError:
        pass
    return info


def record_step(step_name, start_iso, end_iso):
    """
    Record a step's run in run_manifest.json.
    Merges with existing manifest so multiple steps can be recorded.
    """
    env = _get_env_info()
    entry = {
        "solver": env["solver"],
        "python": env["python"],
        "pulp": env["pulp"],
        "start": start_iso,
        "end": end_iso,
        "machine": env["machine"],
    }
    manifest = {}
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r") as f:
            manifest = json.load(f)
    manifest[step_name] = entry
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    return MANIFEST_PATH
