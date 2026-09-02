"""Tests pour `berlue.llm.client.OllamaClient` — unitaires (client Ollama
interne mocké, pas de réseau) et fonctionnels (`@pytest.mark.functional`, vrai
serveur Ollama requis, cf. docs/setup/ollama-setup.md)."""

import logging

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


def test_warmup_calls_generate_once():
    client = make_client(response_text="ok")

    client.warmup()

    assert len(client.client.calls) == 1


def test_warmup_returns_a_non_negative_elapsed_time():
    client = make_client(response_text="ok")

    elapsed = client.warmup()

    assert isinstance(elapsed, float)
    assert elapsed >= 0.0


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


def test_la_temperature_du_constructeur_est_utilisee(monkeypatch):
    """`OllamaClient(temperature=...)` doit s'appliquer aux appels qui n'en
    passent pas : c'est par là que l'API transmettait la température du payload,
    et elle était silencieusement ignorée."""
    vues = []

    class FakeClient:
        def generate(self, model, prompt, options):
            vues.append(options["temperature"])
            return {"response": "ok"}

    client = OllamaClient(temperature=0.7)
    monkeypatch.setattr(client, "client", FakeClient())

    client.generate("q")
    client.generate("q", temperature=0.1)

    assert vues == [0.7, 0.1], "défaut = celle du client, valeur explicite = prioritaire"


def test_une_generation_tronquee_est_signalee(monkeypatch, caplog):
    """`num_predict` coupe silencieusement : un JSON amputé ne parse pas et dégénère
    en résultat vide en aval. La troncature doit être visible dans les logs."""

    class FakeClient:
        def generate(self, model, prompt, options):
            return {"response": "texte coupé", "done_reason": "length"}

    client = OllamaClient()
    monkeypatch.setattr(client, "client", FakeClient())

    with caplog.at_level(logging.WARNING):
        client.generate("q", num_predict=12)

    assert any("tronquée" in r.message for r in caplog.records)


def test_une_generation_complete_ne_declenche_aucun_avertissement(monkeypatch, caplog):
    class FakeClient:
        def generate(self, model, prompt, options):
            return {"response": "texte complet", "done_reason": "stop"}

    client = OllamaClient()
    monkeypatch.setattr(client, "client", FakeClient())

    with caplog.at_level(logging.WARNING):
        client.generate("q", num_predict=300)

    assert not [r for r in caplog.records if "tronquée" in r.message]


def test_le_client_est_reconstruit_quand_le_jeton_a_expire():
    """Un jeton d'identité Cloud Run ne vit qu'une heure. Figé à la construction,
    il condamnait les clients de longue vie — l'extracteur et le client RAG,
    créés au démarrage du service, tombaient en Unauthorized au bout d'une heure.
    L'accès au client doit donc renouveler le jeton dès qu'il n'est plus valide.
    """

    class FauxIdentifiants:
        def __init__(self):
            self.valid = False
            self.token = "jeton-frais"
            self.refresh_count = 0

        def refresh(self, _requete):
            self.refresh_count += 1
            self.valid = True

    client = OllamaClient(host="https://berlue-llm.example.run.app")
    identifiants = FauxIdentifiants()
    client._credentials = identifiants
    client._client = None

    premier = client.client
    assert identifiants.refresh_count == 1

    # Tant que le jeton reste valide, aucun renouvellement ni reconstruction.
    assert client.client is premier
    assert identifiants.refresh_count == 1

    # Jeton expiré : renouvellement et nouveau client porteur du nouvel en-tête.
    identifiants.valid = False
    second = client.client
    assert identifiants.refresh_count == 2
    assert second is not premier
