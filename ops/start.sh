#!/usr/bin/env bash
# Start (or restart) StudioOS.   ops/start.sh          live copy
#                                 ops/start.sh --test   test copy
source "$(dirname "$0")/_common.sh"
VERSION=$(env_value STUDIOOS_VERSION)
say "Starting the $TARGET copy, version $VERSION"
for v in BACKUP_PATH OFFSITE_PATH FILES_PATH; do
  p=$(env_value "$v"); [[ -n "$p" ]] || fail "$v is empty in $ENVFILE"
  mkdir -p "$p" || fail "Cannot create $p"
done
dc build app
dc run --rm migrate || fail "The upgrade step (schema and app database login) failed. See the output above."
dc up -d
wait_healthy "$VERSION" || fail "The app did not become healthy. See: docker compose -p $PROJECT logs app"
say "Running. First backup and restore test start automatically within a few minutes."
echo "Check them with: ops/status.sh${FLAG}"
