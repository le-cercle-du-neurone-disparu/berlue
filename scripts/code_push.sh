#!/usr/bin/env bash
# Publie le code de l'application dans le bucket de code, sous la version
# demandée — c'est ce que les conteneurs `berlue-runtime` copieront au
# démarrage (cf. docker/entrypoint.sh).
#
#   scripts/code_push.sh <bucket> <version>
#
# Ce qui part dans le bucket, et rien d'autre :
#   berlue/                         le package (~1 Mo)
#   models/nli_tfidf_logreg.joblib  la baseline NLI, si entraînée
#   data/halueval/ data/truthfulqa/ les jeux labellisés (~6 Mo)
#
# Les jeux de données accompagnent le code parce que `params.py` les référence
# par chemin relatif et que `berlue.evaluation.data` les téléchargerait sinon
# à chaque démarrage à froid. `data/fever/` en est exclu : 371 Mo, et l'index
# FAISS a déjà son propre bucket (RAG_BUCKET_NAME).
set -euo pipefail

BUCKET="${1:?usage: code_push.sh <bucket> <version>}"
VERSION="${2:?usage: code_push.sh <bucket> <version>}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

# rsync depuis une copie propre plutôt que depuis le dépôt : c'est le seul
# moyen de garantir que le bucket ne contient que la liste ci-dessus, et que
# `--delete-unmatched-destination-objects` supprime bien ce qui a disparu du
# code sans risquer d'emporter autre chose.
mkdir -p "$STAGING/berlue"
rsync -a --exclude='__pycache__' --exclude='*.pyc' berlue/ "$STAGING/berlue/"

if [ -f models/nli_tfidf_logreg.joblib ]; then
    mkdir -p "$STAGING/models"
    cp models/nli_tfidf_logreg.joblib "$STAGING/models/"
else
    echo "⚠️  models/nli_tfidf_logreg.joblib absent — la baseline NLI ne sera pas"
    echo "    disponible côté GCP (make train_baseline pour l'entraîner)."
fi

for DATASET in halueval truthfulqa; do
    if [ -d "data/$DATASET" ]; then
        mkdir -p "$STAGING/data/$DATASET"
        rsync -a "data/$DATASET/" "$STAGING/data/$DATASET/"
    else
        echo "⚠️  data/$DATASET absent — sera téléchargé au démarrage du conteneur."
    fi
done

echo "☁️  Publication vers gs://$BUCKET/$VERSION/ ..."
gcloud storage rsync --recursive --delete-unmatched-destination-objects \
    "$STAGING" "gs://$BUCKET/$VERSION"

echo "✅ Code publié : gs://$BUCKET/$VERSION/ ($(find "$STAGING" -type f | wc -l) fichiers)"
