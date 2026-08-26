import httpx
import pytest


@pytest.mark.asyncio
async def test_root_is_up():
    from berlue.api.fast import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_root_returns_greeting():
    from berlue.api.fast import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/")
    assert response.json() == {"greeting": "Hello from Berlue API"}


@pytest.mark.asyncio
async def test_favicon_returns_204():
    from berlue.api.fast import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/favicon.ico")
    assert response.status_code == 204
