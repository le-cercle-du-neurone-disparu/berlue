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

ask GCP_PROJECT "$gcp_default" "GCP_PROJECT"
ask GOOGLE_APPLICATION_CREDENTIALS "" "GOOGLE_APPLICATION_CREDENTIALS (chemin clé JSON, optionnel)"
ask BUCKET_SUFFIX "1" "BUCKET_SUFFIX"
ask TEST_ENV "local" "TEST_ENV (local|docker|gcp)"
ask RUN_ENV "local" "RUN_ENV (local|docker|gcp)"
ask DATA_SIZE "1k" "DATA_SIZE"
ask NOTIFY_BASE_URL "" "NOTIFY_BASE_URL (webhook notifications, optionnel)"

{
    echo "GCP_PROJECT=$GCP_PROJECT"
    if [ -n "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
        echo "GOOGLE_APPLICATION_CREDENTIALS=$GOOGLE_APPLICATION_CREDENTIALS"
    else
        echo "# GOOGLE_APPLICATION_CREDENTIALS="
    fi
    echo "BUCKET_SUFFIX=$BUCKET_SUFFIX"
    echo "TEST_ENV=$TEST_ENV"
    echo "RUN_ENV=$RUN_ENV"
    echo "DATA_SIZE=$DATA_SIZE"
    if [ -n "$NOTIFY_BASE_URL" ]; then
        echo "NOTIFY_BASE_URL=$NOTIFY_BASE_URL"
    else
        echo "# NOTIFY_BASE_URL="
    fi
} > "$ENV_FILE"

echo "✅ .env créé."
