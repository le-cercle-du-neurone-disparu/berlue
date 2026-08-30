"""Tests unitaires purs pour `berlue.evaluation.gcp_result_store` — aucune
infra GCP requise (contrairement à `test_gcp_result_store.py`, `functional`).
Couvre la sélection de la source du jeton d'accès (local vs Cloud Run) et la
sécurité thread du registre de scopes bufferisé, cf. docstring du module."""

import threading

import pytest

from berlue.evaluation import gcp_result_store as gcp


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
    monkeypatch.setenv("CLOUD_RUN_JOB", "berlue-eval-mocked")
    assert gcp._running_on_cloud_run() is True


class _FakeAdcCredentials:
    """Simule des credentials `google.auth.default()` — `refresh()` pose
    `token`, comme le fait la vraie lib."""

    def __init__(self):
        self.token = None

    def refresh(self, request):
        self.token = "fake-adc-token"


def test_access_token_uses_adc_on_cloud_run(monkeypatch):
    """Sur Cloud Run, pas d'appel à `gcloud` — jeton via `google.auth.default()`,
    déjà `sa-berlue` via l'identité attachée au service/job."""
    monkeypatch.setenv("K_SERVICE", "berlue-api-test")
    fake_credentials = _FakeAdcCredentials()
    monkeypatch.setattr(gcp.google.auth, "default", lambda: (fake_credentials, "some-project"))

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("gcloud CLI ne doit jamais être appelé en exécution Cloud Run")

    monkeypatch.setattr(gcp.subprocess, "check_output", _fail_if_called)

    assert gcp._access_token() == "fake-adc-token"


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

    assert gcp._access_token() == "fake-cli-token"
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
