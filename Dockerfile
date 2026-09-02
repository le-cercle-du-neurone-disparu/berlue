# Image d'exécution unique des deux services applicatifs Berlue : l'API
# (`berlue.api.fast:app`) et le service d'éval (`berlue.api.eval_service:app`)
# ne différaient que par le module servi — un seul jeu de dépendances, une
# seule image, le module choisi par BERLUE_APP_MODULE au déploiement.
#
# Elle ne contient PAS le code de `berlue/` : il arrive au démarrage du bucket
# de code monté en volume (cf. docker/entrypoint.sh, make/code.mk). Le code
# pèse 1 Mo, les dépendances ~6,5 Go — les enfermer dans la même image
# imposait un build + push complet à chaque ligne de Python changée.
ARG DOCKER_BASE_IMAGE=python:3.10.6-slim
FROM ${DOCKER_BASE_IMAGE}

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Précharge les poids des deux modèles du pipeline. Sans ça, ils sont téléchargés
# au premier usage réel — `RagRetriever.__init__` construit le SentenceTransformer,
# le singleton de `selfcheck/scorer.py` instancie SelfCheckNLI — donc en plein
# milieu d'une requête déjà longue, et de nouveau après chaque scale-to-zero.
#
# Le nom du NLI vient du paquet `selfcheckgpt`, présent dans l'image. Celui de
# l'embedding vient de `berlue/params.py`, qui n'y est PAS (le code arrive du
# bucket au démarrage) : il est donc passé en build-arg par `make docker_build_prod`,
# qui le lit depuis params.py. La valeur ci-dessous n'est qu'un repli pour un
# `docker build` lancé à la main.
ARG RAG_EMBEDDING_MODEL=all-mpnet-base-v2
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
from selfcheckgpt.utils import NLIConfig; \
from transformers import DebertaV2ForSequenceClassification, DebertaV2Tokenizer; \
SentenceTransformer('${RAG_EMBEDDING_MODEL}'); \
DebertaV2Tokenizer.from_pretrained(NLIConfig.nli_model); \
DebertaV2ForSequenceClassification.from_pretrained(NLIConfig.nli_model)"

COPY docker/entrypoint.sh /usr/local/bin/berlue-entrypoint
RUN chmod +x /usr/local/bin/berlue-entrypoint

# Le package n'est pas installé (pas de `pip install .`, il n'est pas là au
# build) : il est importé depuis /app, où l'entrypoint dépose le code.
ENV PYTHONPATH=/app
# Sortie non bufferisée — sinon les marqueurs horodatés de
# `berlue.evaluation.timing` n'apparaissent dans les logs Cloud Run qu'à
# l'extinction du conteneur.
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/usr/local/bin/berlue-entrypoint"]
