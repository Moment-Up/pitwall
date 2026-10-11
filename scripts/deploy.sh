#!/usr/bin/env bash
# Kept for muscle memory: deploys are now releases of a COMMITTED version (scripts/release.sh), so work in progress
# in this checkout (other engineers, cloud merges) can never reach the live service. Commit first, then deploy.
#   scripts/deploy.sh [git-ref]   == scripts/release.sh [git-ref]   (default HEAD)
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/release.sh" "$@"
