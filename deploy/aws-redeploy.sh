#!/bin/bash
set -euo pipefail
main() {
export HOME="${HOME:-/root}"
cd "$(dirname "$0")/.."
test -f .local/compose/stack.env
exec 9>.local/compose/deploy.lock
flock -n 9 || { echo "Another deployment is running." >&2; exit 1; }
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Commit or preserve server changes before deploying." >&2
  git status --short
  exit 1
fi
source_ref="${1:-main}"
git fetch --depth 1 origin "$source_ref"
git checkout --detach FETCH_HEAD
public_url="$(python3 deploy/aws-public-url.py)"
sh deploy/aws-compose.sh config --quiet
sh deploy/aws-compose.sh up --build -d
# Reload the gateway after application container replacement.
sh deploy/aws-compose.sh restart gateway
sh deploy/aws-compose.sh up -d --wait --wait-timeout 600
curl -fsS --retry 30 --retry-delay 3 --retry-all-errors "$public_url/backend/health"
git rev-parse HEAD
sh deploy/aws-compose.sh ps
}
main "$@"
