#!/bin/sh
set -eu
cd "$(dirname "$0")"
dir=$(pwd -P)
mkdir -p "$dir/.state/tmp" "$dir/.state/matplotlib" "$dir/.state/cache"
export TMPDIR="./.state/tmp" MPLCONFIGDIR="$dir/.state/matplotlib" XDG_CACHE_HOME="$dir/.state/cache"
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
exec nice -n 10 "$dir/../../tsm-yield-thresholds/.venv/bin/python" -B "$@"

