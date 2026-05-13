#!/usr/bin/env bash
# Placeholder hydroland one-month step. Will be replaced by the real model.
#
# Args: <experiment> <member> <yyyymm> <prev_state> <out_state> [forcing_files...]
set -euo pipefail

experiment="$1"
member="$2"
yyyymm="$3"
prev="$4"
out="$5"
shift 5
forcing=("$@")

mkdir -p "$(dirname "$out")"
{
    echo "hydroland: monthly step"
    echo "experiment: ${experiment}"
    echo "member:     ${member}"
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
