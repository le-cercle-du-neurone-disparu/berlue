import pytest
from httpx import AsyncClient

# TODO: Fill these parameters with dummy data matching your API input schemas
test_params = {}

# TODO: Define the expected key returned by your /predict endpoint
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
# PREDICT ENDPOINT TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_predict_is_up():
    # FAIL FAST : Explose si l'utilisateur n'a pas rempli ses paramètres de test
    assert test_params, "❌ TODO: You must define 'test_params' to run predict tests!"

    from berlue.api.fast import app

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/predict", params=test_params)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_predict_is_dict():
    assert test_params, "❌ TODO: You must define 'test_params' to run predict tests!"

    from berlue.api.fast import app

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/predict", params=test_params)

    assert isinstance(response.json(), dict)


@pytest.mark.asyncio
async def test_predict_has_expected_key():
    assert test_params, "❌ TODO: You must define 'test_params' to run predict tests!"

    from berlue.api.fast import app

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/predict", params=test_params)

    assert response.json().get(EXPECTED_PREDICT_KEY, False), f"Key '{EXPECTED_PREDICT_KEY}' not found in response"


@pytest.mark.asyncio
async def test_predict_val_is_float():
    assert test_params, "❌ TODO: You must define 'test_params' to run predict tests!"

    from berlue.api.fast import app

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/predict", params=test_params)

    assert isinstance(response.json().get(EXPECTED_PREDICT_KEY), float)
