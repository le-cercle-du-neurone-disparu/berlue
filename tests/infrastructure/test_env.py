from pathlib import Path

import pytest


@pytest.mark.functional
def test_env_file_exists():
    """Vérifie que le fichier .env existe à la racine du projet."""
    env_path = Path(".env")
    assert env_path.is_file(), "❌ Le fichier .env est manquant ! Avez-vous lancé 'cp .env.sample .env' ?"
