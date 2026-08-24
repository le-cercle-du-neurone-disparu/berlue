import os

import pytest
from google.cloud import storage

GCP_PROJECT = os.environ.get("GCP_PROJECT")
BUCKET_NAME = os.environ.get("BUCKET_NAME")


def test_setup_key_env():
    """Verify that $GOOGLE_APPLICATION_CREDENTIALS is defined"""
    assert os.getenv("GOOGLE_APPLICATION_CREDENTIALS"), (
        "❌ GOOGLE_APPLICATION_CREDENTIALS environment variable is not defined."
    )


def test_setup_key_path():
    """Verify that $GOOGLE_APPLICATION_CREDENTIALS points to an existing file"""
    service_account_key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    assert service_account_key_path, "❌ GOOGLE_APPLICATION_CREDENTIALS is not set."
    assert os.path.exists(service_account_key_path), f"❌ GCP Key file not found at {service_account_key_path}"


def test_code_get_project():
    """Verify we can authenticate and retrieve the default GCP project id"""
    try:
        client = storage.Client()
        assert client.project is not None, "❌ Could not authenticate to GCP. Check your service account."
    except Exception as e:
        pytest.fail(f"❌ Failed to connect to Google Cloud: {e}")


def test_setup_project_id():
    """Verify that the provided project id matches the authenticated one"""
    assert GCP_PROJECT, "❌ GCP_PROJECT is not defined in your environment."
    client = storage.Client()
    assert client.project == GCP_PROJECT, (
        f"❌ Authenticated project '{client.project}' differs from env GCP_PROJECT '{GCP_PROJECT}'"
    )


def test_setup_bucket_name():
    """Verify that the provided bucket exists and is accessible"""
    assert BUCKET_NAME, "❌ BUCKET_NAME is not defined in your environment."
    client = storage.Client()
    try:
        client.get_bucket(BUCKET_NAME, timeout=10.0)
    except Exception as e:
        pytest.fail(f"❌ Bucket '{BUCKET_NAME}' could not be found or accessed. Make sure it exists. Error: {e}")
