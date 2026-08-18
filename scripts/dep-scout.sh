#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

REPORT_DIR="$HOME/logs/yapit-reports"
mkdir -p "$REPORT_DIR"

UNIT=yapit-dep-scout

# What this run did, for anyone reading later: run-log keeps one line per run in
# ~/logs/runs/$UNIT.jsonl. Nothing here notifies — a dependency report is read
# when there is time for it, from the yapit dashboard — so that line and the
# overdue watchdog behind it are the only things saying this still runs.
log_run() {  # outcome [reason] [stats-json]
    local stats="${3:-}"
    [[ -n "$stats" ]] || stats='{}'
    if ! command -v run-log >/dev/null 2>&1; then
        echo "run-log is not on PATH — this run goes unrecorded, and the watchdog will call $UNIT overdue" >&2
        return 0
    fi
    run-log "$UNIT" "$1" --reason "${2:-}" --stats "$stats" \
        || echo "run-log failed — this run goes unrecorded" >&2
    return 0
}

fail_reason=""
finish() {
    local rc=$?
    [[ "$rc" -eq 0 ]] && return 0
    log_run fail "${fail_reason:-dep-scout.sh exited $rc before finishing — journalctl --user -u $UNIT}"
}
trap finish EXIT

if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

echo "Gathering current dependency versions..."

# --- Python (main project) ---
PYTHON_DEPS=$(uv run python -c "
import tomllib, json
with open('pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
deps = data['project']['dependencies']
print(json.dumps(deps, indent=2))
")

# --- Frontend (npm) ---
FRONTEND_DEPS=$(uv run python -c "
import json
with open('frontend/package.json') as f:
    data = json.load(f)
print(json.dumps({
    'dependencies': data.get('dependencies', {}),
    'devDependencies': data.get('devDependencies', {}),
    'overrides': data.get('overrides', {}),
}, indent=2))
")

# --- Defuddle service (npm) ---
DEFUDDLE_DEPS=$(uv run python -c "
import json
with open('docker/defuddle/package.json') as f:
    data = json.load(f)
print(json.dumps({
    'dependencies': data.get('dependencies', {}),
}, indent=2))
")

# --- npm audit ---
echo "Running npm audit..."
FRONTEND_AUDIT=$(cd frontend && npm audit --json 2>/dev/null || true)
DEFUDDLE_AUDIT=$(cd docker/defuddle && npm audit --json 2>/dev/null || true)

# --- Docker base images ---
DOCKER_IMAGES=$(grep -rh '^FROM ' docker/ yapit/ frontend/Dockerfile 2>/dev/null | sort -u)

# --- Stack Auth: pinned SHA and recent upstream commits ---
STACKAUTH_SHA=$(grep '^FROM stackauth/server:' docker/Dockerfile.stackauth | cut -d: -f2)
echo "Stack Auth pinned at: $STACKAUTH_SHA"
echo "Fetching Stack Auth commit log..."
STACKAUTH_COMMITS=$(gh api -X GET "repos/stack-auth/stack-auth/commits?per_page=30" \
    --jq '.[] | "- \(.sha[0:7]) \(.commit.message | split("\n")[0])"' 2>/dev/null || echo "(failed to fetch)")

# --- Latest PyPI versions ---
echo "Checking latest PyPI versions..."
PYPI_VERSIONS=$(uv run python -c "
import urllib.request, json, re

specs = json.loads('''$PYTHON_DEPS''')
seen = set()
results = {}
for spec in specs:
    name = re.split(r'[~>=<!\[]', spec)[0].strip().lower()
    if name in seen:
        continue
    seen.add(name)
    try:
        url = f'https://pypi.org/pypi/{name}/json'
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            results[name] = data['info']['version']
    except Exception:
        pass
print(json.dumps(results, indent=2))
" 2>/dev/null)

# --- Latest npm versions ---
echo "Checking latest npm versions..."
FRONTEND_LATEST=$(uv run python -c "
import subprocess, json

results = {}
for pkg_file in ['frontend/package.json', 'docker/defuddle/package.json']:
    with open(pkg_file) as f:
        data = json.load(f)
    for section in ['dependencies', 'devDependencies']:
        for pkg in data.get(section, {}):
            if pkg in results:
                continue
            try:
                out = subprocess.run(
                    ['npm', 'view', pkg, 'version'],
                    capture_output=True, text=True, timeout=10
                )
                ver = out.stdout.strip()
                if ver:
                    results[pkg] = ver
            except Exception:
                pass
print(json.dumps(results, indent=2))
" 2>/dev/null)

# --- Build the data payload ---
DATA="## Current Dependency Inventory

### Python — main project (pyproject.toml)
$PYTHON_DEPS

### Frontend (frontend/package.json)
$FRONTEND_DEPS

### Defuddle service (docker/defuddle/package.json)
$DEFUDDLE_DEPS

### npm audit — frontend
$FRONTEND_AUDIT

### npm audit — defuddle
$DEFUDDLE_AUDIT

### Docker base images
$DOCKER_IMAGES

### Stack Auth
Pinned SHA: $STACKAUTH_SHA
Recent upstream commits (newest first):
$STACKAUTH_COMMITS

### Latest available versions (PyPI)
$PYPI_VERSIONS

### Latest available versions (npm)
$FRONTEND_LATEST"

echo "Running Claude analysis..."
output=$(clankr run "$PROJECT_DIR" -p "$SCRIPT_DIR/dep-scout-profile" \
    -- -p "$DATA" \
    --allowedTools "WebSearch,WebFetch" \
    --output-format json \
    2>"$REPORT_DIR/dep-scout-stderr.log") || {
    echo "Claude analysis failed. stderr:"
    cat "$REPORT_DIR/dep-scout-stderr.log"
    echo "stdout: $output"
    fail_reason="the analysis agent failed — $(tail -c 200 "$REPORT_DIR/dep-scout-stderr.log" | tr '\n' ' ')"
    exit 1
}

result_event=$(echo "$output" | jq -c '.[] | select(.type == "result")' 2>/dev/null || echo "$output" | jq -c 'select(.type == "result")' 2>/dev/null || echo '{}')
session_id=$(echo "$result_event" | jq -r '.session_id // "unknown"')
result=$(echo "$result_event" | jq -r '.result // "No result"')

message="Dep Scout — Session: $session_id
---

$result"

# Save report
REPORT_FILE="$REPORT_DIR/dep-scout-$(date +%Y-%m-%d).md"
echo "$message" > "$REPORT_FILE"
echo "Report saved to: $REPORT_FILE"
echo ""
echo "$message"

log_run ok "" "$(jq -n --arg report "$REPORT_FILE" --arg session "$session_id" \
    '{report: $report, session: $session}')"
