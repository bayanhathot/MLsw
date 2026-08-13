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
# and upload-volume ownership initialization to complete successfully. ollama
# has no dependents (backend deliberately isn't gated on it, see
# docker-compose.prod.yml), so it must be listed explicitly here or `up`
# would never create it at all on a fresh VM.
"${compose[@]}" up --detach --remove-orphans backend frontend caddy ollama
"${compose[@]}" ps

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
  if ! "${compose[@]}" exec -T ollama ollama pull "${ollama_model}"; then
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
