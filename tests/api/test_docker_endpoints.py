import os
import re
import subprocess

import pytest
from httpx import AsyncClient

# TODO: Remplir ces paramètres avec des données factices correspondant au schéma d'entrée de votre API
test_params = {}

# TODO: Définir la clé attendue retournée par votre endpoint /predict
EXPECTED_PREDICT_KEY = "prediction"

# Trouve le port sur lequel tourne l'image docker
image_name = f"{os.environ.get('GAR_IMAGE')}:dev"

# Utilise docker ps pour lister tous les conteneurs en cours dérivés de $GAR_IMAGE:dev
docker_ps_command = f'docker ps --filter ancestor={image_name} --format "{{{{.Ports}}}}"'
docker_ps_output = subprocess.Popen(docker_ps_command, shell=True, stdout=subprocess.PIPE).stdout.read().decode("utf-8")

# Si on a une sortie, on extrait le port sur lequel tourne le conteneur
if docker_ps_output:
    # Cherche le port mappé (ex. 0.0.0.0:8000->8000/tcp)
    match = re.findall(r":(\d{4,5})->", docker_ps_output)
    docker_port = match[0] if match else None
else:
    docker_port = None

SERVICE_URL = f"http://localhost:{docker_port}" if docker_port else None

ERROR_DOCKER_PORT = f"""
❌ ERREUR : Aucun conteneur docker en cours d'exécution trouvé pour '{image_name}'.
Vérifiez :
  1. Que votre conteneur docker est lancé (ex. make docker_run_local)
  2. Que l'image docker est correctement nommée avec $GAR_IMAGE:dev
"""

ERROR_PARAMS = "❌ TODO: Vous devez définir 'test_params' pour lancer les tests de predict !"


@pytest.mark.asyncio
async def test_root_is_up():
    assert docker_port, ERROR_DOCKER_PORT
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_root_returns_greeting():
    assert docker_port, ERROR_DOCKER_PORT
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/")
    assert response.json() == {"greeting": "Hello"}


@pytest.mark.asyncio
async def test_predict_is_up():
    assert docker_port, ERROR_DOCKER_PORT
    assert test_params, ERROR_PARAMS
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/predict", params=test_params)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_predict_is_dict():
    assert docker_port, ERROR_DOCKER_PORT
    assert test_params, ERROR_PARAMS
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/predict", params=test_params)
    assert isinstance(response.json(), dict)


@pytest.mark.asyncio
async def test_predict_has_key():
    assert docker_port, ERROR_DOCKER_PORT
    assert test_params, ERROR_PARAMS
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/predict", params=test_params)
    assert response.json().get(EXPECTED_PREDICT_KEY, False), f"Clé '{EXPECTED_PREDICT_KEY}' introuvable dans la réponse"


@pytest.mark.asyncio
async def test_docker_api_predict_val_is_float():
    assert docker_port, ERROR_DOCKER_PORT
    assert test_params, ERROR_PARAMS
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/predict", params=test_params)
    assert isinstance(response.json().get(EXPECTED_PREDICT_KEY), float)
