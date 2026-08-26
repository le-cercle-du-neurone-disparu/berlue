"""Construction des matrices de confusion de l'évaluation offline (baseline NLI vs
pipeline Berlue complet) — alimente `berlue.api.schemas.Metrics`."""

from berlue.api.schemas import ConfusionMatrix
from berlue.core.schemas import Verdict


def build_confusion_matrix(ground_truth: list[bool], predictions: list[Verdict]) -> ConfusionMatrix:
    """Construit une matrice de confusion 2x3 à partir de labels vérité-terrain
    (`True` = affirmation vraie, `False` = affirmation fausse) et des verdicts
    prédits (un couple par affirmation évaluée, `ground_truth` et `predictions`
    doivent avoir la même longueur)."""
    # TODO(evaluation)
    # return ConfusionMatrix(
    #     ground_truth_true=ConfusionRow(predicted_true=50, predicted_undecided=15, predicted_false=10),
    #     ground_truth_false=ConfusionRow(predicted_true=8, predicted_undecided=7, predicted_false=10),
    # )
    raise NotImplementedError
