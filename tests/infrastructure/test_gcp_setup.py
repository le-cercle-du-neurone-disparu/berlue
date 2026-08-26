import os

import pytest
from google.cloud import storage

GCP_PROJECT = os.environ.get("GCP_PROJECT")
BUCKET_NAME = os.environ.get("BUCKET_NAME")


def test_setup_key_env():
    """Vérifie que $GOOGLE_APPLICATION_CREDENTIALS est défini"""
    assert os.getenv("GOOGLE_APPLICATION_CREDENTIALS"), (
        "❌ La variable d'environnement GOOGLE_APPLICATION_CREDENTIALS n'est pas définie."
    )


def test_setup_key_path():
    """Vérifie que $GOOGLE_APPLICATION_CREDENTIALS pointe vers un fichier existant"""
    service_account_key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    assert service_account_key_path, "❌ GOOGLE_APPLICATION_CREDENTIALS n'est pas définie."
    assert os.path.exists(service_account_key_path), f"❌ Fichier de clé GCP introuvable à {service_account_key_path}"


def test_code_get_project():
    """Vérifie qu'on peut s'authentifier et récupérer l'id du projet GCP par défaut"""
    try:
        client = storage.Client()
        assert client.project is not None, (
            "❌ Impossible de s'authentifier auprès de GCP. Vérifiez votre compte de service."
        )
    except Exception as e:
        pytest.fail(f"❌ Échec de connexion à Google Cloud : {e}")


def test_setup_project_id():
    """Vérifie que l'id de projet fourni correspond à celui authentifié"""
    assert GCP_PROJECT, "❌ GCP_PROJECT n'est pas défini dans votre environnement."
    client = storage.Client()
    assert client.project == GCP_PROJECT, (
        f"❌ Le projet authentifié '{client.project}' diffère du GCP_PROJECT '{GCP_PROJECT}' de l'environnement"
    )


def test_setup_bucket_name():
    """Vérifie que le bucket fourni existe et est accessible"""
    assert BUCKET_NAME, "❌ BUCKET_NAME n'est pas défini dans votre environnement."
    client = storage.Client()
    try:
        client.get_bucket(BUCKET_NAME, timeout=10.0)
    except Exception as e:
        pytest.fail(
            f"❌ Le bucket '{BUCKET_NAME}' est introuvable ou inaccessible. Vérifiez qu'il existe. Erreur : {e}"
        )
