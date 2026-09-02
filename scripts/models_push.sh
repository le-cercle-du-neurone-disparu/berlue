#!/usr/bin/env bash
# Publie les poids des modèles HuggingFace du pipeline dans le bucket de
# modèles — c'est ce que les conteneurs `berlue-runtime` monteront en volume
# GCS FUSE comme cache HuggingFace (HF_HOME), au lieu de les télécharger au
# premier usage réel.
#
#   scripts/models_push.sh <bucket>
#
# Deux modèles, chargés paresseusement par le code :
#   sentence-transformers/<embedding>      RagRetriever.__init__      ~0,4 Go
#   potsawee/deberta-v3-large-mnli         selfcheck/scorer.py        ~1,7 Go
#
# Seuls les poids `safetensors` sont récupérés : le dépôt du NLI contient AUSSI
# `pytorch_model.bin`, 1,7 Go pour exactement le même modèle, que transformers
# n'utilise pas quand safetensors est présent. Les ignorer divise la taille
# poussée par près de deux.
set -euo pipefail

BUCKET="${1:?usage: models_push.sh <bucket>}"
EMBEDDING="${2:?usage: models_push.sh <bucket> <modele-embedding>}"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

echo "⬇️  Constitution d'un cache HuggingFace minimal dans $STAGING ..."
HF_HOME="$STAGING" python - "$EMBEDDING" <<'PY'
import sys
from huggingface_hub import snapshot_download
from selfcheckgpt.utils import NLIConfig

# Le nom du NLI vient du paquet selfcheckgpt : pas de valeur recopiée qui
# dériverait si le paquet change de modèle.
IGNORE = ["*.bin", "*.h5", "*.msgpack", "*.onnx", "*.ot"]
for repo in (f"sentence-transformers/{sys.argv[1]}", NLIConfig.nli_model):
    print(f"   {repo}")
    snapshot_download(repo_id=repo, ignore_patterns=IGNORE)
PY

TAILLE=$(du -sh "$STAGING" | cut -f1)
echo "☁️  Publication vers gs://$BUCKET/ (${TAILLE}) ..."
gcloud storage rsync --recursive --delete-unmatched-destination-objects \
    "$STAGING" "gs://$BUCKET"

echo "✅ Modèles publiés : gs://$BUCKET/ (${TAILLE}, $(find "$STAGING" -type f | wc -l) fichiers)"
