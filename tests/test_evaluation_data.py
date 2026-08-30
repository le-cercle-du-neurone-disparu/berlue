"""Tests pour `berlue.evaluation.data` — pas de réseau requis (le split travaille
sur des exemples synthétiques, la validation des noms de dataset se fait avant
tout téléchargement)."""

import pytest

from berlue.evaluation.data import explode_answers, load_labeled_examples, split_train_test


def test_load_labeled_examples_rejects_unknown_dataset():
    """Un nom de dataset hors `KNOWN_DATASETS` doit lever une erreur claire avant
    toute tentative de téléchargement."""
    with pytest.raises(ValueError, match="Dataset inconnu"):
        load_labeled_examples(datasets=["not_a_real_dataset"])


def test_explode_answers_splits_on_semicolon_and_strips():
    """Une ligne par variante de réponse, séparateur ';' — une même question peut
    donc apparaître plusieurs fois si elle a plusieurs variantes (cf. TruthfulQA,
    où `Correct Answers`/`Incorrect Answers` sont des listes de taille variable)."""
    rows = [{"Question": "q1", "Answers": " a ;b; c "}, {"Question": "q2", "Answers": "d"}]

    records = explode_answers(rows, "Question", "Answers", ground_truth_label=True)

    assert records == [
        {"question": "q1", "answer": "a", "ground_truth_label": True},
        {"question": "q1", "answer": "b", "ground_truth_label": True},
        {"question": "q1", "answer": "c", "ground_truth_label": True},
        {"question": "q2", "answer": "d", "ground_truth_label": True},
    ]


def make_examples(n_questions: int, source: str = "synthetic") -> list[dict]:
    """`n_questions` questions distinctes, chacune avec une version vraie et une
    version hallucinée — reproduit la forme que produit `load_labeled_examples`
    pour HaluEval (deux lignes par question, cf. son docstring)."""
    examples = []
    for i in range(n_questions):
        question = f"{source} question {i} ?"
        examples.append(
            {"question": question, "answer": "réponse correcte", "ground_truth_label": True, "source": source}
        )
        examples.append(
            {"question": question, "answer": "réponse hallucinée", "ground_truth_label": False, "source": source}
        )
    return examples


def test_split_train_test_no_question_leakage():
    """Une même question ne doit jamais se retrouver à la fois dans train et test
    — c'est la fuite corrigée par le split par question unique (au lieu d'un split
    par ligne, qui pourrait séparer la version vraie et la version hallucinée
    d'une même question de part et d'autre)."""
    examples = make_examples(n_questions=20)

    train_examples, test_examples = split_train_test(examples, train_ratio=0.75, seed=0)

    train_questions = {ex["question"] for ex in train_examples}
    test_questions = {ex["question"] for ex in test_examples}

    assert train_questions.isdisjoint(test_questions)
    assert len(train_examples) + len(test_examples) == len(examples)


def test_split_train_test_keeps_both_rows_of_a_question_together():
    """Les deux lignes (vraie/hallucinée) d'une question donnée doivent atterrir
    ensemble du même côté du split."""
    examples = make_examples(n_questions=10)

    train_examples, test_examples = split_train_test(examples, train_ratio=0.7, seed=0)

    for question in {ex["question"] for ex in examples}:
        in_train = sum(1 for ex in train_examples if ex["question"] == question)
        in_test = sum(1 for ex in test_examples if ex["question"] == question)
        assert in_train == 0 or in_test == 0, f"'{question}' est à cheval sur train et test"
        assert in_train + in_test == 2


def test_split_train_test_balances_train_classes():
    """Le train doit toujours avoir autant d'exemples vrais que faux, même si les
    exemples de départ sont déséquilibrés (questions supplémentaires uniquement
    fausses, sans pendant vrai)."""
    examples = make_examples(n_questions=15)
    for i in range(15, 25):
        examples.append(
            {
                "question": f"synthetic question {i} ?",
                "answer": "réponse hallucinée",
                "ground_truth_label": False,
                "source": "synthetic",
            }
        )

    train_examples, _test_examples = split_train_test(examples, train_ratio=0.8, seed=0)

    n_true = sum(1 for ex in train_examples if ex["ground_truth_label"] is True)
    n_false = sum(1 for ex in train_examples if ex["ground_truth_label"] is False)
    assert n_true == n_false > 0


def test_split_train_test_balances_each_source_independently():
    """Une source déjà équilibrée (autant de vrai que de faux par question) ne
    doit jamais être touchée par le rééquilibrage d'une autre source déséquilibrée
    — sinon des questions parfaitement appariées perdraient une de leurs deux
    réponses pour compenser un déséquilibre qui ne les concerne pas."""
    balanced_source = make_examples(n_questions=20, source="balanced")

    imbalanced_source = make_examples(n_questions=20, source="imbalanced")
    for i in range(20, 40):
        imbalanced_source.append(
            {
                "question": f"imbalanced question {i} ?",
                "answer": "réponse hallucinée",
                "ground_truth_label": False,
                "source": "imbalanced",
            }
        )

    examples = balanced_source + imbalanced_source
    train_examples, _test_examples = split_train_test(examples, train_ratio=0.9, seed=0)

    balanced_in_train = [ex for ex in train_examples if ex["source"] == "balanced"]
    per_question = {}
    for ex in balanced_in_train:
        per_question.setdefault(ex["question"], set()).add(ex["ground_truth_label"])

    assert len(per_question) > 0
    assert all(labels == {True, False} for labels in per_question.values()), (
        "des questions de la source déjà équilibrée ont perdu une de leurs deux réponses"
    )


def test_split_train_test_reproducible_across_calls():
    """Même `seed`, même liste d'exemples (mais recréée, pas le même objet Python)
    -> même split, d'un appel à l'autre — nécessaire pour que l'entraînement et
    l'évaluation (deux process séparés) retombent sur le même jeu de test."""
    train_1, test_1 = split_train_test(make_examples(n_questions=20), train_ratio=0.75, seed=0)
    train_2, test_2 = split_train_test(make_examples(n_questions=20), train_ratio=0.75, seed=0)

    assert {ex["question"] for ex in train_1} == {ex["question"] for ex in train_2}
    assert {ex["question"] for ex in test_1} == {ex["question"] for ex in test_2}
