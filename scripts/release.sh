#!/usr/bin/env bash
# Release a COMMITTED version to the live service without touching the main checkout's work in progress.
#
#   scripts/release.sh [git-ref]      (default: HEAD)
#   PITWALL_RELEASE_DIR=$HOME/Projects/pitwall-release-v0.2.0 scripts/release.sh <ref>   (a fresh worktree)
#
# 1. checks the ref out into a separate release worktree (PITWALL_RELEASE_DIR, default ~/Projects/pitwall-release),
# 2. syncs its own .venv, links node_modules from the main checkout (incl. the licensed HeroUI Pro install), copies .env,
# 3. runs the test suite and builds both dashboards there - nothing is released if anything fails,
# 4. waits until nobody is driving, backs the database up (<data>/backups/pitwall-pre-<commit>-<time>.sqlite3; the
#    new version may migrate it on its first start), then points the launchd service at the release (data stays in
#    <main>/data).
#
# Steps 1-3 change the release worktree's code, .venv and dashboards while the old version may still be serving, so
# the release worktree must not be the one the running service runs from: release into a fresh worktree (a new
# PITWALL_RELEASE_DIR; the service is repointed to it in step 4, and the old worktree stays as it was for a quick
# rollback). The script refuses to check out into the running service's worktree (RELEASE_IN_PLACE=1 overrides; only
# safe while the service is stopped).
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
serving_from_rel() {  # the launchd service is set to run from $REL and is running (or answers on its port)
  grep -qF "<string>$REL</string>" "$PLIST" 2>/dev/null || return 1
  # not only the HTTP probe: it reads a slow answer (2 s timeout) or a restart in progress as "not serving"
  launchctl print "gui/$(id -u)/com.pitwall.server" 2>/dev/null | grep -q "state = running" && return 0
  pgrep -f "$REL/.venv/bin/pitwall serve" >/dev/null 2>&1 && return 0
  [[ "$(status)" != "down" ]]
}
backup_db() {  # backup_db <data dir>: an online SQLite backup (safe while the idle service keeps the file open)
  local db="$1/pitwall.sqlite3" dest
  [[ -f "$db" ]] || { echo "release: no database at $db yet - nothing to back up"; return 0; }
  mkdir -p "$1/backups"
  dest="$1/backups/pitwall-pre-${COMMIT:0:7}-$(date +%Y%m%d-%H%M%S).sqlite3"
  sqlite3 "$db" ".backup '$dest'" && [[ -s "$dest" ]] || { echo "release: DATABASE BACKUP FAILED - not switching" >&2; exit 4; }
  echo "release: database backed up to $dest"
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
if serving_from_rel && [[ "${RELEASE_IN_PLACE:-0}" != "1" ]]; then
  VER="$(git -C "$ROOT" show "$COMMIT:pyproject.toml" 2>/dev/null | sed -n 's/^version = "\(.*\)"/\1/p' | head -1)"
  echo "release: the running service runs from $REL - checking ${COMMIT:0:7} out there would change its code" >&2
  echo "release: (and rebuild its dashboard) under it. Release into a fresh worktree instead:" >&2
  echo "  PITWALL_RELEASE_DIR=$HOME/Projects/pitwall-release-v${VER:-${COMMIT:0:7}} $0 $REF" >&2
  exit 2
fi
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
# the tests assert built-in defaults: run them without the caller's PITWALL_* settings (moved ports, voice off...)
(cd "$REL" && env $(env | sed -n 's/^\(PITWALL_[A-Za-z0-9_]*\)=.*/-u \1/p') uv run --frozen pytest -q -p no:cacheprovider -m "not live and not llm and not voice" -x >/tmp/pitwall-release-tests.log 2>&1) || {
  echo "release: TESTS FAILED - not releasing (see /tmp/pitwall-release-tests.log)" >&2; tail -5 /tmp/pitwall-release-tests.log >&2; exit 1; }
tail -1 /tmp/pitwall-release-tests.log
echo "release: building dashboards"
(cd "$REL/web" && npm run build >/tmp/pitwall-release-web.log 2>&1) || { echo "release: web build failed" >&2; exit 1; }
if [[ -d "$REL/web-react" ]]; then
  (cd "$REL/web-react" && npm run build:root >/tmp/pitwall-release-web-react.log 2>&1) || { echo "release: web-react build failed" >&2; exit 1; }
fi
echo "release: waiting until nobody is driving"
wait_idle
if grep -qF "<string>$REL</string>" "$PLIST" 2>/dev/null; then
  # in place (the service was stopped, or RELEASE_IN_PLACE=1): the data folder stays the service's own
  backup_db "$(plutil -extract EnvironmentVariables.PITWALL_DATA_DIR raw "$PLIST" 2>/dev/null || echo "$ROOT/data")"
  "$SVC" restart
else
  backup_db "$ROOT/data"
  PITWALL_APP_DIR="$REL" PITWALL_DATA_DIR="$ROOT/data" "$SVC" install  # a fresh worktree: repoint the service
fi
echo "release: ${COMMIT:0:7} live at $(date +%H:%M:%S)"
