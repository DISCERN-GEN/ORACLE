#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f .env ]] || { echo "Missing .env. Run ./scripts/init-env.sh, then review .env." >&2; exit 1; }
docker compose -f infra/docker-compose.yml up --build -d
echo "ORACLE services started. Open http://localhost:3000 after health checks pass."
