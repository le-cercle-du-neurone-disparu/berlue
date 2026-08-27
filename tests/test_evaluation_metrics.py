"""Tests pour `berlue.evaluation.metrics.build_confusion_matrix`."""

import pytest

from berlue.core.schemas import Verdict
from berlue.evaluation.metrics import build_confusion_matrix


def test_build_confusion_matrix_counts_each_cell():
    ground_truth = [True, True, True, False, False, False]
    predictions = [
        Verdict.SUPPORTED,
        Verdict.SUPPORTED,
        Verdict.CONTRADICTED,
        Verdict.CONTRADICTED,
        Verdict.NOT_ENOUGH_INFO,
        Verdict.SUPPORTED,
    ]

    matrix = build_confusion_matrix(ground_truth, predictions)

    assert matrix.ground_truth_true.predicted_true == 2
    assert matrix.ground_truth_true.predicted_undecided == 0
    assert matrix.ground_truth_true.predicted_false == 1

    assert matrix.ground_truth_false.predicted_true == 1
    assert matrix.ground_truth_false.predicted_undecided == 1
    assert matrix.ground_truth_false.predicted_false == 1


def test_build_confusion_matrix_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="Taille asymétrique"):
        build_confusion_matrix(ground_truth=[True, False], predictions=[Verdict.SUPPORTED])
