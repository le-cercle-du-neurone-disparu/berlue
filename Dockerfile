# 1. Récupère l'image de base dynamiquement (passée par le Makefile)
ARG DOCKER_BASE_IMAGE=python:3.10.6-slim
FROM ${DOCKER_BASE_IMAGE}

WORKDIR /api

# 2. Installe les dépendances (production uniquement !)
COPY requirements.txt requirements.txt
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# 3. Copie le code source et installe le package
COPY berlue berlue
COPY setup.py setup.py

# Optionnel : décommenter si vous avez des modèles figés stockés localement
# COPY models models

# 4. Astuce production : installe le package sans les dépendances [dev] !
RUN pip install . && rm -rf build *.egg-info

# 5. Démarre l'API (utilise exec pour bien gérer les signaux comme CTRL+C)
CMD ["sh", "-c", "exec uvicorn berlue.api.fast:app --host 0.0.0.0 --port $PORT"]
