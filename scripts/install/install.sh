#!/bin/sh
# Pitwall one-line installer for macOS and Linux (POSIX sh: dash, bash and macOS sh).
#
#   curl -fsSL https://github.com/Moment-Up/pitwall/releases/latest/download/install.sh | sh
#   curl -fsSL https://github.com/Moment-Up/pitwall/releases/latest/download/install.sh | sh -s -- --yes
#
# It installs the latest release into ~/Pitwall/pitwall-<version>/ (--home to choose another folder): it checks the
# zip's SHA-256 and every path in it, installs Python 3.12 and Pitwall's packages with uv (and offers to install uv),
# then hands over to the new version's `pitwall install-finish`, which keeps your sessions in ~/Pitwall/data, backs
# up the database, carries your .env forward and, if you want, starts Pitwall in the background at login.
# Running it again is safe: a version that is already installed is not downloaded again.
#
# Options (or the environment variables after them):
#   --yes, -y           yes to every question                     PITWALL_INSTALL_YES=1
#   --version vX.Y.Z    install this release                      PITWALL_INSTALL_VERSION
#   --home DIR          install folder (default ~/Pitwall)        PITWALL_INSTALL_HOME
#   --service           start Pitwall at login (macOS)            PITWALL_INSTALL_SERVICE=yes
#   --no-service        do not install the background service     PITWALL_INSTALL_SERVICE=no
#   --wait-idle MIN     wait up to MIN minutes while someone is driving, instead of stopping   PITWALL_INSTALL_WAIT_IDLE
#   --pre               allow pre-releases                        PITWALL_INSTALL_PRE=1
#   --from-zip PATH     install a local pitwall-<version>.zip (PATH.sha256 must be next to it)  PITWALL_INSTALL_FROM_ZIP
#
# Exit codes: 0 ok | 1 error | 2 usage or unsupported | 3 telemetry live (someone is driving) | 4 needs you
# (a question without a terminal, low disk, another install running) | 5 download verification failed.
#
# SHA-256 from the same release proves the download arrived complete and unchanged, not who made it.
# Everything is inside functions and `main "$@"` is the last line, so a download cut short runs nothing.
# Guide: docs/install.md, "Install with one command".

set -eu

PW_REPO="Moment-Up/pitwall"
PW_TAG_RE='^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$'
PW_MIN_CORE="0.2.0"
PW_MIN_FREE_KB=2097152

OPT_YES=0
OPT_VERSION=""
OPT_HOME=""
OPT_SERVICE=""
OPT_WAIT_IDLE=""
OPT_PRE=0
OPT_FROM_ZIP=""
HOME_DIR=""
TAG=""
VDIR=""
UV=""
FETCH=""
DIGEST=""
LOCK=""
LOCK_HELD=0
STAGING=""
DL_DIR=""

say() {
  printf '%s\n' "$*"
}

warn() {
  printf 'warning: %s\n' "$*" >&2
}

die() {
  pw_code=$1
  shift
  printf 'error: %s\n' "$*" >&2
  cleanup
  exit "$pw_code"
}

cleanup() {
  if [ -n "$STAGING" ] && [ -d "$STAGING" ]; then
    rm -rf "$STAGING"
  fi
  if [ -n "$DL_DIR" ] && [ -d "$DL_DIR" ]; then
    # our own downloads: a failed or damaged one is never kept
    rm -f "$DL_DIR/pitwall-$TAG.zip" "$DL_DIR/pitwall-$TAG.zip.sha256" "$DL_DIR/pitwall-$TAG.zip.part"
    rmdir "$DL_DIR" 2>/dev/null || true
    DL_DIR=""
  fi
  if [ "$LOCK_HELD" = 1 ]; then
    rm -rf "$LOCK"
    LOCK_HELD=0
  fi
}

usage() {
  sed -n '2,24p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//' || true
  say "Usage: install.sh [--yes] [--version vX.Y.Z] [--home DIR] [--service|--no-service] [--wait-idle MIN] [--pre] [--from-zip PATH]"
}

# ------------------------------------------------------------------------------------------------ arguments
parse_args() {
  case "${PITWALL_INSTALL_YES:-}" in 1|yes|true) OPT_YES=1 ;; esac
  OPT_VERSION=${PITWALL_INSTALL_VERSION:-}
  OPT_HOME=${PITWALL_INSTALL_HOME:-}
  OPT_SERVICE=${PITWALL_INSTALL_SERVICE:-}
  OPT_WAIT_IDLE=${PITWALL_INSTALL_WAIT_IDLE:-}
  case "${PITWALL_INSTALL_PRE:-}" in 1|yes|true) OPT_PRE=1 ;; esac
  OPT_FROM_ZIP=${PITWALL_INSTALL_FROM_ZIP:-}
  while [ $# -gt 0 ]; do
    case "$1" in
      -y|--yes) OPT_YES=1 ;;
      --version) [ $# -ge 2 ] || die 2 "--version needs a value"; OPT_VERSION=$2; shift ;;
      --version=*) OPT_VERSION=${1#*=} ;;
      --home) [ $# -ge 2 ] || die 2 "--home needs a folder"; OPT_HOME=$2; shift ;;
      --home=*) OPT_HOME=${1#*=} ;;
      --service) OPT_SERVICE=yes ;;
      --no-service) OPT_SERVICE=no ;;
      --wait-idle) [ $# -ge 2 ] || die 2 "--wait-idle needs minutes"; OPT_WAIT_IDLE=$2; shift ;;
      --wait-idle=*) OPT_WAIT_IDLE=${1#*=} ;;
      --pre) OPT_PRE=1 ;;
      --from-zip) [ $# -ge 2 ] || die 2 "--from-zip needs a path"; OPT_FROM_ZIP=$2; shift ;;
      --from-zip=*) OPT_FROM_ZIP=${1#*=} ;;
      -h|--help) usage; exit 0 ;;
      *) die 2 "unknown option: $1 (see --help)" ;;
    esac
    shift
  done
  case "$OPT_SERVICE" in ""|yes|no) ;; *) die 2 "PITWALL_INSTALL_SERVICE must be yes or no" ;; esac
  if [ -n "$OPT_WAIT_IDLE" ]; then
    case "$OPT_WAIT_IDLE" in *[!0-9]*|"") die 2 "--wait-idle takes whole minutes, e.g. --wait-idle 120" ;; esac
  fi
  if [ -n "$OPT_VERSION" ] && ! valid_tag "$OPT_VERSION"; then
    die 2 "--version must look like v1.2.3 or v1.2.3-rc.1"
  fi
}

# ------------------------------------------------------------------------------------------------ helpers
valid_tag() {
  case "$1" in
    ""|*[!0-9A-Za-z.-]*) return 1 ;;
  esac
  printf '%s\n' "$1" | grep -Eq "$PW_TAG_RE"
}

# semver_cmp A B: prints -1, 0 or 1 (SemVer 2.0: a pre-release sorts below its release; rc.2 < rc.10)
semver_cmp() {
  LC_ALL=C awk -v a="$1" -v b="$2" '
    function cmpid(x, y,   nx, ny) {
      nx = (x ~ /^[0-9]+$/); ny = (y ~ /^[0-9]+$/)
      if (nx && ny) { x = x + 0; y = y + 0; return (x < y) ? -1 : (x > y) }
      if (nx) return -1
      if (ny) return 1
      return ("" x < "" y) ? -1 : ("" x > "" y)
    }
    BEGIN {
      sub(/^v/, "", a); sub(/^v/, "", b)
      pa = index(a, "-"); pb = index(b, "-")
      ca = pa ? substr(a, 1, pa - 1) : a; ra = pa ? substr(a, pa + 1) : ""
      cb = pb ? substr(b, 1, pb - 1) : b; rb = pb ? substr(b, pb + 1) : ""
      split(ca, A, "."); split(cb, B, ".")
      for (i = 1; i <= 3; i++) if (A[i] + 0 != B[i] + 0) { print ((A[i] + 0 < B[i] + 0) ? -1 : 1); exit }
      if (ra == "" && rb == "") { print 0; exit }
      if (ra == "") { print 1; exit }
      if (rb == "") { print -1; exit }
      na = split(ra, X, "."); nb = split(rb, Y, ".")
      for (i = 1; i <= na && i <= nb; i++) { c = cmpid(X[i], Y[i]); if (c != 0) { print c; exit } }
      print ((na < nb) ? -1 : (na > nb))
    }'
}

# core_at_least TAG X.Y.Z: the X.Y.Z part of TAG (pre-release ignored) is at least X.Y.Z
core_at_least() {
  pw_core=${1#v}
  pw_core=${pw_core%%-*}
  [ "$(semver_cmp "v$pw_core" "v$2")" != "-1" ]
}

checked_base() {
  case "$2" in
    https://?*) printf '%s' "${2%/}" ;;
    *)
      if printf '%s\n' "$2" | grep -Eq '^http://(127\.[0-9]+\.[0-9]+\.[0-9]+|localhost|\[::1\])(:[0-9]+)?(/[^[:space:]]*)?$'; then
        printf '%s' "${2%/}"
      else
        die 2 "$1 must be an https:// URL (or http:// on this computer, for tests)"
      fi
      ;;
  esac
}

api_base() {
  if [ -n "${PITWALL_RELEASES_API:-}" ]; then
    checked_base PITWALL_RELEASES_API "${PITWALL_RELEASES_API:-}"
  else
    printf '%s' "https://api.github.com"
  fi
}

download_base() {
  if [ -n "${PITWALL_RELEASES_DOWNLOAD:-}" ]; then
    checked_base PITWALL_RELEASES_DOWNLOAD "${PITWALL_RELEASES_DOWNLOAD:-}"
  else
    printf '%s' "https://github.com/$PW_REPO/releases/download"
  fi
}

# fetch URL DEST: download a file (follows redirects)
fetch() {
  if [ "$FETCH" = curl ]; then
    curl -fsSL --connect-timeout 10 --retry 2 -A "pitwall-install.sh" -o "$2" "$1"
  else
    wget -q --timeout=60 --tries=3 -U "pitwall-install.sh" -O "$2" "$1"
  fi
}

# fetch_api URL: print a GitHub API answer
fetch_api() {
  if [ "$FETCH" = curl ]; then
    curl -fsSL --connect-timeout 10 --max-time 60 -A "pitwall-install.sh" \
      -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" "$1"
  else
    wget -q --timeout=60 -U "pitwall-install.sh" --header="Accept: application/vnd.github+json" \
      --header="X-GitHub-Api-Version: 2022-11-28" -O - "$1"
  fi
}

# http_quiet URL: print a local answer, or fail (2 s)
http_quiet() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -m 2 "$1" 2>/dev/null
  elif command -v wget >/dev/null 2>&1; then
    wget -q -T 2 -t 1 -O - "$1" 2>/dev/null
  else
    return 1
  fi
}

# json_strings KEY: the string values of "KEY" in JSON on stdin, one per line (values without quotes or commas)
# Each of , { } [ ] becomes a newline (five characters to five newlines: a set, as intended; \133 \135 are [ ]).
json_strings() {
  # shellcheck disable=SC2020
  tr ',{}\133\135' '\n\n\n\n\n' | sed -n "s/^[[:space:]]*\"$1\"[[:space:]]*:[[:space:]]*\"\\([^\"\\\\]*\\)\"[[:space:]]*\$/\\1/p"
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{ print $1 }'
  else
    shasum -a 256 "$1" | awk '{ print $1 }'
  fi
}

# ask QUESTION: 0 yes, 1 no, 2 no terminal to ask in (answers come from /dev/tty: stdin is this script with | sh)
ask() {
  if [ "$OPT_YES" = 1 ]; then
    return 0
  fi
  if ! (exec </dev/tty) 2>/dev/null; then
    return 2
  fi
  printf '%s [y/N] ' "$1" >/dev/tty
  pw_answer=""
  read -r pw_answer </dev/tty || pw_answer=""
  case "$pw_answer" in
    y|Y|yes|Yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

# ------------------------------------------------------------------------------------------------ steps
check_platform() {
  if [ "$(id -u)" = 0 ]; then
    die 2 "do not run the installer as root (sudo): run it as yourself; Pitwall installs into your home folder"
  fi
  pw_os=$(uname -s)
  pw_arch=$(uname -m)
  case "$pw_os/$pw_arch" in
    Darwin/arm64|Darwin/x86_64|Linux/x86_64|Linux/aarch64|Linux/arm64) ;;
    *) die 2 "$pw_os on $pw_arch is not supported by this installer (macOS or Linux on x86_64/arm64; Windows: install.ps1)" ;;
  esac
}

check_tools() {
  if command -v curl >/dev/null 2>&1; then
    FETCH=curl
  elif command -v wget >/dev/null 2>&1; then
    FETCH=wget
  elif [ -z "$OPT_FROM_ZIP" ]; then
    die 2 "curl or wget is needed: install curl (Debian/Ubuntu: sudo apt install curl), then run this again"
  fi
  if ! command -v unzip >/dev/null 2>&1; then
    die 2 "unzip is needed: install it (Debian/Ubuntu: sudo apt install unzip; Fedora: sudo dnf install unzip), then run this again"
  fi
  if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
    die 2 "sha256sum or shasum is needed (Debian/Ubuntu: sudo apt install coreutils; Fedora: sudo dnf install perl-Digest-SHA)"
  fi
}

resolve_home() {
  pw_home=${OPT_HOME:-${HOME:-}/Pitwall}
  case "$pw_home" in
    /*) ;;
    *) pw_home="$(pwd)/$pw_home" ;;
  esac
  HOME_DIR=${pw_home%/}
}

resolve_tag() {
  if [ -n "$OPT_FROM_ZIP" ]; then
    [ -f "$OPT_FROM_ZIP" ] || die 2 "--from-zip: $OPT_FROM_ZIP not found"
    case "$OPT_FROM_ZIP" in /*) ;; *) OPT_FROM_ZIP="$(pwd)/$OPT_FROM_ZIP" ;; esac
    pw_base=$(basename "$OPT_FROM_ZIP")
    pw_t=${pw_base#pitwall-}
    pw_t=${pw_t%.zip}
    valid_tag "$pw_t" || die 2 "--from-zip: the file must be named pitwall-<version>.zip"
    if [ -n "$OPT_VERSION" ] && [ "$OPT_VERSION" != "$pw_t" ]; then
      die 2 "--version $OPT_VERSION does not match $pw_base"
    fi
    TAG=$pw_t
    return 0
  fi
  if [ -n "$OPT_VERSION" ]; then
    TAG=$OPT_VERSION
    return 0
  fi
  pw_api=$(api_base)
  if [ "$OPT_PRE" = 1 ]; then
    pw_url="$pw_api/repos/$PW_REPO/releases?per_page=20"
  else
    pw_url="$pw_api/repos/$PW_REPO/releases/latest"
  fi
  say "Looking for the latest Pitwall release..."
  if pw_json=$(fetch_api "$pw_url" 2>/dev/null); then
    pw_tags=$(printf '%s' "$pw_json" | json_strings tag_name)
    pw_names=$(printf '%s' "$pw_json" | json_strings name)
    pw_best=""
    while IFS= read -r pw_t; do
      valid_tag "$pw_t" || continue
      printf '%s\n' "$pw_names" | grep -Fxq "pitwall-$pw_t.zip" || continue
      printf '%s\n' "$pw_names" | grep -Fxq "pitwall-$pw_t.zip.sha256" || continue
      if [ -z "$pw_best" ] || [ "$(semver_cmp "$pw_t" "$pw_best")" = 1 ]; then
        pw_best=$pw_t
      fi
    done <<EOF
$pw_tags
EOF
    [ -n "$pw_best" ] || die 1 "no published release has a pitwall-<version>.zip yet (try again in a few minutes)"
    TAG=$pw_best
  elif [ -z "${PITWALL_RELEASES_API:-}" ] && [ "$OPT_PRE" = 0 ] && [ "$FETCH" = curl ]; then
    # GitHub's API can refuse (rate limit): the releases page redirects /latest to /tag/<version>.
    pw_loc=$(curl -fsSI --connect-timeout 10 -A "pitwall-install.sh" "https://github.com/$PW_REPO/releases/latest" 2>/dev/null \
      | tr -d '\r' | sed -n 's/^[Ll]ocation:[[:space:]]*//p' | tail -n 1)
    TAG=${pw_loc##*/tag/}
  else
    die 1 "could not reach GitHub to find the latest release (check the network, or pass --version vX.Y.Z)"
  fi
  valid_tag "$TAG" || die 1 "could not work out the latest release from GitHub's answer"
}

check_min_version() {
  if [ -n "$OPT_FROM_ZIP" ]; then
    return 0  # a local zip is checked for the installer's other half after unpacking
  fi
  if ! core_at_least "$TAG" "$PW_MIN_CORE"; then
    die 2 "$TAG is older than the one-line installer (v$PW_MIN_CORE): install $TAG by hand: docs/install.md, \"Install from a release\""
  fi
}

check_disk() {
  if [ -f "$HOME_DIR/pitwall-$TAG/.pitwall-ready" ]; then
    return 0
  fi
  pw_dir=$HOME_DIR
  while [ ! -d "$pw_dir" ]; do
    pw_dir=$(dirname "$pw_dir")
  done
  pw_free=$(df -Pk "$pw_dir" 2>/dev/null | awk 'NR == 2 { print $4 }')
  case "$pw_free" in
    ""|*[!0-9]*) warn "could not read the free disk space of $pw_dir" ;;
    *)
      if [ "$pw_free" -lt "$PW_MIN_FREE_KB" ]; then
        die 4 "less than 2 GB free in $pw_dir: free some space and run this again"
      fi
      ;;
  esac
}

http_port() {
  case "${PITWALL_HTTP_PORT:-}" in
    "") ;;
    *[!0-9]*) ;;
    *) printf '%s' "${PITWALL_HTTP_PORT:-}"; return 0 ;;
  esac
  pw_port=""
  if [ -f "$HOME_DIR/install.json" ]; then
    pw_cur=$(json_strings current <"$HOME_DIR/install.json" | head -n 1)
    if valid_tag "$pw_cur" && [ -f "$HOME_DIR/pitwall-$pw_cur/.env" ]; then
      pw_port=$(sed -n 's/^[[:space:]]*\(export[[:space:]][[:space:]]*\)\{0,1\}PITWALL_HTTP_PORT[[:space:]]*=[[:space:]]*["'"'"']\{0,1\}\([0-9][0-9]*\).*/\2/p' \
        "$HOME_DIR/pitwall-$pw_cur/.env" | tail -n 1)
    fi
  fi
  printf '%s' "${pw_port:-8770}"
}

# telemetry_status PORT: live | stale | no_data | down ("live" = a game is streaming right now)
telemetry_status() {
  pw_body=$(http_quiet "http://127.0.0.1:$1/api/health") || { printf 'down'; return 0; }
  pw_st=$(printf '%s' "$pw_body" | tr -d '\n' \
    | sed -n 's/.*"connection"[[:space:]]*:[[:space:]]*{[[:space:]]*"status"[[:space:]]*:[[:space:]]*"\([a-z_]*\)".*/\1/p')
  printf '%s' "${pw_st:-unknown}"
}

check_live() {
  pw_hp=$(http_port)
  if [ "$(telemetry_status "$pw_hp")" != live ]; then
    return 0
  fi
  if [ -z "$OPT_WAIT_IDLE" ] || [ "$OPT_WAIT_IDLE" = 0 ]; then
    die 3 "telemetry is live on http://127.0.0.1:$pw_hp/ (someone is driving): not installing now. Run this again between sessions, or add --wait-idle 120 to wait up to 2 hours."
  fi
  say "Telemetry is live: waiting up to $OPT_WAIT_IDLE min for the session to end..."
  pw_deadline=$(( $(date +%s) + OPT_WAIT_IDLE * 60 ))
  pw_quiet=0
  while [ "$(date +%s)" -lt "$pw_deadline" ]; do
    if [ "$(telemetry_status "$pw_hp")" != live ]; then
      pw_quiet=$((pw_quiet + 1))
      if [ "$pw_quiet" -ge 3 ]; then
        return 0
      fi
    else
      pw_quiet=0
    fi
    sleep 5
  done
  die 3 "still live after $OPT_WAIT_IDLE min: not installing"
}

find_uv() {
  if command -v uv >/dev/null 2>&1; then
    UV=$(command -v uv)
    return 0
  fi
  for pw_c in "${XDG_BIN_HOME:-$HOME/.local/bin}/uv" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [ -x "$pw_c" ]; then
      UV=$pw_c
      return 0
    fi
  done
  return 1
}

ensure_uv() {
  if find_uv; then
    return 0
  fi
  pw_rc=0
  ask "uv (it installs Python 3.12 and Pitwall's packages) is not installed. Install uv from astral.sh now?" || pw_rc=$?
  case "$pw_rc" in
    0) ;;
    2) die 4 "uv is not installed and there is no terminal to ask: run this again with --yes, or install uv first (https://docs.astral.sh/uv/getting-started/installation/)" ;;
    *) die 4 "uv is needed: install it (https://docs.astral.sh/uv/getting-started/installation/), then run this again" ;;
  esac
  [ -n "$FETCH" ] || die 2 "curl or wget is needed to install uv"
  pw_uv_url=$(checked_base PITWALL_INSTALL_UV_URL "${PITWALL_INSTALL_UV_URL:-https://astral.sh/uv/install.sh}")
  mkdir -p "$HOME_DIR"
  pw_uv_script="$HOME_DIR/.uv-install-$$.sh"
  say "Installing uv from $pw_uv_url ..."
  fetch "$pw_uv_url" "$pw_uv_script" || { rm -f "$pw_uv_script"; die 1 "could not download the uv installer"; }
  # No shell-profile edits: the commands Pitwall prints use uv by name; ~/.local/bin is usually on PATH already.
  env UV_NO_MODIFY_PATH=1 INSTALLER_NO_MODIFY_PATH=1 sh "$pw_uv_script" || { rm -f "$pw_uv_script"; die 1 "the uv installer failed (see above)"; }
  rm -f "$pw_uv_script"
  find_uv || die 1 "uv was installed but cannot be found (looked on PATH and in ~/.local/bin and ~/.cargo/bin)"
  say "uv: $UV"
}

take_lock() {
  mkdir -p "$HOME_DIR"
  LOCK="$HOME_DIR/.install.lock"
  if mkdir "$LOCK" 2>/dev/null; then
    LOCK_HELD=1
  elif [ -n "$(find "$LOCK" -maxdepth 0 -mmin +120 2>/dev/null)" ]; then
    rm -rf "$LOCK"
    mkdir "$LOCK" 2>/dev/null || die 4 "another Pitwall install or update is running ($LOCK)"
    LOCK_HELD=1
  else
    die 4 "another Pitwall install or update is running ($LOCK exists). If none is, delete that folder and run this again."
  fi
  printf 'install.sh %s\n' "$$" >"$LOCK/owner"
}

clean_leftovers() {
  for pw_d in "$HOME_DIR"/.staging-*; do
    [ -d "$pw_d" ] || continue
    pw_has_data=0
    for pw_x in "$pw_d"/data "$pw_d"/*/data; do
      if [ -e "$pw_x" ]; then
        pw_has_data=1
      fi
    done
    if [ "$pw_has_data" = 0 ]; then
      rm -rf "$pw_d"
    fi
  done
}

verify_sha() {
  [ -f "$2" ] || die 5 "$(basename "$2") is missing: it must be next to the zip"
  pw_line=$(head -n 1 "$2" | tr -d '\r')
  pw_want=$(printf '%s\n' "$pw_line" | awk '{ print $1 }')
  pw_name=$(printf '%s\n' "$pw_line" | awk '{ print $2 }' | sed 's/^\*//')
  pw_fields=$(printf '%s\n' "$pw_line" | awk '{ print NF }')
  if [ "$pw_fields" != 2 ] || [ "$pw_name" != "pitwall-$3.zip" ]; then
    die 5 "$(basename "$2") does not name pitwall-$3.zip: refusing to install it"
  fi
  pw_have=$(sha256_of "$1")
  if [ "$pw_have" != "$pw_want" ]; then
    die 5 "SHA-256 mismatch for pitwall-$3.zip: the download is damaged or is not the release"
  fi
  DIGEST=$pw_have
}

check_zip() {
  pw_names=$(unzip -Z1 "$1" 2>/dev/null) || die 5 "$(basename "$1") is not a readable zip"
  [ -n "$pw_names" ] || die 5 "$(basename "$1") is empty"
  pw_bad=$(printf '%s\n' "$pw_names" | LC_ALL=C awk -v p="$2/" '
    {
      if ($0 ~ /^\// || index($0, "\\") > 0 || $0 ~ /^[A-Za-z]:/) { print "absolute path: " $0; exit }
      n = split($0, parts, "/")
      for (i = 1; i <= n; i++) if (parts[i] == "..") { print "path with ..: " $0; exit }
      if (substr($0, 1, length(p)) != p) { print "outside " p ": " $0; exit }
      key = $0; sub(/\/$/, "", key)
      if (seen[key]++) { print "duplicate: " $0; exit }
    }')
  [ -z "$pw_bad" ] || die 5 "unsafe zip ($pw_bad): refusing to unpack it"
  pw_links=$(unzip -Z "$1" 2>/dev/null | awk '/^l/ { print; exit }')
  [ -z "$pw_links" ] || die 5 "the zip holds a symbolic link: refusing to unpack it"
}

stage() {
  VDIR="$HOME_DIR/pitwall-$TAG"
  if [ -f "$VDIR/.pitwall-ready" ]; then
    say "pitwall-$TAG is already installed in $HOME_DIR (skipping the download)."
    return 0
  fi
  clean_leftovers
  if [ ! -e "$VDIR" ]; then
    if [ -n "$OPT_FROM_ZIP" ]; then
      pw_zip=$OPT_FROM_ZIP
      pw_sha="$OPT_FROM_ZIP.sha256"
      pw_dl=""
    else
      pw_dl="$HOME_DIR/downloads"
      DL_DIR=$pw_dl
      mkdir -p "$pw_dl"
      pw_zip="$pw_dl/pitwall-$TAG.zip"
      pw_sha="$pw_zip.sha256"
      pw_base=$(download_base)
      say "Downloading pitwall-$TAG.zip..."
      fetch "$pw_base/$TAG/pitwall-$TAG.zip.sha256" "$pw_sha" || die 1 "could not download pitwall-$TAG.zip.sha256 (is $TAG a published release?)"
      fetch "$pw_base/$TAG/pitwall-$TAG.zip" "$pw_zip" || die 1 "could not download pitwall-$TAG.zip"
    fi
    say "Checking SHA-256..."
    verify_sha "$pw_zip" "$pw_sha" "$TAG"
    say "Checking SHA-256... OK"
    check_zip "$pw_zip" "pitwall-$TAG"
    say "Unpacking..."
    STAGING="$HOME_DIR/.staging-$TAG-$$"
    rm -rf "$STAGING"
    mkdir -p "$STAGING"
    unzip -q -n "$pw_zip" -d "$STAGING" || die 5 "could not unpack pitwall-$TAG.zip"
    if [ ! -f "$STAGING/pitwall-$TAG/src/pitwall/install/activate.py" ]; then
      die 2 "pitwall-$TAG.zip is older than the one-line installer: install it by hand (docs/install.md)"
    fi
    if [ -e "$VDIR" ]; then
      die 1 "$VDIR appeared while unpacking: not replacing it"
    fi
    mv "$STAGING/pitwall-$TAG" "$VDIR"
    rm -rf "$STAGING"
    STAGING=""
    if [ -n "$pw_dl" ]; then
      rm -f "$pw_zip" "$pw_sha"
      rmdir "$pw_dl" 2>/dev/null || true
      DL_DIR=""
    fi
  else
    say "Resuming the unfinished install in $VDIR"
  fi
  say "Installing Python and Pitwall's packages (uv sync)..."
  if ! (unset VIRTUAL_ENV UV_PROJECT_ENVIRONMENT; cd "$VDIR" && "$UV" sync --locked --all-extras); then
    die 1 "uv sync failed in $VDIR (see above). Run this installer again to resume."
  fi
  if ! (cd "$VDIR" && ./.venv/bin/python -c "import pitwall.api.app, pitwall.core.runtime"); then
    die 1 "Pitwall is installed in $VDIR, but its server does not start on this computer (import error above)"
  fi
  if [ -n "$DIGEST" ]; then pw_digest="\"$DIGEST\""; else pw_digest=null; fi
  printf '{"tag": "%s", "sha256": %s, "unix": %s}\n' "$TAG" "$pw_digest" "$(date +%s)" >"$VDIR/.pitwall-ready"
  say "Installing Python and Pitwall's packages (uv sync)... done"
}

hand_over() {
  set -- install-finish --home "$HOME_DIR" --version-dir "$VDIR" --installer install.sh
  if [ "$OPT_YES" = 1 ]; then
    set -- "$@" --yes
  fi
  if [ -n "$OPT_SERVICE" ]; then
    set -- "$@" --service "$OPT_SERVICE"
  fi
  if [ -n "$OPT_WAIT_IDLE" ]; then
    set -- "$@" --wait-idle "$OPT_WAIT_IDLE"
  fi
  cleanup
  cd "$VDIR"
  exec "$VDIR/.venv/bin/pitwall" "$@"
}

main() {
  trap 'cleanup' EXIT
  trap 'cleanup; exit 130' INT TERM
  parse_args "$@"
  check_platform
  check_tools
  resolve_home
  resolve_tag
  say "Pitwall $TAG -> $HOME_DIR"
  check_min_version
  check_disk
  check_live
  ensure_uv
  take_lock
  stage
  hand_over
}

main "$@"
