#!/usr/bin/env bash
# Manage Pitwall as a macOS launchd user agent (starts at login, restarts if it crashes).
#
#   scripts/pitwall-service.sh install    # write the plist and start the service
#   scripts/pitwall-service.sh restart    # restart (refused while telemetry is live; --force to override)
#   scripts/pitwall-service.sh restart-when-idle [minutes]  # wait until nobody is driving, then restart
#   scripts/pitwall-service.sh status     # launchd state + health check
#   scripts/pitwall-service.sh logs       # follow the server log
#   scripts/pitwall-service.sh uninstall  # stop and remove the service
set -euo pipefail

LABEL="com.pitwall.server"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/pitwall"
DOMAIN="gui/$(id -u)"
# APP_DIR: where the code runs from (scripts/release.sh points it at a release worktree of a committed version, so
# in-progress edits in the main checkout never reach the live service). DATA_DIR: where data/settings/captures live.
APP_DIR="${PITWALL_APP_DIR:-$ROOT}"
DATA_DIR="${PITWALL_DATA_DIR:-$ROOT/data}"
BIN="$APP_DIR/.venv/bin/pitwall"

install() {
  if [[ "${1:-}" != "--force" && "$(telemetry_status)" == "live" ]]; then
    echo "telemetry is LIVE (someone is driving): not replacing the server now. Retry between sessions, or pass --force." >&2
    exit 3
  fi
  [[ -x "$BIN" ]] || { echo "missing $BIN - run 'uv sync --all-extras' in $APP_DIR first" >&2; exit 1; }
  mkdir -p "$LOG_DIR" "$(dirname "$PLIST")"
  # stop a manually started server that holds the service's port (8770) so the service can bind it; never other
  # Pitwall servers (scratch/test servers on other ports keep running)
  for pid in $(lsof -nP -t -iTCP:8770 -sTCP:LISTEN 2>/dev/null); do
    if ps -o command= -p "$pid" 2>/dev/null | grep -q "pitwall serve"; then kill "$pid" 2>/dev/null || true; fi
  done
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$BIN</string><string>serve</string></array>
  <key>WorkingDirectory</key><string>$APP_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
    <key>PITWALL_DATA_DIR</key><string>$DATA_DIR</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$LOG_DIR/server.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/server.log</string>
</dict>
</plist>
EOF
  plutil -lint "$PLIST" >/dev/null
  for _ in $(seq 1 20); do pgrep -f "pitwall serve" >/dev/null || break; sleep 0.5; done
  launchctl bootstrap "$DOMAIN" "$PLIST"
  echo "installed $LABEL ($PLIST); logs: $LOG_DIR/server.log"
  wait_healthy
}

uninstall() {
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "removed $LABEL"
}

telemetry_status() {
  # live | stale | no_data | down. "live" means a game is streaming right now (someone may be on track).
  curl -fsS -m 2 http://127.0.0.1:8770/api/health 2>/dev/null \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["connection"]["status"])' 2>/dev/null || echo down
}

restart() {
  # Restarting mid-session ends the pitwall session and splits the driver's race in two, so refuse while live.
  if [[ "${1:-}" != "--force" && "$(telemetry_status)" == "live" ]]; then
    echo "telemetry is LIVE (someone is driving): not restarting. Use '$0 restart-when-idle' or '$0 restart --force'." >&2
    return 3
  fi
  launchctl kickstart -k "$DOMAIN/$LABEL"
  wait_healthy
}

restart_when_idle() {
  local minutes="${1:-120}" deadline quiet=0
  deadline=$(( $(date +%s) + minutes * 60 ))
  echo "waiting for telemetry to go idle (up to ${minutes} min)..."
  while (( $(date +%s) < deadline )); do
    if [[ "$(telemetry_status)" != "live" ]]; then
      quiet=$((quiet + 1))
      # 3 consecutive idle checks (~15 s): not just a pause or a loading screen
      if (( quiet >= 3 )); then restart; return; fi
    else
      quiet=0
    fi
    sleep 5
  done
  echo "still live after ${minutes} min: not restarting" >&2
  return 3
}

wait_healthy() {
  for _ in $(seq 1 40); do
    if curl -fsS -m 2 http://127.0.0.1:8770/api/health >/dev/null 2>&1; then
      echo "pitwall is up: http://127.0.0.1:8770/"
      return 0
    fi
    sleep 0.5
  done
  echo "pitwall did not become healthy in 20 s - check: $0 logs" >&2
  return 1
}

status() {
  launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "state =|pid =|last exit code|runs =" || echo "$LABEL is not installed"
  curl -fsS -m 2 http://127.0.0.1:8770/api/health >/dev/null 2>&1 && echo "health: OK" || echo "health: not responding"
}

case "${1:-}" in
  install) shift; install "${1:-}" ;;
  uninstall) uninstall ;;
  restart) shift; restart "${1:-}" ;;
  restart-when-idle) shift; restart_when_idle "${1:-120}" ;;
  status) status ;;
  logs) tail -n 100 -f "$LOG_DIR/server.log" ;;
  *) echo "usage: $0 {install|uninstall|restart [--force]|restart-when-idle [min]|status|logs}" >&2; exit 2 ;;
esac
