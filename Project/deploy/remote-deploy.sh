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

# CI owns these non-secret feature switches for the course test deployment.
# The VM's .env deliberately survives deploys, so merely changing Compose's
# defaults cannot fix an old explicit "false" value. Persist the validated
# values supplied by the workflow before Compose reads the file. A manual
# invocation that supplies none of them leaves .env untouched, preserving
# the dashboard's emergency kill-switch behavior outside automated deploys.
set_managed_env() {
  local key="$1"
  local value="$2"
  local temporary
  temporary="$(mktemp "${DEPLOY_ROOT}/.env.XXXXXX")"
  awk -v key="${key}" -v value="${value}" '
    BEGIN { replaced = 0 }
    index($0, key "=") == 1 { print key "=" value; replaced = 1; next }
    { print }
    END { if (!replaced) print key "=" value }
  ' .env > "${temporary}"
  chmod --reference=.env "${temporary}"
  mv "${temporary}" .env
}

if [ -n "${MANAGED_AUDIUS_ANALYSIS_CACHE_ENABLED:-}" ]; then
  case "${MANAGED_AUDIUS_ANALYSIS_CACHE_ENABLED}" in
    true|false) ;;
    *) echo "MANAGED_AUDIUS_ANALYSIS_CACHE_ENABLED must be true or false" >&2; exit 1 ;;
  esac
  set_managed_env AUDIUS_ANALYSIS_CACHE_ENABLED "${MANAGED_AUDIUS_ANALYSIS_CACHE_ENABLED}"
fi
if [ -n "${MANAGED_DEBUG_DASHBOARD_ENABLED:-}" ]; then
  case "${MANAGED_DEBUG_DASHBOARD_ENABLED}" in
    true|false) ;;
    *) echo "MANAGED_DEBUG_DASHBOARD_ENABLED must be true or false" >&2; exit 1 ;;
  esac
  set_managed_env DEBUG_DASHBOARD_ENABLED "${MANAGED_DEBUG_DASHBOARD_ENABLED}"
fi
if [ -n "${MANAGED_ENABLE_PIPELINE_DEBUG:-}" ]; then
  case "${MANAGED_ENABLE_PIPELINE_DEBUG}" in
    true|false) ;;
    *) echo "MANAGED_ENABLE_PIPELINE_DEBUG must be true or false" >&2; exit 1 ;;
  esac
  set_managed_env ENABLE_PIPELINE_DEBUG "${MANAGED_ENABLE_PIPELINE_DEBUG}"
fi

compose=(docker compose --env-file .env --file docker-compose.prod.yml)
"${compose[@]}" config --quiet
"${compose[@]}" pull
# Service dependencies wait for PostgreSQL and require the one-shot migration
# and upload-volume ownership initialization to complete successfully. ollama
# has no dependents (backend deliberately isn't gated on it, see
# docker-compose.prod.yml), so it must be listed explicitly here or `up`
# would never create it at all on a fresh VM.
"${compose[@]}" up --detach --remove-orphans backend frontend caddy ollama
"${compose[@]}" ps

# Prove the recreated backend received the managed values. This catches the
# exact class of drift where CI is green but an old VM .env silently keeps a
# feature disabled. Do not print the full container environment: it contains
# production credentials.
verify_managed_env() {
  local key="$1"
  local expected="$2"
  local actual
  actual="$("${compose[@]}" exec -T backend printenv "${key}")"
  if [ "${actual}" != "${expected}" ]; then
    echo "running backend has ${key}=${actual:-<unset>}; expected ${expected}" >&2
    exit 1
  fi
  echo "Verified running backend feature setting: ${key}=${expected}"
}
if [ -n "${MANAGED_AUDIUS_ANALYSIS_CACHE_ENABLED:-}" ]; then
  verify_managed_env AUDIUS_ANALYSIS_CACHE_ENABLED "${MANAGED_AUDIUS_ANALYSIS_CACHE_ENABLED}"
fi
if [ -n "${MANAGED_DEBUG_DASHBOARD_ENABLED:-}" ]; then
  verify_managed_env DEBUG_DASHBOARD_ENABLED "${MANAGED_DEBUG_DASHBOARD_ENABLED}"
fi
if [ -n "${MANAGED_ENABLE_PIPELINE_DEBUG:-}" ]; then
  verify_managed_env ENABLE_PIPELINE_DEBUG "${MANAGED_ENABLE_PIPELINE_DEBUG}"
fi

# Ensure the local LLM refinement model is present. Read OLLAMA_MODEL out of
# the real deployment .env (not just the compose file's own default) so a
# custom override there is honored; falls back to the same default
# docker-compose.prod.yml uses if the key is absent.
ollama_model="$(grep -E '^OLLAMA_MODEL=' .env 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
ollama_model="${ollama_model:-qwen3:8b}"

echo "Waiting for the ollama service to accept commands..."
ollama_ready=0
for _attempt in $(seq 1 20); do
  if "${compose[@]}" exec -T ollama ollama list >/dev/null 2>&1; then
    ollama_ready=1
    break
  fi
  sleep 3
done

if [ "${ollama_ready}" -eq 1 ]; then
  # `ollama pull` is itself idempotent (a fast manifest check short-circuits
  # a re-download once the model is already present), so this is safe and
  # cheap to run on every deploy, not just the first.
  echo "Ensuring Ollama model ${ollama_model} is pulled..."
  if "${compose[@]}" exec -T ollama ollama pull "${ollama_model}"; then
    # Force the model into memory now, at deploy time, rather than letting
    # the first real classification request pay for a cold load from disk --
    # Ollama unloads an idle model after its keep-alive window (see
    # OLLAMA_KEEP_ALIVE) but nothing loads it back in until something asks.
    # Same never-fail-the-deploy principle as the pull step above.
    echo "Warming up Ollama model ${ollama_model}..."
    if ! "${compose[@]}" exec -T ollama ollama run "${ollama_model}" "ok"; then
      echo "warning: failed to warm up ${ollama_model}; the first real" >&2
      echo "request will pay the cold-load cost instead. Warm it up" >&2
      echo "manually: docker compose exec ollama ollama run ${ollama_model} ok" >&2
    fi
  else
    echo "warning: failed to pull ${ollama_model}; the app keeps working via" >&2
    echo "the deterministic prompt-parse fallback until this is retried" >&2
    echo "manually: docker compose exec ollama ollama pull ${ollama_model}" >&2
  fi
else
  # Never fail the deploy over this: the LLM refinement step is optional at
  # every call site (prompt_parser.parse_prompt fails open), same principle
  # backend's own healthcheck already applies to ollama.
  echo "warning: ollama did not become ready in time; skipping model pull." >&2
  echo "The app will run on the deterministic parser until this is retried" >&2
  echo "manually: docker compose exec ollama ollama pull ${ollama_model}" >&2
fi

# Install (or refresh) a daily backup cron job -- idempotent, so this is
# safe to run on every deploy, not just the first. Runs as whichever user
# this script itself runs as (the SSH deploy user), consistent with
# DEPLOY_ROOT already being that user's home-relative path. See
# deploy/backup.sh and deploy/README.md's Operations section.
cron_marker="# cuemix-backup (managed by remote-deploy.sh -- do not edit by hand)"
cron_line="0 3 * * * DEPLOY_ROOT=${DEPLOY_ROOT} /usr/bin/env bash ${DEPLOY_ROOT}/deploy/backup.sh >> ${DEPLOY_ROOT}/../cuemix-backups/backup.log 2>&1 ${cron_marker}"
existing_crontab="$(crontab -l 2>/dev/null | grep -v -F "${cron_marker}" || true)"
{
  printf '%s\n' "${existing_crontab}" | sed '/^$/d'
  printf '%s\n' "${cron_line}"
} | crontab -
echo "Installed daily backup cron job (03:00 UTC): ${cron_line}"
