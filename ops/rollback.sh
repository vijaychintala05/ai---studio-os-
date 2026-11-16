#!/usr/bin/env bash
# Go back to an earlier version, and optionally an earlier database.
#
#   ops/rollback.sh --to 0.6.3                     code only; keeps all data
#   ops/rollback.sh --restore-db studioos_XXXX.dump
#                                                  database back to that backup; the current
#                                                  database is RENAMED and kept, never deleted
#   add --test to work on the test copy
source "$(dirname "$0")/_common.sh"

TO=""; DB_FILE=""
set -- "${ARGS[@]+"${ARGS[@]}"}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --to) TO="$2"; shift 2 ;;
    --restore-db) DB_FILE="$2"; shift 2 ;;
    *) fail "Unknown option $1" ;;
  esac
done
[[ -n "$TO" || -n "$DB_FILE" ]] || fail "Say what to roll back: --to VERSION and/or --restore-db FILE"

if [[ -n "$TO" ]]; then
  docker image inspect "studioos-app:$TO" >/dev/null 2>&1 || fail "Image studioos-app:$TO is not on this NAS"
  say "Switching the $TARGET copy to version $TO (code only)"
  cp "$ENVFILE" "$ENVFILE.before-rollback"
  sed -i.bak "s/^STUDIOOS_VERSION=.*/STUDIOOS_VERSION=$TO/" "$ENVFILE"
  start_version
  wait_healthy "$TO" || fail "Version $TO did not start. Previous settings are in $ENVFILE.before-rollback"
fi

if [[ -n "$DB_FILE" ]]; then
  read -r -p "Replace the $TARGET database with $DB_FILE? The current one is kept under a new name. Type YES: " ok
  [[ "$ok" == YES ]] || fail "Cancelled. Nothing changed."
  say "Safety backup of the current database first"
  safekeeping backup --label before-restore
  say "Stopping the app"
  dc stop app
  say "Restoring $DB_FILE (checked against the backup before anything is switched)"
  safekeeping swap-in --file "$DB_FILE" --confirm-live-replace || { dc start app; fail "Restore did not complete. Live database untouched; app restarted."; }
  # v0.16.0: backups carry no privileges; give the restricted app role its row access again.
  dc run --rm --no-deps migrate || fail "The upgrade step failed after the restore. See: docker compose -p $PROJECT logs migrate"
  dc start app
  VERSION=$(env_value STUDIOOS_VERSION)
  wait_healthy "$VERSION" || fail "App did not start after the restore. See RUNBOOK.md"
fi
say "Rollback finished."
