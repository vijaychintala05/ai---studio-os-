#!/usr/bin/env bash
# Show containers, the newest backups and the safety status.   ops/status.sh [--test]
source "$(dirname "$0")/_common.sh"
say "Containers ($TARGET)"
dc ps
say "Newest backups"
safekeeping list | sed -n '1,40p'
say "Safety status"
if [[ "$(safekeeping status --help)" == *--show-warning* ]]; then
  safekeeping status --show-warning
else
  safekeeping status
fi
