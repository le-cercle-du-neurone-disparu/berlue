"""Test d'intégration du store GCP (Firestore + BigQuery) — nécessite de
vraies credentials `gcloud` valides (session CLI, pas l'ADC, cf. docstring de
`berlue.evaluation.gcp_result_store`). Couvre un sous-ensemble représentatif
(une table individuelle, une table de matrice, purge, registre de scopes)
plutôt que les 8 tables — la parité complète avec `LocalResultStore` est
déjà couverte côté unitaire par `test_result_store.py` (mêmes appels, store
différent)."""

import pytest

from berlue.api.schemas import ConfusionMatrix, ConfusionRow
from berlue.core.schemas import Verdict
from berlue.evaluation.gcp_result_store import GcpResultStore
from berlue.evaluation.result_store import EvalScope

pytestmark = pytest.mark.gcp

MODEL_ID = "pytest-gcp-smoke-test"


@pytest.fixture
def store():
    store = GcpResultStore()
    yield store
    store.purge(model_id=MODEL_ID)  # nettoie ce que le test a écrit, réussi ou pas


@pytest.fixture
def scope():
    return EvalScope(
        dataset="halueval",
        ratio=0.8,
        model_id=MODEL_ID,
        pipeline_version="v1",
        generation_version="v1",
        eval_version="v1",
    )


def test_prediction_roundtrip_and_dedup(store, scope):
    assert store.get_verdict(scope, "Q1", "A1") is None

    assert store.put_prediction(scope, "Q1", "A1", True, Verdict.SUPPORTED) is True
    assert store.put_prediction(scope, "Q1", "A1", True, Verdict.SUPPORTED) is False  # déjà en cache

    assert store.get_verdict(scope, "Q1", "A1") == Verdict.SUPPORTED
    predictions = store.list_predictions(scope)
    assert len(predictions) == 1
    assert predictions[0]["question"] == "Q1"


def test_registry_flush_and_list_scopes(store, scope):
    """Le registre de scopes (`_scope_registry`) est bufferisé en mémoire —
    sans `flush_registry()`, `list_prediction_scopes()` ne doit rien voir."""
    store.put_prediction(scope, "Q1", "A1", True, Verdict.SUPPORTED)
    store.put_prediction(scope, "Q2", "A2", True, Verdict.SUPPORTED)

    before_flush = [s for s in store.list_prediction_scopes() if s["model_id"] == MODEL_ID]
    assert before_flush == []

    store.flush_registry()

    after_flush = [s for s in store.list_prediction_scopes() if s["model_id"] == MODEL_ID]
    assert len(after_flush) == 1
    assert after_flush[0]["n_rows"] == 2


def test_matrix_roundtrip_and_upsert(store, scope):
    matrix = ConfusionMatrix(
        ground_truth_true=ConfusionRow(predicted_true=3, predicted_undecided=1, predicted_false=0),
        ground_truth_false=ConfusionRow(predicted_true=0, predicted_undecided=1, predicted_false=4),
    )

    assert store.get_matrix(scope) is None
    store.put_matrix(scope, matrix, n_examples=9)
    assert store.get_matrix(scope) == matrix

    store.put_matrix(scope, matrix, n_examples=9)  # upsert (MERGE), ne doit pas échouer
    assert store.get_matrix(scope) == matrix

    matrices = store.list_matrices(model_id=MODEL_ID)
    assert len(matrices) == 1


def test_matrix_dataset_test_size_defaults_to_none_and_round_trips(store, scope):
    matrix = ConfusionMatrix(
        ground_truth_true=ConfusionRow(predicted_true=1, predicted_undecided=0, predicted_false=0),
        ground_truth_false=ConfusionRow(predicted_true=0, predicted_undecided=0, predicted_false=1),
    )

    store.put_matrix(scope, matrix, n_examples=2)
    assert store.list_matrices(model_id=MODEL_ID)[0]["dataset_test_size"] is None

    store.put_matrix(scope, matrix, n_examples=2, dataset_test_size=4000)
    assert store.list_matrices(model_id=MODEL_ID)[0]["dataset_test_size"] == 4000


def test_purge_covers_both_backends(store, scope):
    store.put_prediction(scope, "Q1", "A1", True, Verdict.SUPPORTED)
    matrix = ConfusionMatrix(
        ground_truth_true=ConfusionRow(predicted_true=1, predicted_undecided=0, predicted_false=0),
        ground_truth_false=ConfusionRow(predicted_true=0, predicted_undecided=0, predicted_false=1),
    )
    store.put_matrix(scope, matrix, n_examples=1)

    counts = store.purge(model_id=MODEL_ID)
    assert counts["predictions_deleted"] == 1
    assert counts["matrices_deleted"] == 1
    assert store.get_verdict(scope, "Q1", "A1") is None
    assert store.get_matrix(scope) is None


def test_purge_scope_results_only_leaves_matrices(store, scope):
    store.put_prediction(scope, "Q1", "A1", True, Verdict.SUPPORTED)
    matrix = ConfusionMatrix(
        ground_truth_true=ConfusionRow(predicted_true=1, predicted_undecided=0, predicted_false=0),
        ground_truth_false=ConfusionRow(predicted_true=0, predicted_undecided=0, predicted_false=1),
    )
    store.put_matrix(scope, matrix, n_examples=1)

    counts = store.purge(model_id=MODEL_ID, scope="results")

    assert counts["predictions_deleted"] == 1
    assert "matrices_deleted" not in counts
    assert store.get_verdict(scope, "Q1", "A1") is None
    assert store.get_matrix(scope) == matrix  # pas touchée
