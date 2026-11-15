#!/usr/bin/env bash
# Show containers, the newest backups and the safety status.   ops/status.sh [--test]
source "$(dirname "$0")/_common.sh"
say "Containers ($TARGET)"
dc ps
say "Newest backups"
safekeeping list | head -40
say "Safety status"
safekeeping status
