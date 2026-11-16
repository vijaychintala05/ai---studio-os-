#!/usr/bin/env bash
# Upgrade StudioOS to the version in the VERSION file, with automatic rollback.
#
#   ops/upgrade.sh --test     ALWAYS do the test copy first and check it
#   ops/upgrade.sh            then the live copy
#
# Steps: verified backup (labelled) -> restore test -> build -> switch ->
# health check -> if anything fails, switch back to the previous version.
# Database changes are additive only, so switching back keeps all data.
source "$(dirname "$0")/_common.sh"

NEW=$(tr -d '[:space:]' < VERSION)
OLD=$(env_value STUDIOOS_VERSION)
[[ -n "$NEW" && -n "$OLD" ]] || fail "Could not read versions (VERSION file and STUDIOOS_VERSION in $ENVFILE)"

# v0.9.5 (review F12): "tested" means THESE exact files were upgraded on the test copy.
# The test run records a fingerprint of the code; the live upgrade refuses any difference.
source_fingerprint() {
  find studioos ops agents compose.yaml Dockerfile requirements.txt VERSION -type f \
       -not -path '*/__pycache__/*' -not -name '*.pyc' -print0 2>/dev/null | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-32
}
SRC=$(source_fingerprint)
if [[ "$TARGET" == live ]]; then
  [[ -f ".upgrade-tested-$NEW" ]] || fail "Version $NEW has not been upgraded on the test copy yet. Run: ops/upgrade.sh --test   then check the test copy, then run this again."
  [[ "$(cat ".upgrade-tested-$NEW")" == "$SRC" ]] || fail "These files differ from the ones tested on the test copy. Run ops/upgrade.sh --test again first."
fi

say "Upgrading the $TARGET copy from $OLD to $NEW"

[[ -n "$(env_value FILES_PATH)" ]] || fail "v0.9.1 needs FILES_PATH in $ENVFILE: a NAS folder for attached photos and files (see env.live.example). Nothing was changed."
if [[ "$(env_value STUDIOOS_ENV)" == "production" && "$(env_value STUDIOOS_SECURE_COOKIE)" != "true" ]]; then
  fail "v0.9.2 requires STUDIOOS_SECURE_COOKIE=true for live data (serve over HTTPS with tailscale serve; see RUNBOOK.md). Nothing was changed."
fi
say "Preparing persistent attachments before the verified backup"
prepare_attachment_backup
say "1/5 Verified backup before upgrading"
LABEL="pre-upgrade-${NEW//./-}"
safekeeping backup --label "$LABEL" > /tmp/studioos-upgrade-backup.json || fail "Backup failed. Nothing was changed."
BACKUP_FILE=$(grep -o '"file": "[^"]*"' /tmp/studioos-upgrade-backup.json | head -1 | cut -d'"' -f4)
echo "Backup: $BACKUP_FILE"

say "2/5 Proving that backup restores"
safekeeping drill --file "$BACKUP_FILE" > /tmp/studioos-upgrade-drill.json || fail "Restore test failed. Nothing was changed. See /tmp/studioos-upgrade-drill.json"

say "3/5 Building version $NEW"
cp "$ENVFILE" "$ENVFILE.before-$NEW"
STUDIOOS_VERSION="$NEW" dc build app || fail "Build failed. Nothing was changed."
# v0.9.1: versions before 0.9.1 kept attached files inside the app container. Copy any
# that exist to FILES_PATH before the container is replaced, so none are lost.
FILES_DIR=$(env_value FILES_PATH)
[[ -n "$FILES_DIR" ]] || fail "Set FILES_PATH in $ENVFILE (a NAS folder for attached files). Nothing was changed."
mkdir -p "$FILES_DIR/new_type_uploads" || fail "Cannot create $FILES_DIR/new_type_uploads. Nothing was changed."
if dc exec -T app test -d /app/data/new_type_uploads 2>/dev/null; then
  dc cp app:/app/data/new_type_uploads/. "$FILES_DIR/new_type_uploads/" || fail "Could not copy attached files out of the old app. Nothing was changed."
  say "Attached files copied to $FILES_DIR/new_type_uploads"
fi

# v0.9.5 (review F12): from here on, ANY failure switches back. Before, a failed
# "docker compose up" stopped the script (set -e) before the switch-back could run.
switch_back() {
  trap - ERR
  set +e
  say "Version $NEW did not start properly. Switching back to $OLD."
  cp "$ENVFILE.before-$NEW" "$ENVFILE"
  dc up -d app backup
  if wait_healthy "$OLD"; then
    echo "Back on $OLD. Your data was kept (database changes are additive)."
    echo "If you also want the database exactly as it was before the upgrade, run:"
    echo "  ops/rollback.sh${FLAG} --restore-db $BACKUP_FILE"
  else
    echo "The previous version did not start either. Follow 'App will not start' in RUNBOOK.md."
  fi
  exit 1
}

# A real check of the running app: database reachable, schema at the expected
# version, the main tables readable. /health alone only proves the web server answers.
smoke_test() {
  dc exec -T app python - <<'PY'
from sqlalchemy import select, func, text
from studioos.db import SessionLocal, Project, Task, Cost, ApprovalTicket, ChatMessage
from studioos.migrations import LATEST_VERSION
with SessionLocal() as db:
    version = db.execute(text('SELECT MAX(version) FROM schema_migrations')).scalar()
    assert version == LATEST_VERSION, f'schema {version}, expected {LATEST_VERSION}'
    for model in (Project, Task, Cost, ApprovalTicket, ChatMessage):
        db.scalar(select(func.count()).select_from(model))
print('smoke test passed')
PY
}

say "4/5 Switching to $NEW"
trap switch_back ERR
sed -i.bak "s/^STUDIOOS_VERSION=.*/STUDIOOS_VERSION=$NEW/" "$ENVFILE"
dc up -d app backup || switch_back

say "5/5 Health and smoke check"
if wait_healthy "$NEW" && smoke_test; then
  trap - ERR
  [[ "$TARGET" == test ]] && echo "$SRC" > ".upgrade-tested-$NEW"
  say "Upgrade complete: the $TARGET copy runs $NEW. Pre-upgrade backup: $BACKUP_FILE"
  [[ "$TARGET" == test ]] && echo "Now check the test copy in the browser (port $(env_value APP_PORT)). If it looks right: ops/upgrade.sh"
  exit 0
fi
switch_back
