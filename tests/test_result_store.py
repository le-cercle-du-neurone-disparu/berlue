"""Tests pour `berlue.evaluation.result_store` — SQLite sur fichier temporaire
(`tmp_path`), aucune infra externe requise."""

from dataclasses import replace

import pytest

from berlue.api.schemas import ConfusionMatrix, ConfusionRow
from berlue.core.schemas import Verdict
from berlue.evaluation.result_store import EvalScope, LocalResultStore, get_result_store
from berlue.evaluation.signals import SIGNALS_FORMAT_VERSION


def _store(tmp_path) -> LocalResultStore:
    return LocalResultStore(db_path=str(tmp_path / "eval.db"))


def _scope(**overrides) -> EvalScope:
    defaults = {
        "dataset": "halueval",
        "ratio": 0.8,
        "model_id": "m",
        "pipeline_version": "v1",
        "generation_version": "v1",
        "eval_version": "v1",
    }
    return EvalScope(**{**defaults, **overrides})


def _matrix(a=1, b=0, c=0, d=0, e=0, f=1) -> ConfusionMatrix:
    return ConfusionMatrix(
        ground_truth_true=ConfusionRow(predicted_true=a, predicted_undecided=b, predicted_false=c),
        ground_truth_false=ConfusionRow(predicted_true=d, predicted_undecided=e, predicted_false=f),
    )


def test_eval_scope_as_dict_returns_requested_fields_only():
    scope = _scope(dataset="halueval", pipeline_version="p1", generation_version="g1", eval_version="e1")
    assert scope.as_dict("dataset", "pipeline_version") == {"dataset": "halueval", "pipeline_version": "p1"}


def test_get_verdict_absent_returns_none(tmp_path):
    store = _store(tmp_path)
    assert store.get_verdict(_scope(), "une question", "une réponse") is None


def test_put_then_get_verdict_roundtrip(tmp_path):
    store = _store(tmp_path)
    scope = _scope()

    store.put_prediction(scope, "q", "a", ground_truth_label=True, verdict=Verdict.SUPPORTED)

    assert store.get_verdict(scope, "q", "a") == Verdict.SUPPORTED


def test_put_prediction_is_idempotent(tmp_path):
    """Un deuxième `put_prediction` sur la même (scope, question, answer) ne
    doit rien écraser — c'est le mécanisme de dédoublonnage entre workers
    concurrents qui tombent sur la même clé."""
    store = _store(tmp_path)
    scope = _scope()

    first = store.put_prediction(scope, "q", "a", ground_truth_label=True, verdict=Verdict.SUPPORTED)
    second = store.put_prediction(scope, "q", "a", ground_truth_label=True, verdict=Verdict.CONTRADICTED)

    assert first is True
    assert second is False
    assert store.get_verdict(scope, "q", "a") == Verdict.SUPPORTED


def test_get_verdict_is_scoped(tmp_path):
    """Une prédiction stockée sous un scope ne doit pas être visible depuis un
    scope différent (ex. un autre `model_id`)."""
    store = _store(tmp_path)
    store.put_prediction(_scope(model_id="a"), "q", "a", ground_truth_label=True, verdict=Verdict.SUPPORTED)

    assert store.get_verdict(_scope(model_id="b"), "q", "a") is None


def test_get_verdict_is_scoped_by_dataset(tmp_path):
    """Deux scopes qui ne diffèrent que par `dataset` ne partagent jamais de
    résultat — les résultats ne mélangent jamais plusieurs datasets."""
    store = _store(tmp_path)
    store.put_prediction(_scope(dataset="halueval"), "q", "a", ground_truth_label=True, verdict=Verdict.SUPPORTED)
    assert store.get_verdict(_scope(dataset="truthfulqa"), "q", "a") is None


def test_list_prediction_scopes_summarizes_by_scope(tmp_path):
    store = _store(tmp_path)
    store.put_prediction(_scope(model_id="a"), "q1", "x", True, Verdict.SUPPORTED)
    store.put_prediction(_scope(model_id="a"), "q2", "y", True, Verdict.SUPPORTED)
    store.put_prediction(_scope(model_id="b"), "q1", "x", True, Verdict.SUPPORTED)

    scopes = store.list_prediction_scopes()

    by_model = {s["model_id"]: s["n_rows"] for s in scopes}
    assert by_model == {"a": 2, "b": 1}


def test_flush_registry_is_a_noop_locally(tmp_path):
    """Parité d'interface avec `GcpResultStore` — ne doit jamais lever."""
    store = _store(tmp_path)
    store.flush_registry()


def test_put_and_get_matrix_roundtrip(tmp_path):
    store = _store(tmp_path)
    scope = _scope()
    matrix = _matrix(5, 1, 2, 1, 2, 5)

    assert store.get_matrix(scope) is None

    store.put_matrix(scope, matrix, n_examples=16)

    assert store.get_matrix(scope) == matrix


def test_put_matrix_dataset_test_size_defaults_to_none_and_round_trips(tmp_path):
    """`dataset_test_size` : `None` par défaut (pas de connaissance du split
    officiel), sinon la valeur explicite — round-trip via `list_matrices`
    (`get_matrix` ne renvoie que la matrice, pas les métadonnées)."""
    store = _store(tmp_path)
    matrix = _matrix()

    store.put_matrix(_scope(model_id="no-total"), matrix, n_examples=3)
    store.put_matrix(_scope(model_id="with-total"), matrix, n_examples=3, dataset_test_size=4000)

    no_total = store.list_matrices(model_id="no-total")[0]
    with_total = store.list_matrices(model_id="with-total")[0]
    assert no_total["dataset_test_size"] is None
    assert with_total["dataset_test_size"] == 4000


def test_put_matrix_overwrites_previous(tmp_path):
    """Rappeler `put_matrix` sur le même scope remplace la matrice précédente
    (ex. `evaluate_model_matrix` relancé après un rééquilibrage du cache)."""
    store = _store(tmp_path)
    scope = _scope()
    first = _matrix(1, 0, 0, 0, 0, 1)
    second = _matrix(9, 0, 0, 0, 0, 9)

    store.put_matrix(scope, first, n_examples=1)
    store.put_matrix(scope, second, n_examples=9)

    assert store.get_matrix(scope) == second


def test_list_matrices_filters_by_scope_fields(tmp_path):
    store = _store(tmp_path)
    matrix = _matrix()
    store.put_matrix(_scope(model_id="a"), matrix, n_examples=1)
    store.put_matrix(_scope(model_id="b"), matrix, n_examples=1)

    all_results = store.list_matrices()
    filtered = store.list_matrices(model_id="a")

    assert len(all_results) == 2
    assert len(filtered) == 1
    assert filtered[0]["model_id"] == "a"


def test_list_matrices_filters_by_dataset(tmp_path):
    store = _store(tmp_path)
    matrix = _matrix()
    store.put_matrix(_scope(dataset="halueval"), matrix, n_examples=1)
    store.put_matrix(_scope(dataset="truthfulqa"), matrix, n_examples=1)

    filtered = store.list_matrices(dataset="halueval")

    assert len(filtered) == 1
    assert filtered[0]["dataset"] == "halueval"


def test_purge_deletes_predictions_and_matrix_for_matching_scope_only(tmp_path):
    store = _store(tmp_path)
    matrix = _matrix()
    scope_a = _scope(model_id="a")
    scope_b = _scope(model_id="b")

    store.put_prediction(scope_a, "q", "a", ground_truth_label=True, verdict=Verdict.SUPPORTED)
    store.put_matrix(scope_a, matrix, n_examples=1)
    store.put_prediction(scope_b, "q", "a", ground_truth_label=True, verdict=Verdict.SUPPORTED)
    store.put_matrix(scope_b, matrix, n_examples=1)

    result = store.purge(model_id="a")

    assert result["predictions_deleted"] == 1
    assert result["matrices_deleted"] == 1
    assert store.get_verdict(scope_a, "q", "a") is None
    assert store.get_matrix(scope_a) is None
    assert store.get_verdict(scope_b, "q", "a") == Verdict.SUPPORTED


def test_purge_scope_results_only_leaves_matrices(tmp_path):
    store = _store(tmp_path)
    scope = _scope()
    store.put_prediction(scope, "q", "a", True, Verdict.SUPPORTED)
    store.put_matrix(scope, _matrix(), n_examples=1)

    result = store.purge(model_id=scope.model_id, scope="results")

    assert result == {
        "predictions_deleted": 1,
        "llm_answers_deleted": 0,
        "judge_verdicts_deleted": 0,
        "berlue_generated_deleted": 0,
        "baseline_generated_deleted": 0,
    }
    assert store.get_verdict(scope, "q", "a") is None
    assert store.get_matrix(scope) is not None  # la matrice n'a pas été touchée


def test_purge_scope_matrices_only_leaves_results(tmp_path):
    store = _store(tmp_path)
    scope = _scope()
    store.put_prediction(scope, "q", "a", True, Verdict.SUPPORTED)
    store.put_matrix(scope, _matrix(), n_examples=1)

    result = store.purge(model_id=scope.model_id, scope="matrices")

    assert result == {
        "matrices_deleted": 1,
        "matrices_generated_berlue_deleted": 0,
        "matrices_generated_baseline_deleted": 0,
    }
    assert store.get_matrix(scope) is None
    assert store.get_verdict(scope, "q", "a") is not None  # le résultat n'a pas été touché


def test_purge_invalid_scope_raises(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="scope de purge invalide"):
        store.purge(scope="not_a_scope")


def test_purge_covers_mode_2_tables(tmp_path):
    """purge() doit aussi nettoyer les tables du mode 2 (llm_answers,
    judge_verdicts, eval_*_generated, eval_matrices_generated_*) — pas
    seulement eval_predictions/eval_matrices du mode 1."""
    store = _store(tmp_path)
    scope = _scope(model_id="a")
    matrix = _matrix()

    store.put_generated_answer("a", "v1", "q", "réponse générée")
    store.put_judge_verdict("a", "v1", "judge-1", "v1", "q", Verdict.SUPPORTED)
    store.put_generated_berlue_verdict(scope, "q", Verdict.SUPPORTED)
    store.put_generated_baseline_verdict(scope.dataset, scope.ratio, "a", "v1", "v1", "q", Verdict.SUPPORTED)
    store.put_generated_berlue_matrix(scope, matrix, n_examples=1)
    store.put_generated_baseline_matrix(scope.dataset, scope.ratio, "a", "v1", "v1", matrix, n_examples=1)

    result = store.purge(model_id="a")

    assert result == {
        "predictions_deleted": 0,
        "matrices_deleted": 0,
        "signals_deleted": 0,
        "llm_answers_deleted": 1,
        "judge_verdicts_deleted": 1,
        "berlue_generated_deleted": 1,
        "baseline_generated_deleted": 1,
        "matrices_generated_berlue_deleted": 1,
        "matrices_generated_baseline_deleted": 1,
    }
    assert store.get_generated_answer("a", "v1", "q") is None
    assert store.get_judge_verdict("a", "v1", "judge-1", "v1", "q") is None
    assert store.get_generated_berlue_verdict(scope, "q") is None
    assert store.get_generated_baseline_verdict(scope.dataset, scope.ratio, "a", "v1", "v1", "q") is None
    assert store.get_generated_berlue_matrix(scope) is None
    assert store.get_generated_baseline_matrix(scope.dataset, scope.ratio, "a", "v1", "v1") is None


def test_purge_baseline_generated_ignores_pipeline_version_filter(tmp_path):
    """eval_baseline_generated n'a pas de colonne pipeline_version — un
    filtre pipeline_version fourni à purge() ne doit pas l'empêcher d'être
    nettoyée."""
    store = _store(tmp_path)
    store.put_generated_baseline_verdict("halueval", 0.8, "a", "v1", "v1", "q", Verdict.SUPPORTED)

    result = store.purge(model_id="a", pipeline_version="whatever")

    assert result["baseline_generated_deleted"] == 1
    assert store.get_generated_baseline_verdict("halueval", 0.8, "a", "v1", "v1", "q") is None


def test_get_generated_answer_absent_returns_none(tmp_path):
    store = _store(tmp_path)
    assert store.get_generated_answer("m1", "v1", "q") is None


def test_put_then_get_generated_answer_roundtrip(tmp_path):
    store = _store(tmp_path)
    store.put_generated_answer("m1", "v1", "q", "réponse générée")
    assert store.get_generated_answer("m1", "v1", "q") == "réponse générée"


def test_put_generated_answer_is_idempotent(tmp_path):
    store = _store(tmp_path)
    first = store.put_generated_answer("m1", "v1", "q", "réponse A")
    second = store.put_generated_answer("m1", "v1", "q", "réponse B")

    assert first is True
    assert second is False
    assert store.get_generated_answer("m1", "v1", "q") == "réponse A"


def test_generated_answer_is_scoped_by_model_id_and_generation_version(tmp_path):
    """Indépendant de dataset/ratio — mais dépendant de generation_version :
    changer le prompt de génération doit produire une nouvelle entrée, pas
    réutiliser silencieusement une réponse générée sous un prompt différent."""
    store = _store(tmp_path)
    store.put_generated_answer("a", "v1", "q", "réponse")
    assert store.get_generated_answer("b", "v1", "q") is None
    assert store.get_generated_answer("a", "v2", "q") is None


def test_list_generated_answer_scopes_summarizes(tmp_path):
    store = _store(tmp_path)
    store.put_generated_answer("a", "v1", "q1", "r1")
    store.put_generated_answer("a", "v1", "q2", "r2")
    store.put_generated_answer("a", "v2", "q1", "r1")

    scopes = store.list_generated_answer_scopes()
    by_version = {s["generation_version"]: s["n_rows"] for s in scopes}
    assert by_version == {"v1": 2, "v2": 1}


def test_get_judge_verdict_absent_returns_none(tmp_path):
    store = _store(tmp_path)
    assert store.get_judge_verdict("m1", "v1", "j1", "v1", "q") is None


def test_put_then_get_judge_verdict_roundtrip(tmp_path):
    store = _store(tmp_path)
    store.put_judge_verdict("m1", "v1", "j1", "v1", "q", Verdict.SUPPORTED)
    assert store.get_judge_verdict("m1", "v1", "j1", "v1", "q") == Verdict.SUPPORTED


def test_judge_verdict_is_scoped_by_model_judge_and_versions(tmp_path):
    store = _store(tmp_path)
    store.put_judge_verdict("m1", "v1", "j1", "v1", "q", Verdict.SUPPORTED)

    assert store.get_judge_verdict("m1", "v1", "j2", "v1", "q") is None, "un autre juge ne doit pas voir ce verdict"
    assert store.get_judge_verdict("m2", "v1", "j1", "v1", "q") is None, (
        "un autre modèle jugé ne doit pas voir ce verdict"
    )
    assert store.get_judge_verdict("m1", "v2", "j1", "v1", "q") is None, (
        "une autre generation_version ne doit pas voir ce verdict"
    )
    assert store.get_judge_verdict("m1", "v1", "j1", "v2", "q") is None, (
        "une autre eval_version ne doit pas voir ce verdict"
    )


def test_get_then_put_generated_berlue_verdict_roundtrip(tmp_path):
    store = _store(tmp_path)
    scope = _scope()

    assert store.get_generated_berlue_verdict(scope, "q") is None

    store.put_generated_berlue_verdict(scope, "q", Verdict.SUPPORTED)
    assert store.get_generated_berlue_verdict(scope, "q") == Verdict.SUPPORTED


def test_generated_berlue_verdict_is_scoped(tmp_path):
    """Un verdict Berlue mode 2 pour un scope ne doit pas être visible depuis
    un scope différent (ex. autre pipeline_version)."""
    store = _store(tmp_path)
    store.put_generated_berlue_verdict(_scope(pipeline_version="v1"), "q", Verdict.SUPPORTED)
    assert store.get_generated_berlue_verdict(_scope(pipeline_version="v2"), "q") is None


def test_get_then_put_generated_baseline_verdict_roundtrip(tmp_path):
    store = _store(tmp_path)

    assert store.get_generated_baseline_verdict("halueval", 0.8, "m1", "v1", "v1", "q") is None

    store.put_generated_baseline_verdict("halueval", 0.8, "m1", "v1", "v1", "q", Verdict.CONTRADICTED)
    assert store.get_generated_baseline_verdict("halueval", 0.8, "m1", "v1", "v1", "q") == Verdict.CONTRADICTED


def test_generated_baseline_verdict_independent_of_pipeline_version(tmp_path):
    """La baseline mode 2 n'a pas de notion de pipeline_version — un verdict
    stocké pour un (dataset, ratio, model_id, generation_version,
    eval_version) doit être retrouvable peu importe quelle version de
    Berlue tourne en parallèle."""
    store = _store(tmp_path)
    store.put_generated_baseline_verdict("halueval", 0.8, "m1", "v1", "v1", "q", Verdict.SUPPORTED)
    assert store.get_generated_baseline_verdict("halueval", 0.8, "m1", "v1", "v1", "q") == Verdict.SUPPORTED


def test_list_generated_berlue_matrices_filters_by_scope_fields(tmp_path):
    store = _store(tmp_path)
    matrix = _matrix()
    store.put_generated_berlue_matrix(_scope(model_id="a"), matrix, n_examples=1)
    store.put_generated_berlue_matrix(_scope(model_id="b"), matrix, n_examples=1)

    assert len(store.list_generated_berlue_matrices()) == 2
    filtered = store.list_generated_berlue_matrices(model_id="a")
    assert len(filtered) == 1
    assert filtered[0]["model_id"] == "a"


def test_list_generated_baseline_matrices_filters_by_scope_fields(tmp_path):
    store = _store(tmp_path)
    matrix = _matrix()
    store.put_generated_baseline_matrix("halueval", 0.8, "a", "v1", "v1", matrix, n_examples=1)
    store.put_generated_baseline_matrix("halueval", 0.8, "b", "v1", "v1", matrix, n_examples=1)

    assert len(store.list_generated_baseline_matrices()) == 2
    filtered = store.list_generated_baseline_matrices(model_id="a")
    assert len(filtered) == 1
    assert filtered[0]["model_id"] == "a"
    assert "pipeline_version" not in filtered[0]


def test_get_result_store_local_returns_local_store():
    assert isinstance(get_result_store("local"), LocalResultStore)


def test_get_result_store_gcp_dispatches_to_gcp_store(monkeypatch):
    """`GcpResultStore` touche du vrai GCP à l'instanciation (tables
    BigQuery) — pas adapté à un test unitaire. On vérifie juste le dispatch,
    pas le store réel."""

    class FakeGcpResultStore:
        pass

    monkeypatch.setattr("berlue.evaluation.gcp_result_store.GcpResultStore", FakeGcpResultStore)
    assert isinstance(get_result_store("gcp"), FakeGcpResultStore)


def test_get_result_store_invalid_target():
    with pytest.raises(ValueError, match="EVAL_STORE_TARGET invalide"):
        get_result_store("not_a_target")


# --- Cache des signaux pré-fusion -------------------------------------------


def _signals(divergence: float = 0.3) -> dict:
    """Signaux minimaux au format de `berlue.evaluation.signals`."""
    return {
        "format_version": SIGNALS_FORMAT_VERSION,
        "raw_answer": "une réponse",
        "panne": None,
        "claims": [{"id": "c1", "text": "Une affirmation."}],
        "rag_scores": [{"claim_id": "c1", "verdict": "likely_true", "confidence": 0.9, "evidence": None}],
        "selfcheck_scores": [{"claim_id": "c1", "divergence_score": divergence, "confidence": 1 - divergence}],
    }


def test_signals_absents_puis_en_cache(tmp_path):
    store = _store(tmp_path)
    scope = _scope()
    assert store.get_signals(scope, "q", "a") is None
    assert store.put_signals(scope, "q", "a", _signals()) is True
    assert store.get_signals(scope, "q", "a") == _signals()


def test_put_signals_n_ecrase_pas_une_entree_existante(tmp_path):
    """Deux workers sur la même question ne doivent pas se marcher dessus."""
    store = _store(tmp_path)
    scope = _scope()
    store.put_signals(scope, "q", "a", _signals(divergence=0.1))
    assert store.put_signals(scope, "q", "a", _signals(divergence=0.9)) is False
    assert store.get_signals(scope, "q", "a")["selfcheck_scores"][0]["divergence_score"] == 0.1


def test_signals_ignores_si_le_format_a_change(tmp_path):
    """Une entrée d'un format plus ancien est un cache miss, pas une relecture
    approximative."""
    store = _store(tmp_path)
    scope = _scope()
    perimes = {**_signals(), "format_version": SIGNALS_FORMAT_VERSION - 1}
    store.put_signals(scope, "q", "a", perimes)
    assert store.get_signals(scope, "q", "a") is None


def test_signals_ignorent_eval_version(tmp_path):
    """La méthodologie d'éval n'a aucune influence sur ce que le RAG et SelfCheck
    produisent : changer d'eval_version ne doit pas invalider les signaux."""
    store = _store(tmp_path)
    store.put_signals(_scope(), "q", "a", _signals())
    autre = _scope()
    autre = replace(autre, eval_version="v99")
    assert store.get_signals(autre, "q", "a") == _signals()


def test_purge_fusion_garde_les_signaux(tmp_path):
    """Le geste de calibration : on purge la fusion, on garde de quoi la rejouer
    sans rappeler le moindre modèle."""
    store = _store(tmp_path)
    scope = _scope()
    store.put_signals(scope, "q", "a", _signals())
    store.put_prediction(scope, "q", "a", True, Verdict.SUPPORTED)
    store.put_matrix(scope, _matrix(), n_examples=1)

    result = store.purge(scope="fusion")

    assert result == {"predictions_deleted": 1, "matrices_deleted": 1}
    assert store.get_verdict(scope, "q", "a") is None
    assert store.get_matrix(scope) is None
    assert store.get_signals(scope, "q", "a") == _signals()


def test_purge_signals_ne_touche_qu_aux_signaux(tmp_path):
    store = _store(tmp_path)
    scope = _scope()
    store.put_signals(scope, "q", "a", _signals())
    store.put_prediction(scope, "q", "a", True, Verdict.SUPPORTED)

    assert store.purge(scope="signals") == {"signals_deleted": 1}
    assert store.get_signals(scope, "q", "a") is None
    assert store.get_verdict(scope, "q", "a") == Verdict.SUPPORTED


def test_purge_scope_invalide(tmp_path):
    with pytest.raises(ValueError, match="scope de purge invalide"):
        _store(tmp_path).purge(scope="n-importe-quoi")
