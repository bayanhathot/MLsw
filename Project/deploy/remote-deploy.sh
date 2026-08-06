#!/usr/bin/env bash
#
# remote-deploy.sh
#
# Runs ON the Azure VM (invoked over SSH by the GitHub Actions deploy job).
# Pulls the already-built images from GHCR and runs them - this script never
# builds anything. That split (build+push in CI, pull+run on the VM) is what
# makes the deploy idempotent and reproducible from the images alone.

set -Eeuo pipefail

: "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
: "${BACKEND_IMAGE:?BACKEND_IMAGE is required}"
: "${FRONTEND_IMAGE:?FRONTEND_IMAGE is required}"

shared_env="${DEPLOY_ROOT}/.env"
compose=(docker compose -p zonix -f docker-compose.prod.yml)

if [[ ! -f "${shared_env}" ]]; then
  echo "Production environment file is missing: ${shared_env}" >&2
  echo "Create it once on the Azure VM before the first deploy (see deploy/README.md)." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed on the Azure VM." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "The Docker Compose plugin is not installed on the Azure VM." >&2
  exit 1
fi

cd "${DEPLOY_ROOT}"

export BACKEND_IMAGE
export FRONTEND_IMAGE

"${compose[@]}" config --quiet
"${compose[@]}" pull
"${compose[@]}" up -d postgres

database_ready=false
for _ in {1..30}; do
  if "${compose[@]}" exec -T postgres sh -c \
    'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
    database_ready=true
    break
  fi

  sleep 2
done

if [[ "${database_ready}" != "true" ]]; then
  echo "PostgreSQL did not become ready in time." >&2
  exit 1
fi

# Run migrations from the freshly pulled backend image, before it serves traffic.
"${compose[@]}" run --rm backend python -m alembic upgrade head

"${compose[@]}" up -d --remove-orphans

backend_ready=false
for _ in {1..30}; do
  if "${compose[@]}" exec -T backend python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/', timeout=3)" \
    >/dev/null 2>&1; then
    backend_ready=true
    break
  fi

  sleep 2
done

if [[ "${backend_ready}" != "true" ]]; then
  echo "The deployed backend did not pass its internal health check." >&2
  "${compose[@]}" logs --tail=100 backend
  exit 1
fi

"${compose[@]}" ps

echo "Deployment of ${BACKEND_IMAGE} / ${FRONTEND_IMAGE} completed successfully."
