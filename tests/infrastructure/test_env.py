import os
from pathlib import Path

from dotenv import load_dotenv


def test_env_file_exists():
    """Vérifie que le fichier .env existe à la racine du projet."""
    env_path = Path(".env")
    assert env_path.is_file(), "❌ Le fichier .env est manquant ! Avez-vous lancé 'cp .env.sample .env' ?"


def test_critical_env_variables_are_set():
    """Vérifie que les variables critiques sont remplies et non laissées vides."""
    # On charge explicitement le fichier .env pour le test
    load_dotenv()

    # Ajoutez ici toute variable absolument nécessaire au démarrage du projet
    critical_vars = ["PACKAGE_NAME", "GCP_PROJECT", "GCP_REGION", "BUCKET_NAME", "PYTHON_VERSION"]

    for var in critical_vars:
        val = os.getenv(var)
        assert val, f"❌ '{var}' est vide dans votre fichier .env ! Vous devez le remplir."
