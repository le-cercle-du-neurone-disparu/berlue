import os
import re
import subprocess

import pytest
from httpx import AsyncClient

# TODO: Fill these parameters with dummy data matching your API input schema
test_params = {}

# TODO: Define the expected key returned by your /predict endpoint
EXPECTED_PREDICT_KEY = "prediction"

# Find the port the docker image is running on
image_name = f"{os.environ.get('GAR_IMAGE')}:dev"

# Use docker ps to list all running containers derived from $GAR_IMAGE:dev
docker_ps_command = f'docker ps --filter ancestor={image_name} --format "{{{{.Ports}}}}"'
docker_ps_output = subprocess.Popen(
    docker_ps_command,
    shell=True,
    stdout=subprocess.PIPE
).stdout.read().decode("utf-8")

# If we have an output, extract the port the container is running on
if docker_ps_output:
    # Match the mapped port (e.g., 0.0.0.0:8000->8000/tcp)
    match = re.findall(r":(\d{4,5})->", docker_ps_output)
    docker_port = match[0] if match else None
else:
    docker_port = None

SERVICE_URL = f"http://localhost:{docker_port}" if docker_port else None

ERROR_DOCKER_PORT = f"""
❌ ERROR: We did not find a running docker container for '{image_name}'.
Verify:
  1. Your docker container is running (e.g., make docker_run_local)
  2. The docker image is correctly named using $GAR_IMAGE:dev
"""

ERROR_PARAMS = "❌ TODO: You must define 'test_params' to run predict tests!"


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
    assert response.json().get(EXPECTED_PREDICT_KEY, False), f"Key '{EXPECTED_PREDICT_KEY}' not found in response"


@pytest.mark.asyncio
async def test_docker_api_predict_val_is_float():
    assert docker_port, ERROR_DOCKER_PORT
    assert test_params, ERROR_PARAMS
    async with AsyncClient(base_url=SERVICE_URL, timeout=10.0) as ac:
        response = await ac.get("/predict", params=test_params)
    assert isinstance(response.json().get(EXPECTED_PREDICT_KEY), float)
