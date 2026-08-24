import os
import pytest
from pathlib import Path
from dotenv import load_dotenv

def test_env_file_exists():
    """Verify that the .env file exists at the root of the project."""
    env_path = Path(".env")
    assert env_path.is_file(), "❌ .env file is missing! Did you run 'cp .env.sample .env'?"

def test_critical_env_variables_are_set():
    """Verify that critical variables are filled and not left empty."""
    # We load the .env file explicitly for the test
    load_dotenv()

    # Add any variable here that is absolutely required to start the project
    critical_vars = [
        "PACKAGE_NAME",
        "GCP_PROJECT",
        "GCP_REGION",
        "BUCKET_NAME",
        "PYTHON_VERSION"
    ]

    for var in critical_vars:
        val = os.getenv(var)
        assert val, f"❌ '{var}' is empty in your .env file! You must fill it out."
