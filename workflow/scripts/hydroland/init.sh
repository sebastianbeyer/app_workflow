#!/usr/bin/env bash
# Placeholder hydroland initial-state generator. Will be replaced by the real model.
set -euo pipefail

experiment="$1"
out="$2"

mkdir -p "$(dirname "$out")"
{
    echo "hydroland: initial state"
    echo "experiment: ${experiment}"
    echo "created:    $(date -u +%FT%TZ)"
} > "$out"
