#!/usr/bin/env bash
# Placeholder hydroland one-month step. Will be replaced by the real model.
#
# Args: <experiment> <yyyymm> <prev_state> <out_state> [forcing_files...]
set -euo pipefail

experiment="$1"
yyyymm="$2"
prev="$3"
out="$4"
shift 4
forcing=("$@")

mkdir -p "$(dirname "$out")"
{
    echo "hydroland: monthly step"
    echo "experiment: ${experiment}"
    echo "month:      ${yyyymm}"
    echo "prev_state: ${prev}"
    echo "forcing:"
    for f in "${forcing[@]}"; do
        echo "  - ${f}"
    done
    echo "ran:        $(date -u +%FT%TZ)"
} > "$out"

# Pretend the model does real work.
sleep 1
