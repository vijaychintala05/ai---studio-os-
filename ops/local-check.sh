#!/usr/bin/env bash
# Validate a committed snapshot in temporary storage with disposable test data.
set -euo pipefail

usage() {
    echo "Usage: ops/local-check.sh [--quick] [--ref COMMIT] [-- TEST ...]"
}

quick=false
ref=HEAD
while (($#)); do
    case "$1" in
        --quick) quick=true; shift ;;
        --ref)
            if (($# < 2)); then usage >&2; exit 2; fi
            ref=$2; shift 2 ;;
        --) shift; break ;;
        -h|--help) usage; exit ;;
        *) usage >&2; exit 2 ;;
    esac
done
if [[ "$quick" == false && $# -gt 0 ]]; then
    usage >&2
    exit 2
fi

cd "$(git rev-parse --show-toplevel)"
repo=$PWD
commit=$(git rev-parse --verify --end-of-options "$ref^{commit}")
for tool in gitleaks node; do
    if ! command -v "$tool" >/dev/null; then
        echo "Install $tool before running the local checks." >&2
        exit 1
    fi
done

# Match CI's filename check before exporting or scanning any files.
tracked=$(git ls-tree -r --name-only "$commit")
if printf '%s\n' "$tracked" | grep -Ev '\.example$' | grep -E '(^|/)\.env($|\.)|\.(pem|key|dump|sqlite3|db)$' >/dev/null; then
    echo "The commit tracks a forbidden environment, key, dump, or database file." >&2
    exit 1
fi

scratch=$(mktemp -d)
container=
# Use the local Linux Docker socket even if the caller normally uses another context.
local_docker() {
    env -u DOCKER_CONTEXT -u DOCKER_HOST docker --host unix:///var/run/docker.sock "$@"
}
cleanup() {
    if [[ -n "$container" ]]; then
        local_docker rm -fv "$container" >/dev/null || true
    fi
    rm -rf -- "$scratch"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Checking commit $commit"
git show "$commit:.gitleaks.toml" > "$scratch/gitleaks.toml"
gitleaks git --redact --config "$scratch/gitleaks.toml" --log-opts="$commit" "$repo"

mkdir "$scratch/source"
git archive "$commit" | tar -xf - -C "$scratch/source"
cd "$scratch/source"

for script in studioos/static/*.js; do
    node --check "$script"
done

# A clean environment keeps tests away from developer or deployment settings.
test_python() {
    env -i PATH="$PATH" LANG=C.UTF-8 PYTHON_DOTENV_DISABLED=1 "$@"
}

if [[ "$quick" == true ]]; then
    if (($#)); then
        test_python python -m pytest -q -- "$@"
    else
        echo "No focused tests selected. Run the full check before merging into dev."
    fi
    exit
fi

echo "Running the full SQLite test suite"
test_python STUDIOOS_TEST_TIMEOUT=180 python -m pytest -q --durations=20

echo "Starting disposable PostgreSQL 16"
container=$(local_docker run --detach --publish 127.0.0.1::5432 \
    --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_USER=studioos \
    --env POSTGRES_DB=studioos_app_tests postgres:16)
port=$(local_docker port "$container" 5432/tcp)
if [[ ! "$port" =~ ^127\.0\.0\.1:([0-9]+)$ ]]; then
    echo "Could not find the disposable PostgreSQL port on localhost." >&2
    exit 1
fi
port=${BASH_REMATCH[1]}
for ((attempt=1; attempt<=60; attempt++)); do
    if local_docker exec "$container" pg_isready -h 127.0.0.1 -U studioos >/dev/null 2>&1; then
        break
    fi
    if ((attempt == 60)); then
        echo "Disposable PostgreSQL did not start within 60 seconds." >&2
        exit 1
    fi
    sleep 1
done
local_docker exec "$container" createdb -U studioos studioos_safekeeping_test

echo "Running the full PostgreSQL 16 test suite"
test_python \
    STUDIOOS_TEST_TIMEOUT=240 \
    STUDIOOS_TEST_DATABASE_URL="postgresql+psycopg://studioos@127.0.0.1:$port/studioos_app_tests" \
    STUDIOOS_TEST_PG_URL="postgresql://studioos@127.0.0.1:$port/studioos_safekeeping_test" \
    python -m pytest -q --durations=20

echo "Running the offline benchmark"
mkdir -p data
test_python python -m tests.run_benchmark_v2 --provider demo
