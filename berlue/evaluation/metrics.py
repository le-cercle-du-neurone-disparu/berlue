"""Construction des matrices de confusion de l'évaluation offline (baseline NLI vs
pipeline Berlue complet) — alimente `berlue.api.schemas.Metrics`.
"""

import logging

from berlue.api.schemas import ConfusionMatrix, ConfusionRow
from berlue.core.schemas import Verdict

logger = logging.getLogger(__name__)


def build_confusion_matrix(ground_truth: list[bool], predictions: list[Verdict]) -> ConfusionMatrix:
    """Construit une matrice de confusion 2x3 à partir de labels vérité-terrain
    (`True` = affirmation vraie, `False` = affirmation fausse) et des verdicts
    prédits (un couple par affirmation évaluée, `ground_truth` et `predictions`
    doivent avoir la même longueur).
    """
    if len(ground_truth) != len(predictions):
        raise ValueError(f"Taille asymétrique : ground_truth ({len(ground_truth)}) vs predictions ({len(predictions)})")

    # Compteurs pour la ligne : Ground Truth == True
    gt_true_pred_true = 0
    gt_true_pred_undecided = 0
    gt_true_pred_false = 0

    # Compteurs pour la ligne : Ground Truth == False
    gt_false_pred_true = 0
    gt_false_pred_undecided = 0
    gt_false_pred_false = 0

    # Exclues du comptage, mais signalées : un run qui en accumule est un run à rejouer.
    n_pannes = 0

    # Comptage via un zip (qui itère sur les deux listes en parallèle)
    for gt, pred in zip(ground_truth, predictions, strict=True):
        # Une panne n'est pas une prédiction : le pipeline n'a rien dit. La compter
        # remplirait la matrice de verdicts qui ne sont que l'écho d'une panne d'infra,
        # indiscernables de vraies prédictions.
        if pred == Verdict.PANNE:
            n_pannes += 1
            continue
        if gt is True:
            if pred == Verdict.SUPPORTED:
                gt_true_pred_true += 1
            elif pred == Verdict.NOT_ENOUGH_INFO:
                gt_true_pred_undecided += 1
            elif pred == Verdict.CONTRADICTED:
                gt_true_pred_false += 1
        else:
            if pred == Verdict.SUPPORTED:
                gt_false_pred_true += 1
            elif pred == Verdict.NOT_ENOUGH_INFO:
                gt_false_pred_undecided += 1
            elif pred == Verdict.CONTRADICTED:
                gt_false_pred_false += 1

    if n_pannes:
        logger.warning(
            "⚠️ %d/%d prédiction(s) exclue(s) de la matrice : panne du pipeline, à rejouer.",
            n_pannes,
            len(predictions),
        )

    return ConfusionMatrix(
        ground_truth_true=ConfusionRow(
            predicted_true=gt_true_pred_true,
            predicted_undecided=gt_true_pred_undecided,
            predicted_false=gt_true_pred_false,
        ),
        ground_truth_false=ConfusionRow(
            predicted_true=gt_false_pred_true,
            predicted_undecided=gt_false_pred_undecided,
            predicted_false=gt_false_pred_false,
        ),
    )
