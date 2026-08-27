"""Tests pour `berlue.evaluation.data` — pas de réseau requis (le split travaille
sur des exemples synthétiques, la validation des noms de dataset se fait avant
tout téléchargement)."""

import pytest

from berlue.evaluation.data import load_labeled_examples, split_train_test


def test_load_labeled_examples_rejects_unknown_dataset():
    """Un nom de dataset hors `KNOWN_DATASETS` doit lever une erreur claire avant
    toute tentative de téléchargement."""
    with pytest.raises(ValueError, match="Dataset inconnu"):
        load_labeled_examples(datasets=["not_a_real_dataset"])


def _make_examples(n_questions: int) -> list[dict]:
    """`n_questions` questions distinctes, chacune avec une version vraie et une
    version hallucinée — reproduit la forme que produit `load_labeled_examples`
    pour HaluEval (deux lignes par question, cf. son docstring)."""
    examples = []
    for i in range(n_questions):
        question = f"question {i} ?"
        examples.append({"question": question, "answer": "réponse correcte", "ground_truth_label": True})
        examples.append({"question": question, "answer": "réponse hallucinée", "ground_truth_label": False})
    return examples


def test_split_train_test_no_question_leakage():
    """Une même question ne doit jamais se retrouver à la fois dans train et test
    — c'est la fuite corrigée par le split par question unique (au lieu d'un split
    par ligne, qui pourrait séparer la version vraie et la version hallucinée
    d'une même question de part et d'autre)."""
    examples = _make_examples(n_questions=20)

    train_examples, test_examples = split_train_test(examples, test_size=0.25, seed=0)

    train_questions = {ex["question"] for ex in train_examples}
    test_questions = {ex["question"] for ex in test_examples}

    assert train_questions.isdisjoint(test_questions)
    assert len(train_examples) + len(test_examples) == len(examples)


def test_split_train_test_keeps_both_rows_of_a_question_together():
    """Les deux lignes (vraie/hallucinée) d'une question donnée doivent atterrir
    ensemble du même côté du split."""
    examples = _make_examples(n_questions=10)

    train_examples, test_examples = split_train_test(examples, test_size=0.3, seed=0)

    for question in {ex["question"] for ex in examples}:
        in_train = sum(1 for ex in train_examples if ex["question"] == question)
        in_test = sum(1 for ex in test_examples if ex["question"] == question)
        assert in_train == 0 or in_test == 0, f"'{question}' est à cheval sur train et test"
        assert in_train + in_test == 2
