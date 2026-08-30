#!/usr/bin/env bash
# Verify a running docker-compose.prod.yml stack from the public Caddy edge
# down to its internal services. The browser journey and stress workload run
# separately; this script supplies fast, precise infrastructure diagnostics.

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd -- "${script_dir}/.." && pwd)"
env_file="${SYSTEM_TEST_ENV_FILE:-${script_dir}/system-test.env}"
base_url="${SYSTEM_TEST_BASE_URL:-https://localhost}"

compose=(
  docker compose
  --project-directory "${project_dir}"
  --env-file "${env_file}"
  --file "${project_dir}/docker-compose.prod.yml"
)
curl_common=(
  --fail
  --silent
  --show-error
  --insecure
  --max-time 15
  --retry 10
  --retry-delay 1
  --retry-all-errors
)

require_service_state() {
  local service="$1"
  local expected="$2"
  local container_id state
  container_id="$("${compose[@]}" ps --quiet "${service}")"
  test -n "${container_id}" || {
    echo "${service}: container is missing" >&2
    return 1
  }
  state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}")"
  test "${state}" = "${expected}" || {
    echo "${service}: expected ${expected}, got ${state}" >&2
    return 1
  }
  echo "${service}: ${state}"
}

for service in postgres redis backend studio-ai-service frontend; do
  require_service_state "${service}" healthy
done
require_service_state caddy running

frontend_html="$(curl "${curl_common[@]}" "${base_url}/")"
grep --quiet --ignore-case 'cuemix' <<<"${frontend_html}"

health_json="$(curl "${curl_common[@]}" "${base_url}/api/health")"
db_health_json="$(curl "${curl_common[@]}" "${base_url}/api/db-health")"
python3 - "${health_json}" "${db_health_json}" <<'PY'
import json
import sys

health = json.loads(sys.argv[1])
database = json.loads(sys.argv[2])
assert health["service"] == "cuemix-backend"
assert health["status"] == "healthy"
assert database["database"] == "connected"
assert database["result"] == 1
assert database["redis"]["configured"] is True
assert database["redis"]["reachable"] is True
PY

"${compose[@]}" exec -T studio-ai-service python - <<'PY'
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=5) as response:
    payload = json.load(response)
assert payload["service"] == "cuemix-studio-ai"
assert payload["status"] == "healthy"
PY

media_file="$(mktemp)"
trap 'rm -f -- "${media_file}"' EXIT
curl "${curl_common[@]}" --output "${media_file}" "${base_url}/api/static/audio/cuemix-demo.wav"
test "$(head -c 4 "${media_file}")" = "RIFF"

echo "Container system check passed through ${base_url}."
