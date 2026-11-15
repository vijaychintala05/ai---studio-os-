#!/usr/bin/env bash
# Take a verified backup right now, then test-restore it.
#   ops/backup-now.sh [--test] [label]     e.g. ops/backup-now.sh before-big-import
source "$(dirname "$0")/_common.sh"
LABEL="${ARGS[0]:-manual}"
say "Backing up the $TARGET copy (label: $LABEL)"
safekeeping backup --label "$LABEL"
say "Testing that it restores"
safekeeping drill
