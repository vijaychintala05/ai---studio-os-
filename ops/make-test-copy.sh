#!/usr/bin/env bash
# Refresh the TEST copy with the newest LIVE backup, with personal details masked.
#   ops/make-test-copy.sh
# Only ever touches the test copy. Sign in with the TEST Admin password afterwards.
source "$(dirname "$0")/_common.sh" --test
say "Stopping the test app"
dc stop app
# The original app layer is no longer needed; its files are mounted persistently.
dc rm -f app migrate
FILES_DIR=$(env_value FILES_PATH)
[[ -n "$FILES_DIR" ]] || fail "Set FILES_PATH for the test-copy attachments"
say "Loading the newest live backup into the test database, masked"
dc run --rm --no-deps -v "$FILES_DIR:/app/files:rw" backup python -m studioos.safekeeping make-test-copy || { dc up -d --no-deps app; fail "Test copy not refreshed; the previous test data is unchanged."; }
# v0.16.0: backups carry no privileges; give the restricted app role its row access again.
dc run --rm --no-deps migrate || fail "The upgrade step failed on the test copy. See: docker compose -p $PROJECT logs migrate"
dc up -d --no-deps app
wait_healthy "$(env_value STUDIOOS_VERSION)" || fail "Test app did not start"
say "Test copy refreshed. Phone numbers, GSTINs, emails and chat text are masked; staff accounts are disabled."
