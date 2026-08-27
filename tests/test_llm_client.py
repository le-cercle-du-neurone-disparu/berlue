"""Tests pour `berlue.llm.client.OllamaClient` — unitaires (client Ollama
interne mocké, pas de réseau) et fonctionnels (`@pytest.mark.functional`, vrai
serveur Ollama requis, cf. docs/ollama-setup.md)."""

import pytest
from httpx import TimeoutException
from ollama import ResponseError

from berlue.llm.client import OllamaClient
from berlue.params import OLLAMA_MODEL


class FakeInnerClient:
    """Remplace `ollama.Client` (l'attribut public `OllamaClient.client`) pour
    isoler nos tests du vrai SDK/serveur — enregistre les appels reçus pour
    vérifier ce qui a été demandé."""

    def __init__(self, response_text: str = "réponse test", raise_error: Exception | None = None):
        self.response_text = response_text
        self.raise_error = raise_error
        self.calls: list[dict] = []

    def generate(self, model: str, prompt: str, options: dict) -> dict:
        self.calls.append({"model": model, "prompt": prompt, "options": options})
        if self.raise_error:
            raise self.raise_error
        return {"response": self.response_text}


def make_client(response_text: str = "réponse test", raise_error: Exception | None = None) -> OllamaClient:
    client = OllamaClient(host="http://fake", model="fake-model")
    client.client = FakeInnerClient(response_text=response_text, raise_error=raise_error)
    return client


# ==============================================================================
# UNITAIRES — client Ollama interne mocké, aucun réseau
# ==============================================================================


def test_generate_returns_response_text():
    client = make_client(response_text="Paris est la capitale de la France.")

    result = client.generate(prompt="Quelle est la capitale de la France ?", temperature=0.5)

    assert result == "Paris est la capitale de la France."


def test_generate_passes_model_prompt_and_temperature():
    client = make_client()

    client.generate(prompt="Une question ?", temperature=0.42)

    call = client.client.calls[0]
    assert call == {"model": "fake-model", "prompt": "Une question ?", "options": {"temperature": 0.42}}


def test_generate_raises_timeout_error_on_httpx_timeout():
    client = make_client(raise_error=TimeoutException("trop long"))

    with pytest.raises(TimeoutError):
        client.generate(prompt="...")


def test_generate_raises_runtime_error_on_ollama_response_error():
    client = make_client(raise_error=ResponseError("modèle introuvable"))

    with pytest.raises(RuntimeError, match="Erreur interne Ollama"):
        client.generate(prompt="...")


def test_generate_raises_runtime_error_on_unexpected_exception():
    client = make_client(raise_error=ConnectionError("connexion refusée"))

    with pytest.raises(RuntimeError, match="Échec de la communication Ollama"):
        client.generate(prompt="...")


def test_generate_raises_runtime_error_on_empty_response():
    client = make_client(response_text="")

    with pytest.raises(RuntimeError, match="réponse vide"):
        client.generate(prompt="...")


def test_generate_many_returns_empty_list_for_non_positive_k():
    client = make_client()

    assert client.generate_many("...", k=0, temperature_min=0.1, temperature_max=0.9) == []
    assert client.generate_many("...", k=-1, temperature_min=0.1, temperature_max=0.9) == []


def test_generate_many_uses_midpoint_temperature_for_k_equals_1():
    client = make_client()

    client.generate_many("...", k=1, temperature_min=0.2, temperature_max=0.8)

    assert client.client.calls[0]["options"] == {"temperature": 0.5}


def test_generate_many_distributes_temperatures_evenly():
    client = make_client()

    client.generate_many("...", k=3, temperature_min=0.2, temperature_max=0.8)

    temperatures = [call["options"]["temperature"] for call in client.client.calls]
    assert temperatures == pytest.approx([0.2, 0.5, 0.8])


def test_generate_many_returns_one_response_per_call():
    client = make_client(response_text="réponse")

    results = client.generate_many("...", k=3, temperature_min=0.0, temperature_max=1.0)

    assert results == ["réponse", "réponse", "réponse"]


# ==============================================================================
# FONCTIONNELS — vrai serveur Ollama requis (make ollama_setup / ollama serve)
# ==============================================================================


@pytest.mark.functional
def test_generate_returns_a_real_answer_from_ollama():
    client = OllamaClient(model=OLLAMA_MODEL)

    result = client.generate(prompt="Réponds uniquement par le mot 'ok'.", temperature=0.0)

    assert isinstance(result, str)
    assert result.strip() != ""


@pytest.mark.functional
def test_generate_many_returns_k_real_answers_from_ollama():
    client = OllamaClient(model=OLLAMA_MODEL)

    results = client.generate_many("Réponds uniquement par le mot 'ok'.", k=2, temperature_min=0.3, temperature_max=0.9)

    assert len(results) == 2
    assert all(isinstance(r, str) and r.strip() for r in results)
