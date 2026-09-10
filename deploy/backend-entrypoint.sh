#!/bin/sh
set -eu
mkdir -p /app/data/onboarded-sources
# Seed only missing synthetic sources; never overwrite user onboarding edits.
for source in /app/seed-sources/*; do
  name=$(basename "$source")
  if [ ! -e "/app/data/onboarded-sources/$name" ]; then
    cp -R "$source" /app/data/onboarded-sources/
  fi
done
# Compose injects environment before Python imports LangChain/LangSmith.
# API_HOST is the loopback address used by the backend's own MCP client.
exec uv run --no-env-file --project /app/backend \
  uvicorn customer_signal.api:create_app --factory --host 0.0.0.0 --port 8000 --workers 1 \
  --root-path /backend
