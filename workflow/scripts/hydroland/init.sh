#!/usr/bin/env bash
# Placeholder hydroland initial-state generator. Will be replaced by the real model.
set -euo pipefail

experiment="$1"
member="$2"
out="$3"

mkdir -p "$(dirname "$out")"
{
    echo "hydroland: initial state"
    echo "experiment: ${experiment}"
    echo "member:     ${member}"
    echo "created:    $(date -u +%FT%TZ)"
} > "$out"
