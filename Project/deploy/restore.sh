#!/usr/bin/env bash
set -Eeuo pipefail

# Restores a backup.sh-produced database dump and/or uploads archive.
# Defaults to the live production database/volume -- pass --target-db
# and/or --target-uploads-volume to restore into a scratch copy instead
# (see README.md's Operations section for the restore drill this
# was verified with; a scratch target never touches production data,
# since it's created as a separate Postgres database / Docker volume
# alongside the real one).
#
# Usage:
#   DEPLOY_ROOT=~/cuemix-deploy bash restore.sh \
#     --db cuemix-backups/db-<timestamp>.sql.gz \
#     [--uploads cuemix-backups/uploads-<timestamp>.tar.gz] \
#     [--target-db NAME] [--target-uploads-volume NAME]

DEPLOY_ROOT="${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
VOLUME_PREFIX="${VOLUME_PREFIX:-cuemix-production}"
cd "${DEPLOY_ROOT}"
test -f .env || { echo "${DEPLOY_ROOT}/.env is missing" >&2; exit 1; }

db_backup=""
uploads_backup=""
target_db=""
target_volume=""
while [ $# -gt 0 ]; do
  case "$1" in
    --db) db_backup="$2"; shift 2 ;;
    --uploads) uploads_backup="$2"; shift 2 ;;
    --target-db) target_db="$2"; shift 2 ;;
    --target-uploads-volume) target_volume="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done
if [ -z "${db_backup}" ] && [ -z "${uploads_backup}" ]; then
  echo "Usage: restore.sh --db FILE [--uploads FILE] [--target-db NAME] [--target-uploads-volume NAME]" >&2
  exit 1
fi

postgres_user="$(grep -E '^POSTGRES_USER=' .env | tail -n1 | cut -d= -f2-)"
default_db="$(grep -E '^POSTGRES_DB=' .env | tail -n1 | cut -d= -f2-)"
: "${postgres_user:?POSTGRES_USER is missing from .env}"
: "${default_db:?POSTGRES_DB is missing from .env}"
target_db="${target_db:-${default_db}}"
target_volume="${target_volume:-${VOLUME_PREFIX}_uploads_data}"
# See backup.sh's identical comment: Compose needs these to interpolate the
# whole file even for an `exec` against postgres alone.
export BACKEND_IMAGE="${BACKEND_IMAGE:-unused}"
export FRONTEND_IMAGE="${FRONTEND_IMAGE:-unused}"
export STUDIO_AI_IMAGE="${STUDIO_AI_IMAGE:-unused}"
compose=(docker compose --env-file .env --file docker-compose.prod.yml)

if [ -n "${db_backup}" ]; then
  test -f "${db_backup}" || { echo "${db_backup} not found" >&2; exit 1; }
  if [ "${target_db}" != "${default_db}" ]; then
    echo "Creating scratch database '${target_db}' (production '${default_db}' is untouched)..."
    "${compose[@]}" exec -T postgres psql --username "${postgres_user}" --dbname postgres \
      -c "DROP DATABASE IF EXISTS \"${target_db}\";" -c "CREATE DATABASE \"${target_db}\";"
  else
    echo "Restoring into the LIVE production database '${target_db}'."
  fi
  echo "Restoring ${db_backup} into database '${target_db}'..."
  gunzip -c "${db_backup}" | "${compose[@]}" exec -T postgres psql --username "${postgres_user}" --dbname "${target_db}"
  echo "Row counts in '${target_db}':"
  "${compose[@]}" exec -T postgres psql --username "${postgres_user}" --dbname "${target_db}" -c \
    "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname;"
fi

if [ -n "${uploads_backup}" ]; then
  test -f "${uploads_backup}" || { echo "${uploads_backup} not found" >&2; exit 1; }
  backup_dir="$(cd "$(dirname "${uploads_backup}")" && pwd)"
  backup_name="$(basename "${uploads_backup}")"
  if [ "${target_volume}" = "${VOLUME_PREFIX}_uploads_data" ]; then
    echo "Restoring ${uploads_backup} into the LIVE uploads volume '${target_volume}'."
  else
    echo "Restoring ${uploads_backup} into scratch volume '${target_volume}' (production volume is untouched)..."
    docker volume create "${target_volume}" >/dev/null
  fi
  docker run --rm \
    -v "${target_volume}:/data" \
    -v "${backup_dir}:/backup:ro" \
    alpine:3.20 \
    sh -c "cd /data && tar xzf /backup/${backup_name}"
  echo "Files now present in volume '${target_volume}':"
  docker run --rm -v "${target_volume}:/data:ro" alpine:3.20 sh -c "find /data -type f | wc -l"
fi

echo "Restore complete."
