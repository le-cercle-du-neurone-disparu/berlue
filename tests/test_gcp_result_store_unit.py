"""Tests unitaires purs pour `berlue.evaluation.gcp_result_store` — aucune
infra GCP requise (contrairement à `test_gcp_result_store.py`, `functional`).
Couvre la sélection de la source du jeton d'accès (local vs Cloud Run) et la
sécurité thread du registre de scopes bufferisé, cf. docstring du module."""

import threading
from datetime import datetime

import pytest

from berlue.evaluation import gcp_result_store as gcp

# Échéance arbitraire mais fixe, en UTC naïf comme le fait google-auth.
_EXPIRY = datetime(2030, 1, 1, 12, 0, 0)


def test_running_on_cloud_run_false_by_default(monkeypatch):
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
    assert gcp._running_on_cloud_run() is False


def test_running_on_cloud_run_true_for_service(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "berlue-api-test")
    monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
    assert gcp._running_on_cloud_run() is True


def test_running_on_cloud_run_true_for_job(monkeypatch):
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setenv("CLOUD_RUN_JOB", "berlue-eval")
    assert gcp._running_on_cloud_run() is True


class _FakeAdcCredentials:
    """Simule des credentials `google.auth.default()` — `refresh()` pose
    `token` et `expiry`, comme le fait la vraie lib (`expiry` en UTC naïf)."""

    def __init__(self, expiry=None):
        self.token = None
        self.expiry = expiry

    def refresh(self, request):
        self.token = "fake-adc-token"


def test_access_token_uses_adc_on_cloud_run(monkeypatch):
    """Sur Cloud Run, pas d'appel à `gcloud` — jeton via `google.auth.default()`,
    déjà `sa-berlue` via l'identité attachée au service/job."""
    monkeypatch.setenv("K_SERVICE", "berlue-api-test")
    fake_credentials = _FakeAdcCredentials(expiry=_EXPIRY)
    monkeypatch.setattr(gcp.google.auth, "default", lambda: (fake_credentials, "some-project"))

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("gcloud CLI ne doit jamais être appelé en exécution Cloud Run")

    monkeypatch.setattr(gcp.subprocess, "check_output", _fail_if_called)

    token, expiry = gcp._access_token()
    assert token == "fake-adc-token"
    assert expiry == _EXPIRY


def test_access_token_falls_back_when_adc_publishes_no_expiry(monkeypatch):
    """`credentials.expiry` à None (source qui ne publie pas d'échéance) : on
    retombe sur une durée supposée, jamais sur une échéance nulle qui ferait
    renouveler le jeton à chaque requête."""
    monkeypatch.setenv("K_SERVICE", "berlue-api-test")
    monkeypatch.setattr(gcp.google.auth, "default", lambda: (_FakeAdcCredentials(expiry=None), "some-project"))

    before = datetime.utcnow()
    _, expiry = gcp._access_token()
    assert before + gcp._TOKEN_ASSUMED_LIFETIME <= expiry <= datetime.utcnow() + gcp._TOKEN_ASSUMED_LIFETIME


def test_access_token_uses_gcloud_cli_locally(monkeypatch):
    """En local (ni K_SERVICE ni CLOUD_RUN_JOB), impersonation via la
    session `gcloud` CLI."""
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
    monkeypatch.setattr(gcp, "EVAL_SERVICE_ACCOUNT", "sa-berlue@some-project.iam.gserviceaccount.com")

    captured = {}

    def _fake_check_output(cmd, text=True):
        captured["cmd"] = cmd
        return "fake-cli-token\n"

    monkeypatch.setattr(gcp.subprocess, "check_output", _fake_check_output)

    token, expiry = gcp._access_token()
    assert token == "fake-cli-token"
    # La CLI ne publie pas d'échéance : durée supposée.
    assert expiry <= datetime.utcnow() + gcp._TOKEN_ASSUMED_LIFETIME
    assert captured["cmd"] == [
        "gcloud",
        "auth",
        "print-access-token",
        "--impersonate-service-account",
        "sa-berlue@some-project.iam.gserviceaccount.com",
    ]


def test_access_token_raises_without_service_account_locally(monkeypatch):
    """Pas de repli silencieux sur la session humaine si EVAL_SERVICE_ACCOUNT
    n'a pas pu être résolu (GCP_PROJECT absent) — erreur explicite."""
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
    monkeypatch.setattr(gcp, "EVAL_SERVICE_ACCOUNT", None)

    with pytest.raises(RuntimeError, match="EVAL_SERVICE_ACCOUNT"):
        gcp._access_token()


class _FakeFirestore:
    """Piste les incréments reçus (sous verrou — seul le comportement de
    `GcpResultStore` sous test, pas ce double)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.increments: dict[str, int] = {}

    def create(self, collection, doc_id, fields):
        pass

    def increment(self, collection, doc_id, field, count):
        with self._lock:
            self.increments[doc_id] = self.increments.get(doc_id, 0) + count


def _bare_gcp_store() -> gcp.GcpResultStore:
    """Instance sans passer par `__init__` (évite `bigquery.Client()`/
    `_ensure_bq_tables()`, appels réseau) — ne construit que l'état touché
    par `_register_new_row`/`flush_registry`, sous test ici."""
    store = gcp.GcpResultStore.__new__(gcp.GcpResultStore)
    store.fs = _FakeFirestore()
    store._registry_buffer = {}
    store._registry_lock = threading.Lock()
    return store


def test_register_new_row_thread_safe_under_concurrency():
    """`_registry_buffer` est muté par tous les workers d'un
    `evaluate_model_generated(..., concurrency=N)` — un appel concurrent sans
    verrou lève `RuntimeError: dictionary changed size during iteration` dès
    qu'un flush (déclenché par un thread) itère le buffer pendant qu'un autre
    l'incrémente (cas réel observé en conditions réelles sur GCP)."""
    store = _bare_gcp_store()
    n_threads, n_rows_per_thread = 16, 50

    def worker():
        for _ in range(n_rows_per_thread):
            store._register_new_row("llm_answers", {"model_id": "m", "generation_version": "v1"})

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    store.flush_registry()

    total = sum(store.fs.increments.values()) + sum(store._registry_buffer.values())
    assert total == n_threads * n_rows_per_thread


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


def test_firestore_request_retries_once_with_a_fresh_token_on_401(monkeypatch):
    """Un 401 ne doit pas interrompre l'appelant : l'échéance calculée reste une
    prévision (jeton révoqué, horloge décalée, jeton mutualisé déjà entamé côté
    Cloud Run). Sans ce retry, une écriture refusée tuait tout un run d'éval de
    plusieurs centaines de lignes."""
    tokens = iter(["jeton-perime", "jeton-frais"])
    monkeypatch.setattr(gcp, "_access_token", lambda: (next(tokens), _EXPIRY))

    sent = []

    def _fake_request(method, url, headers=None, **kwargs):
        sent.append(headers["Authorization"])
        return _FakeResponse(401 if len(sent) == 1 else 200)

    monkeypatch.setattr(gcp.requests, "request", _fake_request)

    response = gcp._FirestoreRest("some-project")._request("POST", "https://example.invalid/doc")

    assert response.status_code == 200
    assert sent == ["Bearer jeton-perime", "Bearer jeton-frais"]


def test_firestore_request_does_not_retry_when_the_call_succeeds(monkeypatch):
    """Le chemin nominal ne paie aucun appel supplémentaire au fournisseur de
    jeton — le retry est réservé au 401."""
    calls = {"tokens": 0, "requests": 0}

    def _fake_access_token():
        calls["tokens"] += 1
        return "jeton", _EXPIRY

    def _fake_request(method, url, headers=None, **kwargs):
        calls["requests"] += 1
        return _FakeResponse(200)

    monkeypatch.setattr(gcp, "_access_token", _fake_access_token)
    monkeypatch.setattr(gcp.requests, "request", _fake_request)

    gcp._FirestoreRest("some-project")._request("GET", "https://example.invalid/doc")

    assert calls == {"tokens": 1, "requests": 1}


def test_firestore_headers_renew_the_token_once_expired(monkeypatch):
    """Le jeton est réutilisé tant qu'il est valide, et renouvelé une fois
    l'échéance (moins la marge) dépassée — pas à chaque requête."""
    tokens = iter(["premier", "second"])
    expiries = iter([datetime.utcnow() + gcp._TOKEN_SAFETY_MARGIN, _EXPIRY])
    monkeypatch.setattr(gcp, "_access_token", lambda: (next(tokens), next(expiries)))

    client = gcp._FirestoreRest("some-project")
    # Première échéance déjà dans la marge de sécurité : le jeton suivant est demandé.
    assert client._headers() == {"Authorization": "Bearer premier"}
    assert client._headers() == {"Authorization": "Bearer second"}
    # Le second est valide longtemps : plus aucun renouvellement.
    assert client._headers() == {"Authorization": "Bearer second"}
