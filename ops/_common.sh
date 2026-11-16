# Shared helpers for the StudioOS operating scripts. Not run directly.
# Every script works on the LIVE copy by default and on the TEST copy with --test.

set -euo pipefail
cd "$(dirname "$0")/.."

TARGET=live
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --test) TARGET=test ;;
    --live) TARGET=live ;;
    *) ARGS+=("$arg") ;;
  esac
done

FLAG=""
if [[ "$TARGET" == test ]]; then
  FLAG=" --test"
  PROJECT=studioos-test
  ENVFILE=.env.test
  FILES=(-f compose.yaml -f compose.test.yaml)
else
  PROJECT=studioos-live
  ENVFILE=.env.live
  FILES=(-f compose.yaml)
fi

# Optional explicit configuration file; target names and all safety checks stay unchanged.
ENVFILE="${STUDIOOS_OPS_ENV_FILE:-$ENVFILE}"

[[ -f "$ENVFILE" ]] || { echo "Missing $ENVFILE. Copy env.$TARGET.example to $ENVFILE and fill it in." >&2; exit 2; }
chmod 600 "$ENVFILE" 2>/dev/null || true

# v0.16.0: the restricted app login needs its own password (never printed).
if [[ "$(grep -E '^STUDIOOS_DB_ROLE=' "$ENVFILE" | tail -1 | cut -d= -f2-)" == app ]]; then
  _app_pw=$(grep -E '^STUDIOOS_APP_DB_PASSWORD=' "$ENVFILE" | tail -1 | cut -d= -f2-)
  _own_pw=$(grep -E '^DB_PASSWORD=' "$ENVFILE" | tail -1 | cut -d= -f2-)
  if [[ ${#_app_pw} -lt 16 ]]; then echo "STOPPED: set STUDIOOS_APP_DB_PASSWORD (16+ characters) in $ENVFILE" >&2; exit 2; fi
  if [[ "$_app_pw" == "$_own_pw" ]]; then echo "STOPPED: STUDIOOS_APP_DB_PASSWORD must differ from DB_PASSWORD in $ENVFILE" >&2; exit 2; fi
  if [[ ! "$_app_pw" =~ ^[A-Za-z0-9_-]+$ ]]; then echo "STOPPED: use only letters, digits, - and _ in STUDIOOS_APP_DB_PASSWORD" >&2; exit 2; fi
  unset _app_pw _own_pw
fi

dc() { docker compose -p "$PROJECT" --env-file "$ENVFILE" "${FILES[@]}" "$@"; }

env_value() { grep -E "^$1=" "$ENVFILE" | tail -1 | cut -d= -f2- ; }

say() { printf '\n== %s\n' "$*"; }

fail() { printf '\nSTOPPED: %s\n' "$*" >&2; exit 1; }

wait_healthy() {
  # Wait up to ~3 minutes for the app to answer /health with the expected version.
  local want="$1" i out
  for i in $(seq 1 90); do
    out=$(dc exec -T app python -c "import json,urllib.request;print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=5))['version'])" 2>/dev/null || true)
    if [[ "$out" == "$want" ]]; then return 0; fi
    sleep 2
  done
  return 1
}

# A freshly started daemon can own the recovery lock. Wait only after the
# old-compatible CLI explicitly refused BEFORE doing any work; never retry an
# ambiguous/partial operation or another failure. The database lock stays strict.
safekeeping() {
  local scratch deadline=$((SECONDS+300)) rc waiting=no
  scratch=$(mktemp -d) || return
  while true; do
    if dc exec -T backup python -m studioos.safekeeping "$@" >"$scratch/out" 2>"$scratch/err"; then
      cat "$scratch/out"; cat "$scratch/err" >&2
      rm "$scratch/out" "$scratch/err"; rmdir "$scratch"; return 0
    else rc=$?; fi
    if [[ ! -s "$scratch/out" && "$(cat "$scratch/err")" == 'ERROR: Another backup, restore test or restore is already running' && $SECONDS -lt $deadline ]]; then
      if [[ "$waiting" == no ]]; then
        cat "$scratch/err" >&2
        echo 'Waiting for the running backup or restore to finish (up to 5 minutes).' >&2
        waiting=yes
      fi
      sleep 2
      continue
    fi
    cat "$scratch/out"; cat "$scratch/err" >&2
    rm "$scratch/out" "$scratch/err"; rmdir "$scratch"; return "$rc"
  done
}

# Before a backup or replacement, rescue pre-Inbox-persistence files from the
# running app. The backup service mirrors the full mounted files root, including
# both legacy attachments and Inbox files, even when its image is older.
prepare_attachment_backup() {
  local files_dir source_dir target_name present
  files_dir=$(env_value FILES_PATH)
  [[ -n "$files_dir" ]] || fail "Set FILES_PATH before backing up attached files"
  mkdir -p "$files_dir/intake" "$files_dir/new_type_uploads" || fail "Cannot prepare persistent attachment folders"
  for target_name in new_type_uploads intake; do
    source_dir="/app/data/$target_name"
    present=$(dc exec -T app python -c 'import pathlib,sys; print("present" if pathlib.Path(sys.argv[1]).is_dir() else "absent")' "$source_dir") || fail "Cannot inspect legacy attachments; start the app before taking this upgrade backup"
    if [[ "$present" == present ]]; then
      dc cp "app:$source_dir/." "$files_dir/$target_name/" || fail "Could not preserve legacy $target_name files; nothing was replaced"
    fi
  done
  dc up -d --no-deps backup || fail "Could not prepare the attachment backup service"
}

# One-shot migration runs with the owner login before the restricted app starts.
# Removing only stopped service containers avoids retaining duplicate image layers
# during replacement. Named volumes and mounted files are never removed.
start_version() {
  dc up -d db || return
  dc stop app backup || return
  dc rm -f app backup migrate || return
  dc run --rm --no-deps migrate || return
  dc up -d --no-deps app backup || return
}

# One-shot masked-copy recovery needs write access to the test attachments only.
# The normal backup daemon retains its read-only files mount.
run_test_recovery() {
  [[ "$TARGET" == test ]] || fail "Attachment recovery is only for the test copy"
  local files_dir
  files_dir=$(env_value FILES_PATH)
  [[ -n "$files_dir" ]] || fail "Set FILES_PATH for the test-copy attachments"
  docker compose -p "$PROJECT" --env-file "$ENVFILE" "${FILES[@]}" -f compose.recovery.yaml run --rm --no-deps backup "$@"
}
