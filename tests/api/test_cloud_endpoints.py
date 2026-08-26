import os

import pytest
from httpx import AsyncClient

# TODO: Remplir ces paramètres avec des données factices correspondant au schéma d'entrée de votre API
test_params = {}

# TODO: Définir la clé attendue retournée par votre endpoint /predict
EXPECTED_PREDICT_KEY = "prediction"

SERVICE_URL = os.environ.get("SERVICE_URL")


@pytest.mark.asyncio
async def test_root_is_up():
    assert SERVICE_URL, "❌ SERVICE_URL n'est pas défini dans les variables d'environnement."
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_root_returns_greeting():
    assert SERVICE_URL, "❌ SERVICE_URL n'est pas défini dans les variables d'environnement."
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/")
    assert response.json() == {"greeting": "Hello"}


@pytest.mark.asyncio
async def test_predict_is_up():
    assert SERVICE_URL, "❌ SERVICE_URL n'est pas défini dans les variables d'environnement."
    assert test_params, "❌ TODO: Vous devez définir 'test_params' pour lancer les tests de predict !"
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/predict", params=test_params)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_predict_is_dict():
    assert SERVICE_URL, "❌ SERVICE_URL n'est pas défini dans les variables d'environnement."
    assert test_params, "❌ TODO: Vous devez définir 'test_params' pour lancer les tests de predict !"
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/predict", params=test_params)
    assert isinstance(response.json(), dict)


@pytest.mark.asyncio
async def test_predict_has_key():
    assert SERVICE_URL, "❌ SERVICE_URL n'est pas défini dans les variables d'environnement."
    assert test_params, "❌ TODO: Vous devez définir 'test_params' pour lancer les tests de predict !"
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/predict", params=test_params)
    assert response.json().get(EXPECTED_PREDICT_KEY, False), f"Clé '{EXPECTED_PREDICT_KEY}' introuvable dans la réponse"


@pytest.mark.asyncio
async def test_cloud_api_predict_val_is_float():
    assert SERVICE_URL, "❌ SERVICE_URL n'est pas défini dans les variables d'environnement."
    assert test_params, "❌ TODO: Vous devez définir 'test_params' pour lancer les tests de predict !"
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/predict", params=test_params)
    assert isinstance(response.json().get(EXPECTED_PREDICT_KEY), float)
