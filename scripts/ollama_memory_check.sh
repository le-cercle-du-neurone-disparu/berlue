#!/usr/bin/env bash
# scripts/ollama_memory_check.sh
#
# Vérifie qu'un modèle chargé sur berlue-llm tient dans la mémoire du conteneur
# Cloud Run, et échoue sinon.
#
# Pourquoi : `gcloud run deploy` accepte n'importe quel couple modèle/mémoire, et
# l'insuffisance ne se manifeste qu'à l'inférence, par un llama-server tué et un
# message qui ne nomme jamais la mémoire ("model runner has unexpectedly
# stopped"). Constaté en conditions réelles avec qwen2.5:14b (12 Go) sur un
# conteneur à 16 Gi : trois runs d'évaluation perdus avant d'identifier la cause.
#
# Le seuil est un facteur 2 sur la taille du modèle, pas une marge fixe : Cloud
# Run compte dans la limite mémoire le cache de pages du fichier de modèle lu
# depuis le disque, en plus du modèle chargé — le besoin effectif est de l'ordre
# du double des poids. Heuristique calée sur les deux seuls points mesurés :
# qwen2.5:14b (11 Gi) tué à 16 Gi, le même passant à 32 Gi.
#
# Usage : scripts/ollama_memory_check.sh <url> <token> <mémoire, ex. 32Gi> <modèle>

set -uo pipefail

if [ "$#" -ne 4 ]; then
    echo "Usage : $0 <url> <token> <mémoire> <modèle>" >&2
    exit 2
fi

url="$1"
token="$2"
memory="$3"
model="$4"

# Mémoire exigée = facteur × taille du modèle.
memory_factor=2

memory_gib=$(printf '%s' "$memory" | sed -E 's/[Gg]i?[Bb]?$//')
case "$memory_gib" in
    ''|*[!0-9]*)
        echo "⚠️  Mémoire illisible ($memory) — vérification sautée." >&2
        exit 0
        ;;
esac

model_bytes=$(curl -sf "${url}/api/ps" -H "Authorization: Bearer ${token}" 2>/dev/null \
    | MODEL="$model" python3 -c '
import json, os, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit()
for m in data.get("models", []):
    if m.get("name") == os.environ["MODEL"] or m.get("model") == os.environ["MODEL"]:
        print(m.get("size", 0))
        break
')

if [ -z "$model_bytes" ] || [ "$model_bytes" -eq 0 ] 2>/dev/null; then
    echo "⚠️  Taille de $model introuvable via /api/ps — vérification sautée." >&2
    exit 0
fi

model_gib=$((model_bytes / 1073741824))

required_gib=$((model_gib * memory_factor))

if [ "$required_gib" -gt "$memory_gib" ]; then
    cat >&2 <<MSG
❌ $model occupe ${model_gib} Gi, le conteneur n'en a que ${memory_gib} Gi.
   Il en faut au moins ${required_gib} Gi : le cache de pages du fichier de modèle
   compte dans la limite Cloud Run, en plus du modèle chargé.
   Sans ça, llama-server est tué en pleine inférence, sans message qui le dise.
   👉 make cloudrun_llm_deploy LLM_CPU=8 LLM_MEMORY=${required_gib}Gi
MSG
    exit 1
fi

echo "✅ $model (${model_gib} Gi) tient dans les ${memory_gib} Gi du conteneur."
