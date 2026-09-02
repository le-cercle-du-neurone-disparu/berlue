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
# Un seul format de poids par modèle. Les dépôts publient parfois `safetensors` ET
# `pytorch_model.bin` — 1,7 Go chacun pour le même modèle — mais pas toujours :
# `potsawee/deberta-v3-large-mnli` ne publie QUE le `.bin`. Écarter les `.bin` en
# aveugle le priverait donc de ses poids, et le service échouerait au démarrage
# (HF_HUB_OFFLINE=1). On regarde ce que le dépôt contient avant de choisir.
set -euo pipefail

BUCKET="${1:?usage: models_push.sh <bucket>}"
EMBEDDING="${2:?usage: models_push.sh <bucket> <modele-embedding>}"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

echo "⬇️  Constitution d'un cache HuggingFace minimal dans $STAGING ..."
HF_HOME="$STAGING" python - "$EMBEDDING" <<'PY'
import os
import pathlib
import shutil
import sys

from huggingface_hub import list_repo_files, snapshot_download
from selfcheckgpt.utils import NLIConfig

# Formats que le pipeline n'utilise jamais : TensorFlow, Flax, ONNX.
INUTILES = ["*.h5", "*.msgpack", "*.onnx", "*.ot"]

# Le nom du NLI vient du paquet selfcheckgpt : pas de valeur recopiée qui
# dériverait si le paquet change de modèle.
for repo in (f"sentence-transformers/{sys.argv[1]}", NLIConfig.nli_model):
    fichiers = list_repo_files(repo)
    ignore = list(INUTILES)
    # `.bin` écarté SEULEMENT si le dépôt publie aussi des safetensors : sinon
    # c'est le seul fichier de poids, et l'ignorer rendrait le modèle inutilisable.
    if any(f.endswith(".safetensors") for f in fichiers):
        ignore.append("*.bin")
        format_retenu = "safetensors"
    else:
        format_retenu = "pytorch_model.bin"
    print(f"   {repo}  ({format_retenu})")
    snapshot_download(repo_id=repo, ignore_patterns=ignore)

# Le cache HuggingFace range les poids dans `blobs/` (noms de hachage) et n'expose
# sous `snapshots/<rev>/<fichier>` que des LIENS SYMBOLIQUES. `gcloud storage rsync`
# les ignore : le bucket ne recevait que les blobs, sans l'arborescence qui permet
# de les résoudre — cache inutilisable, y compris pour un modèle pourtant présent.
#
# On matérialise donc chaque lien en vrai fichier, puis on supprime `blobs/` devenu
# redondant : même volume total, arborescence valide, et lisible en lecture seule.
racine = pathlib.Path(os.environ["HF_HOME"]) / "hub"
for lien in racine.rglob("*"):
    if lien.is_symlink():
        cible = lien.resolve()
        lien.unlink()
        shutil.copy2(cible, lien)
for blobs in racine.glob("*/blobs"):
    shutil.rmtree(blobs)
shutil.rmtree(racine / ".locks", ignore_errors=True)
PY

TAILLE=$(du -sh "$STAGING" | cut -f1)
echo "☁️  Publication vers gs://$BUCKET/ (${TAILLE}) ..."
gcloud storage rsync --recursive --delete-unmatched-destination-objects \
    "$STAGING" "gs://$BUCKET"

echo "✅ Modèles publiés : gs://$BUCKET/ (${TAILLE}, $(find "$STAGING" -type f | wc -l) fichiers)"
