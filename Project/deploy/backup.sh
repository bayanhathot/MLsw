#!/usr/bin/env bash
set -Eeuo pipefail

# Backs up production PostgreSQL and the uploads named volume to a
# timestamped, retained directory on the VM. Installed as a daily cron job
# by remote-deploy.sh (idempotent -- safe to also run manually or via the
# cron entry it installs). See deploy/README.md's Operations section for
# the restore procedure (deploy/restore.sh) and why off-VM storage is the
# natural next step this intentionally does not yet cover.

DEPLOY_ROOT="${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
BACKUP_ROOT="${BACKUP_ROOT:-${DEPLOY_ROOT}/../cuemix-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
VOLUME_PREFIX="${VOLUME_PREFIX:-cuemix-production}"

cd "${DEPLOY_ROOT}"
test -f .env || { echo "${DEPLOY_ROOT}/.env is missing" >&2; exit 1; }
test -f docker-compose.prod.yml || { echo "Production Compose file is missing" >&2; exit 1; }

postgres_db="$(grep -E '^POSTGRES_DB=' .env | tail -n1 | cut -d= -f2-)"
postgres_user="$(grep -E '^POSTGRES_USER=' .env | tail -n1 | cut -d= -f2-)"
: "${postgres_db:?POSTGRES_DB is missing from .env}"
: "${postgres_user:?POSTGRES_USER is missing from .env}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${BACKUP_ROOT}"

compose=(docker compose --env-file .env --file docker-compose.prod.yml)

db_backup="${BACKUP_ROOT}/db-${timestamp}.sql.gz"
echo "Backing up database '${postgres_db}' to ${db_backup}..."
"${compose[@]}" exec -T postgres pg_dump --username "${postgres_user}" --dbname "${postgres_db}" \
  | gzip > "${db_backup}"

uploads_backup="${BACKUP_ROOT}/uploads-${timestamp}.tar.gz"
echo "Backing up the ${VOLUME_PREFIX}_uploads_data volume to ${uploads_backup}..."
# A plain `docker run` against the named volume, not a compose exec -- the
# backend container never has the whole volume conveniently tar-able from
# inside it, and this works whether or not the backend service is healthy.
docker run --rm \
  -v "${VOLUME_PREFIX}_uploads_data:/data:ro" \
  -v "${BACKUP_ROOT}:/backup" \
  alpine:3.20 \
  tar czf "/backup/uploads-${timestamp}.tar.gz" -C /data .

echo "Pruning backups older than ${RETENTION_DAYS} days in ${BACKUP_ROOT}..."
find "${BACKUP_ROOT}" -maxdepth 1 -type f \( -name 'db-*.sql.gz' -o -name 'uploads-*.tar.gz' \) \
  -mtime "+${RETENTION_DAYS}" -print -delete

echo "Backup complete: ${db_backup} ${uploads_backup}"
