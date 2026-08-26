import pytest
from httpx import AsyncClient

# TODO: Remplir ces paramètres avec des données factices correspondant aux schémas d'entrée de votre API
test_params = {}

# TODO: Définir la clé attendue retournée par votre endpoint /predict
EXPECTED_PREDICT_KEY = "prediction"


@pytest.mark.asyncio
async def test_root_is_up():
    from berlue.api.fast import app

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_root_returns_greeting():
    from berlue.api.fast import app

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/")
    assert response.json() == {"greeting": "Hello"}


# ==============================================================================
# TESTS DE L'ENDPOINT PREDICT
# ==============================================================================


@pytest.mark.asyncio
async def test_predict_is_up():
    # FAIL FAST : explose si l'utilisateur n'a pas rempli ses paramètres de test
    assert test_params, "❌ TODO: Vous devez définir 'test_params' pour lancer les tests de predict !"

    from berlue.api.fast import app

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/predict", params=test_params)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_predict_is_dict():
    assert test_params, "❌ TODO: Vous devez définir 'test_params' pour lancer les tests de predict !"

    from berlue.api.fast import app

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/predict", params=test_params)

    assert isinstance(response.json(), dict)


@pytest.mark.asyncio
async def test_predict_has_expected_key():
    assert test_params, "❌ TODO: Vous devez définir 'test_params' pour lancer les tests de predict !"

    from berlue.api.fast import app

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/predict", params=test_params)

    assert response.json().get(EXPECTED_PREDICT_KEY, False), f"Clé '{EXPECTED_PREDICT_KEY}' introuvable dans la réponse"


@pytest.mark.asyncio
async def test_predict_val_is_float():
    assert test_params, "❌ TODO: Vous devez définir 'test_params' pour lancer les tests de predict !"

    from berlue.api.fast import app

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/predict", params=test_params)

    assert isinstance(response.json().get(EXPECTED_PREDICT_KEY), float)
