#!/usr/bin/env bash
set -Eeuo pipefail

# Runs a full backup -> restore-into-scratch -> verify -> cleanup cycle
# against real production data, without ever touching production itself:
# restore.sh's --target-db/--target-uploads-volume land in a separate
# database/volume, dropped again at the end of this script. Runs entirely
# on the VM -- it prints plain, structured progress/summary text to stdout
# for whatever invoked it (the "backup-restore-drill" GitHub Actions job,
# workflow_dispatch run_backup_drill=true, forwards this into its job
# summary) to capture; see deploy/README.md's Operations section. Safe to
# also run manually.
#
# Usage:
#   DEPLOY_ROOT=~/cuemix-deploy DRILL_ID=<unique-id> bash backup-restore-drill.sh

DEPLOY_ROOT="${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
DRILL_ID="${DRILL_ID:?DRILL_ID is required}"
BACKUP_ROOT="${BACKUP_ROOT:-${DEPLOY_ROOT}/../cuemix-backups}"
# Postgres identifiers can't contain hyphens unquoted, but restore.sh always
# double-quotes them -- still keep the db name conservative (underscores
# only) since it's echoed back through several layers of quoting.
TARGET_DB="cuemix_restore_drill_${DRILL_ID//[^a-zA-Z0-9_]/_}"
TARGET_VOLUME="cuemix-restore-drill-${DRILL_ID//[^a-zA-Z0-9_]/_}_uploads_data"

cd "${DEPLOY_ROOT}"
test -f .env || { echo "${DEPLOY_ROOT}/.env is missing" >&2; exit 1; }
test -f deploy/backup.sh || { echo "deploy/backup.sh is missing" >&2; exit 1; }
test -f deploy/restore.sh || { echo "deploy/restore.sh is missing" >&2; exit 1; }

postgres_user="$(grep -E '^POSTGRES_USER=' .env | tail -n1 | cut -d= -f2-)"
postgres_db="$(grep -E '^POSTGRES_DB=' .env | tail -n1 | cut -d= -f2-)"
: "${postgres_user:?POSTGRES_USER is missing from .env}"
: "${postgres_db:?POSTGRES_DB is missing from .env}"
compose=(docker compose --env-file .env --file docker-compose.prod.yml)

# Always drop the scratch database/volume, whether the drill below passes,
# fails validation, or errors out partway -- a drill run must never leave
# cruft behind on the VM for the next one to trip over.
cleanup() {
  echo "--- Cleaning up scratch resources (${TARGET_DB}, ${TARGET_VOLUME}) ---"
  "${compose[@]}" exec -T postgres psql --username "${postgres_user}" --dbname postgres \
    -c "DROP DATABASE IF EXISTS \"${TARGET_DB}\";" >/dev/null 2>&1 || true
  docker volume rm "${TARGET_VOLUME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "--- Recording production row/file counts before the drill ---"
production_rows_before="$("${compose[@]}" exec -T postgres psql --username "${postgres_user}" --dbname "${postgres_db}" \
  --tuples-only --no-align -c "SELECT COALESCE(SUM(n_live_tup), 0) FROM pg_stat_user_tables;" | tr -d '[:space:]')"
production_files_before="$(docker run --rm -v cuemix-production_uploads_data:/data:ro alpine:3.20 sh -c "find /data -type f | wc -l" | tr -d '[:space:]')"
echo "Production live row count (approx, pre-drill): ${production_rows_before}"
echo "Production uploads file count (pre-drill): ${production_files_before}"

echo "--- Running deploy/backup.sh ---"
DEPLOY_ROOT="${DEPLOY_ROOT}" BACKUP_ROOT="${BACKUP_ROOT}" bash deploy/backup.sh

db_backup="$(ls -t "${BACKUP_ROOT}"/db-*.sql.gz | head -n1)"
uploads_backup="$(ls -t "${BACKUP_ROOT}"/uploads-*.tar.gz | head -n1)"
: "${db_backup:?No db-*.sql.gz backup was produced}"
: "${uploads_backup:?No uploads-*.tar.gz backup was produced}"
echo "Fresh backup: ${db_backup} / ${uploads_backup}"

echo "--- Restoring into scratch targets (production untouched) ---"
DEPLOY_ROOT="${DEPLOY_ROOT}" bash deploy/restore.sh \
  --db "${db_backup}" --target-db "${TARGET_DB}" \
  --uploads "${uploads_backup}" --target-uploads-volume "${TARGET_VOLUME}"

restored_rows="$("${compose[@]}" exec -T postgres psql --username "${postgres_user}" --dbname "${TARGET_DB}" \
  --tuples-only --no-align -c "SELECT COALESCE(SUM(n_live_tup), 0) FROM pg_stat_user_tables;" | tr -d '[:space:]')"
restored_files="$(docker run --rm -v "${TARGET_VOLUME}:/data:ro" alpine:3.20 sh -c "find /data -type f | wc -l" | tr -d '[:space:]')"

echo ""
echo "=== Backup/restore drill summary ==="
echo "Backup files:                    ${db_backup} / ${uploads_backup}"
echo "Production live row count:       ${production_rows_before} (pre-drill, approx)"
echo "Production uploads file count:   ${production_files_before} (pre-drill)"
echo "Restored database row count:     ${restored_rows}"
echo "Restored volume file count:      ${restored_files}"

# A silent "restore.sh ran without erroring" isn't the same as "the data
# actually came back" -- fail loudly if production clearly had data but the
# restored copy came back empty.
failed=0
if [ "${production_rows_before}" -gt 0 ] && [ "${restored_rows}" -eq 0 ]; then
  echo "FAIL: production has ${production_rows_before} live rows but the restored database has 0." >&2
  failed=1
fi
if [ "${production_files_before}" -gt 0 ] && [ "${restored_files}" -eq 0 ]; then
  echo "FAIL: production has ${production_files_before} uploaded files but the restored volume has 0." >&2
  failed=1
fi
if [ "${failed}" -ne 0 ]; then
  exit 1
fi

echo "PASS: restore produced ${restored_rows} rows and ${restored_files} files."
