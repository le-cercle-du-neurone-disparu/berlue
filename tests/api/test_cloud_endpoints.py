import os

import pytest
from httpx import AsyncClient

# TODO: Fill these parameters with dummy data matching your API input schema
test_params = {}

# TODO: Define the expected key returned by your /predict endpoint
EXPECTED_PREDICT_KEY = "prediction"

SERVICE_URL = os.environ.get("SERVICE_URL")


@pytest.mark.asyncio
async def test_root_is_up():
    assert SERVICE_URL, "❌ SERVICE_URL is not set in environment variables."
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_root_returns_greeting():
    assert SERVICE_URL, "❌ SERVICE_URL is not set in environment variables."
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/")
    assert response.json() == {"greeting": "Hello"}


@pytest.mark.asyncio
async def test_predict_is_up():
    assert SERVICE_URL, "❌ SERVICE_URL is not set in environment variables."
    assert test_params, "❌ TODO: You must define 'test_params' to run predict tests!"
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/predict", params=test_params)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_predict_is_dict():
    assert SERVICE_URL, "❌ SERVICE_URL is not set in environment variables."
    assert test_params, "❌ TODO: You must define 'test_params' to run predict tests!"
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/predict", params=test_params)
    assert isinstance(response.json(), dict)


@pytest.mark.asyncio
async def test_predict_has_key():
    assert SERVICE_URL, "❌ SERVICE_URL is not set in environment variables."
    assert test_params, "❌ TODO: You must define 'test_params' to run predict tests!"
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/predict", params=test_params)
    assert response.json().get(EXPECTED_PREDICT_KEY, False), f"Key '{EXPECTED_PREDICT_KEY}' not found in response"


@pytest.mark.asyncio
async def test_cloud_api_predict_val_is_float():
    assert SERVICE_URL, "❌ SERVICE_URL is not set in environment variables."
    assert test_params, "❌ TODO: You must define 'test_params' to run predict tests!"
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/predict", params=test_params)
    assert isinstance(response.json().get(EXPECTED_PREDICT_KEY), float)
