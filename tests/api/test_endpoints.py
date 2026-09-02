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
    body = response.json()
    assert body["greeting"] == "Hello from Berlue API"
    # Chaque étage doit être nommé : c'est la seule façon de savoir, face à une
    # instance déployée, quel modèle a produit un verdict donné.
    assert set(body["models"]) == {
        "generation",
        "extraction",
        "rag",
        "judge",
        # Deux modèles NLI distincts : celui qui juge la cohérence à chaque
        # requête, et la ligne de base qui ne sert qu'à l'évaluation. Les
        # confondre a déjà fait annoncer le mauvais modèle.
        "selfcheck_nli",
        "nli_baseline",
        "embeddings",
    }
    assert all(body["models"].values())
    # Un index réduit et l'index complet se déploient de la même façon : sans
    # cette information, un « rien trouvé » est ininterprétable.
    assert "rag_index" in body
    assert "path" in body["rag_index"]
    # Ce qu'Ollama a sur disque, et ce qu'il tient en mémoire — la sonde ne doit
    # pas échouer si le serveur est injoignable, mais elle doit le dire.
    assert "llm" in body
    assert "available" in body["llm"] or "erreur" in body["llm"]


@pytest.mark.asyncio
async def test_favicon_returns_204():
    from berlue.api.fast import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/favicon.ico")
    assert response.status_code == 204
