#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec env -i PATH="$PATH" HOME="${HOME:-/root}" COMPOSE_PARALLEL_LIMIT=2 \
  docker compose --project-name catch-catch-local \
  --env-file .local/compose/stack.env -f compose.yaml -f compose.aws.yaml "$@"
