#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
cd "${DEPLOY_ROOT}"

test -f .env || { echo "${DEPLOY_ROOT}/.env is missing" >&2; exit 1; }
test -f docker-compose.prod.yml || { echo "Production Compose file is missing" >&2; exit 1; }

compose=(docker compose --env-file .env --file docker-compose.prod.yml)
ollama_model="$(grep -E '^OLLAMA_MODEL=' .env 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
ollama_model="${ollama_model:-qwen3:8b}"
production_timeout="$(grep -E '^STUDIO_AI_TIMEOUT_SECONDS=' .env 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
production_timeout="${production_timeout:-250}"

echo "Checking that Ollama is reachable..."
ollama_list="$("${compose[@]}" exec -T ollama ollama list)"
if ! awk 'NR > 1 {print $1}' <<<"${ollama_list}" | grep -qxF "${ollama_model}"; then
  echo "Configured Ollama model ${ollama_model} is not installed." >&2
  exit 1
fi
echo "Verified installed Ollama model: ${ollama_model}"

ollama_processes="$("${compose[@]}" exec -T ollama ollama ps)"
if ! awk 'NR > 1 {print $1}' <<<"${ollama_processes}" | grep -qxF "${ollama_model}"; then
  echo "Configured Ollama model ${ollama_model} is not loaded in memory." >&2
  exit 1
fi
echo "Verified loaded Ollama model: ${ollama_model}"

echo "Running one real Studio planning request (deadline: ${production_timeout}s)..."
"${compose[@]}" exec -T \
  -e "STUDIO_AI_DEPLOYMENT_GATE_TIMEOUT_SECONDS=${production_timeout}" \
  studio-ai-service python -m studio_ai.deployment_gate
