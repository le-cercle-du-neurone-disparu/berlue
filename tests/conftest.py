import numpy as np
import pandas as pd
import pytest

# TODO: Importer les constantes ou types spécifiques à votre projet si nécessaire
# from berlue.params import *


@pytest.fixture(scope="session")
def fixture_mock_raw_data() -> pd.DataFrame:
    """
    Fournit un DataFrame brut factice pour les tests.
    scope="session" garantit que ceci ne s'exécute qu'une fois par suite de tests.
    """
    # TODO: Remplacer par votre propre génération de données factices ou charger un petit CSV local
    data = {"feature_1": np.random.rand(10), "feature_2": np.random.rand(10), "target": np.random.randint(0, 2, 10)}
    return pd.DataFrame(data)


@pytest.fixture(scope="session")
def fixture_mock_cleaned_data() -> pd.DataFrame:
    """
    Fournit un DataFrame nettoyé factice pour tester l'entraînement du modèle ou les prédictions.
    """
    # TODO: Adapter au format de données nettoyées attendu par votre projet
    data = {
        "feature_1_scaled": np.random.rand(10),
        "feature_2_scaled": np.random.rand(10),
        "target": np.random.randint(0, 2, 10),
    }
    return pd.DataFrame(data)
