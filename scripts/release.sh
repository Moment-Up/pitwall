#!/usr/bin/env bash
# Release a COMMITTED version to the live service without touching the main checkout's work in progress.
#
#   scripts/release.sh [git-ref]      (default: HEAD)
#
# 1. checks the ref out into a separate release worktree (default ~/Projects/pitwall-release),
# 2. syncs its own .venv, links node_modules from the main checkout (incl. the licensed HeroUI Pro install), copies .env,
# 3. runs the test suite and builds both dashboards there - nothing is released if anything fails,
# 4. waits until nobody is driving, then points the launchd service at the release (data stays in <main>/data).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REL="${PITWALL_RELEASE_DIR:-$HOME/Projects/pitwall-release}"
REF="${1:-HEAD}"
COMMIT="$(git -C "$ROOT" rev-parse --verify "$REF^{commit}")"
SVC="$ROOT/scripts/pitwall-service.sh"
PLIST="$HOME/Library/LaunchAgents/com.pitwall.server.plist"

status() {
  curl -fsS -m 2 http://127.0.0.1:8770/api/health 2>/dev/null \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["connection"]["status"])' 2>/dev/null || echo down
}
wait_idle() {
  local quiet=0 deadline=$(( $(date +%s) + ${RELEASE_WAIT_MIN:-180} * 60 ))
  while (( $(date +%s) < deadline )); do
    if [[ "$(status)" != "live" ]]; then quiet=$((quiet + 1)); (( quiet >= 3 )) && return 0; else quiet=0; fi
    sleep 5
  done
  echo "release: still live - giving up" >&2; exit 3
}

echo "release: ${COMMIT:0:7} -> $REL"
if [[ -e "$REL/.git" ]]; then
  git -C "$REL" checkout -q --detach "$COMMIT"
else
  git -C "$ROOT" worktree add -q --detach "$REL" "$COMMIT"
fi
cp "$ROOT/.env" "$REL/.env" 2>/dev/null || true
for app in web web-react; do
  if [[ -d "$ROOT/$app/node_modules" && ! -e "$REL/$app/node_modules" ]]; then ln -s "$ROOT/$app/node_modules" "$REL/$app/node_modules"; fi
done
(cd "$REL" && uv sync --all-extras --frozen -q)
echo "release: running tests"
(cd "$REL" && uv run --frozen pytest -q -p no:cacheprovider -m "not live and not llm and not voice" -x >/tmp/pitwall-release-tests.log 2>&1) || {
  echo "release: TESTS FAILED - not releasing (see /tmp/pitwall-release-tests.log)" >&2; tail -5 /tmp/pitwall-release-tests.log >&2; exit 1; }
tail -1 /tmp/pitwall-release-tests.log
echo "release: building dashboards"
(cd "$REL/web" && npm run build >/tmp/pitwall-release-web.log 2>&1) || { echo "release: web build failed" >&2; exit 1; }
if [[ -d "$REL/web-react" ]]; then
  (cd "$REL/web-react" && npm run build:root >/tmp/pitwall-release-web-react.log 2>&1) || { echo "release: web-react build failed" >&2; exit 1; }
fi
echo "release: waiting until nobody is driving"
wait_idle
if grep -q "<string>$REL</string>" "$PLIST" 2>/dev/null; then
  "$SVC" restart
else
  PITWALL_APP_DIR="$REL" PITWALL_DATA_DIR="$ROOT/data" "$SVC" install  # first release: repoint the service
fi
echo "release: ${COMMIT:0:7} live at $(date +%H:%M:%S)"
