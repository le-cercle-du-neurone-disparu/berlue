#!/bin/sh
# Point d'entrée unique des services applicatifs Berlue (API et éval, cf.
# BERLUE_APP_MODULE) — l'image `berlue-runtime` ne contient QUE les
# dépendances, jamais le code : celui-ci arrive du bucket de code monté en
# volume GCS FUSE (cf. make/code.mk, docs/gcp/code-en-bucket.md).
set -e

APP_DIR=/app
CODE_DIR=${BERLUE_CODE_DIR:-/mnt/code/current}
APP_MODULE=${BERLUE_APP_MODULE:-berlue.api.fast:app}
PORT=${PORT:-8080}

if [ -d "$APP_DIR/berlue" ]; then
    # Développement local : le code est bind-monté directement dans $APP_DIR
    # (docker-compose, docker_run_local). Même image qu'en production, on ne
    # va simplement pas chercher le bucket.
    echo "📂 Code déjà présent dans $APP_DIR (montage local) — copie sautée."
elif [ -d "$CODE_DIR/berlue" ]; then
    # Copie plutôt qu'import direct depuis $CODE_DIR : les imports ne paient
    # pas la latence GCS FUSE fichier par fichier, $APP_DIR reste inscriptible,
    # et les chemins relatifs codés en dur dans params.py (data/..., ./models/...)
    # résolvent depuis un WORKDIR qui contient le code, comme avant.
    echo "📥 Copie du code depuis $CODE_DIR vers $APP_DIR..."
    cp -a "$CODE_DIR/." "$APP_DIR/"
    echo "✅ Code en place ($(find "$APP_DIR/berlue" -name '*.py' | wc -l) fichiers Python)."
else
    echo "❌ Aucun code trouvé : ni $APP_DIR/berlue, ni $CODE_DIR/berlue."
    echo "   Le bucket de code est-il monté sur /mnt/code, et BERLUE_CODE_DIR"
    echo "   ($CODE_DIR) pointe-t-il sur une version poussée ? → make code_push"
    exit 1
fi

cd "$APP_DIR"
echo "🚀 uvicorn $APP_MODULE sur le port $PORT"
exec uvicorn "$APP_MODULE" --host 0.0.0.0 --port "$PORT"
