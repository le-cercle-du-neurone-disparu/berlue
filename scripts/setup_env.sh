#!/usr/bin/env bash
# scripts/setup_env.sh
#
# Crée .env de façon interactive : propose une valeur par défaut quand c'est
# possible (GCP_PROJECT via `gcloud config`, sinon des constantes
# raisonnables), pose la question pour le reste. Ne touche jamais à un .env
# déjà existant.
#
# Usage : ./scripts/setup_env.sh   (appelé automatiquement par `make local_setup`)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

if [ -f "$ENV_FILE" ]; then
    echo "⚠️  .env existe déjà — on n'y touche pas."
    exit 0
fi

echo "🔧 Configuration de .env (Entrée pour accepter la valeur par défaut) :"

ask() {
    local var_name="$1" default="$2" prompt="$3" value
    if [ -n "$default" ]; then
        read -rp "  $prompt [$default]: " value
        value="${value:-$default}"
    else
        read -rp "  $prompt: " value
    fi
    printf -v "$var_name" '%s' "$value"
}

gcp_default="$(gcloud config get-value project 2>/dev/null || true)"
[ "$gcp_default" = "(unset)" ] && gcp_default=""

# Mêmes clés que .env.sample, qui fait foi : une clé qui n'y figure pas n'a
# rien à faire ici. Valeurs par défaut non vides pour tout ce que berlue/params.py
# valide (RUN_ENV, BERLUE_LOG_LEVEL...) — une clé présente mais vide écrase le
# défaut Python par une chaîne vide, elle ne le laisse pas s'appliquer.
ask GCP_PROJECT "$gcp_default" "GCP_PROJECT"
ask GOOGLE_APPLICATION_CREDENTIALS "" "GOOGLE_APPLICATION_CREDENTIALS (chemin clé JSON, optionnel)"
ask BUCKET_SUFFIX "1" "BUCKET_SUFFIX"
ask RUN_ENV "local" "RUN_ENV (local|docker|gcp)"
ask PORT "8000" "PORT (port exposé par l'API)"
ask DATA_SIZE "1k" "DATA_SIZE"
ask USE_MOCK "0" "USE_MOCK (0|1 — sert la pipeline mockée sur l'API)"
ask NOTIFY_BASE_URL "" "NOTIFY_BASE_URL (webhook notifications, optionnel)"
ask BERLUE_LOG_LEVEL "INFO" "BERLUE_LOG_LEVEL (ERROR|WARNING|INFO|DEBUG)"
ask EXTRACT_MODEL "llama3.1:8b" "EXTRACT_MODEL (modèle Ollama pour l'extraction)"

{
    echo "GCP_PROJECT=$GCP_PROJECT"
    if [ -n "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
        echo "GOOGLE_APPLICATION_CREDENTIALS=$GOOGLE_APPLICATION_CREDENTIALS"
    else
        echo "# GOOGLE_APPLICATION_CREDENTIALS="
    fi
    echo "BUCKET_SUFFIX=$BUCKET_SUFFIX"
    echo "RUN_ENV=$RUN_ENV"
    echo "PORT=$PORT"
    echo "DATA_SIZE=$DATA_SIZE"
    echo "USE_MOCK=$USE_MOCK"
    if [ -n "$NOTIFY_BASE_URL" ]; then
        echo "NOTIFY_BASE_URL=$NOTIFY_BASE_URL"
    else
        echo "# NOTIFY_BASE_URL="
    fi
    echo "BERLUE_LOG_LEVEL=$BERLUE_LOG_LEVEL"
    echo "EXTRACT_MODEL=$EXTRACT_MODEL"
} > "$ENV_FILE"

echo "✅ .env créé."
