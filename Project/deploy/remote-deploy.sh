#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
BACKEND_IMAGE="${BACKEND_IMAGE:?BACKEND_IMAGE is required}"
FRONTEND_IMAGE="${FRONTEND_IMAGE:?FRONTEND_IMAGE is required}"
export BACKEND_IMAGE FRONTEND_IMAGE

cd "${DEPLOY_ROOT}"
test -f .env || { echo "${DEPLOY_ROOT}/.env is missing" >&2; exit 1; }
test -f docker-compose.prod.yml || { echo "Production Compose file is missing" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "Docker is not installed" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is not installed" >&2; exit 1; }

compose=(docker compose --env-file .env --file docker-compose.prod.yml)
"${compose[@]}" config --quiet
"${compose[@]}" pull
# Service dependencies wait for PostgreSQL and require the one-shot migration
# and upload-volume ownership initialization to complete successfully.
"${compose[@]}" up --detach --remove-orphans backend frontend caddy
"${compose[@]}" ps
