#!/usr/bin/env bash
# Refresh the TEST copy with the newest LIVE backup, with personal details masked.
#   ops/make-test-copy.sh
# Only ever touches the test copy. Sign in with the TEST Admin password afterwards.
source "$(dirname "$0")/_common.sh" --test
say "Stopping the test app"
dc stop app backup
# The original app layer is no longer needed; its files are mounted persistently.
dc rm -f app backup migrate
FILES_DIR=$(env_value FILES_PATH)
[[ -n "$FILES_DIR" ]] || fail "Set FILES_PATH for the test-copy attachments"
say "Loading the newest live backup into the test database, masked"
run_test_recovery python -m studioos.safekeeping make-test-copy || fail "Test copy refresh failed. Do not use this copy; inspect the error and restore the previous verified test backup before continuing."
# v0.16.0: backups carry no privileges; give the restricted app role its row access again.
dc run --rm --no-deps migrate || fail "The upgrade step failed on the test copy. See: docker compose -p $PROJECT logs migrate"
dc up -d --no-deps app backup
say "Verifying a fresh backup and history anchor for this masked dataset"
safekeeping backup --label masked-test-refresh
safekeeping drill
wait_healthy "$(env_value STUDIOOS_VERSION)" || fail "Test app did not start"
say "Test copy refreshed. Phone numbers, GSTINs, emails and chat text are masked; staff accounts are disabled."
