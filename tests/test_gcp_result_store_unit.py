"""Tests unitaires purs pour `berlue.evaluation.gcp_result_store` — aucune
infra GCP requise (contrairement à `test_gcp_result_store.py`, `functional`).
Couvre uniquement la sélection de la source du jeton d'accès (local vs
Cloud Run), cf. docstring du module."""

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
