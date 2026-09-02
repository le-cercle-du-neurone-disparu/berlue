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
