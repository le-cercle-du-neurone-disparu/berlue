"""Test de contrat pour `berlue.nli_baseline.predict.NliBaseline.predict` -> `Verdict`."""

import pytest

from berlue.core.schemas import Verdict
from berlue.nli_baseline.predict import NliBaseline


@pytest.mark.functional  # a besoin du modèle entraîné par train_baseline() (fichier joblib)
@pytest.mark.skip(reason="TODO: à activer une fois NliBaseline.predict() implémenté")
def test_predict_returns_verdict():
    """predict() doit renvoyer un Verdict valide pour une paire question/réponse simple."""
    baseline = NliBaseline()
    result = baseline.predict(
        question="Quelle est la capitale de la France ?",
        answer="Paris est la capitale de la France.",
    )
    assert result in Verdict
