"""Test d'intégration bout en bout des deux modes d'évaluation (dataset et
généré) sur une mini tranche du **vrai** jeu de test — marqué `functional` :
télécharge les vrais datasets si absents, nécessite un baseline déjà
entraîné (`make train_baseline`). Le pipeline Berlue reste le mock
(`RandomBerluePipeline` — `HurluBerlu` n'est pas branché sur l'éval), le
LLM-juge est factice ici pour rester reproductible sans dépendre d'un
Ollama disponible sur toute machine de dev/CI.

Lancer avec : pytest tests/test_evaluation_integration.py -m functional
"""

import pytest
from fastapi.testclient import TestClient

from berlue.api.fast import app
from berlue.evaluation.mock_pipeline import RandomBerluePipeline
from berlue.evaluation.result_store import EvalScope, LocalResultStore
from berlue.evaluation.run_eval import (
    evaluate_baseline,
    evaluate_baseline_generated,
    evaluate_baseline_generated_matrix,
    evaluate_model,
    evaluate_model_generated,
    evaluate_model_generated_matrix,
    evaluate_model_matrix,
    get_test_examples,
    group_examples_by_question,
)

pytestmark = pytest.mark.functional

MINI_QUESTIONS = 5


class FakeJudgeClient:
    """Toujours TRUE — déterministe, pour un test reproductible sans dépendre
    d'un vrai Ollama disponible sur toutes les machines de dev/CI."""

    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        return "TRUE"


class FakeGeneratorClient:
    """Génère un texte déterministe — même raison que FakeJudgeClient : ce
    test reste reproductible sur une machine sans Ollama, même si la
    génération n'est plus mockée par défaut (cf. evaluate_model_generated)."""

    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        return f"generated:{prompt}"


def _matrix_total(matrix) -> int:
    return (
        matrix.ground_truth_true.predicted_true
        + matrix.ground_truth_true.predicted_undecided
        + matrix.ground_truth_true.predicted_false
        + matrix.ground_truth_false.predicted_true
        + matrix.ground_truth_false.predicted_undecided
        + matrix.ground_truth_false.predicted_false
    )


def _scope(**overrides) -> EvalScope:
    defaults = {
        "dataset": "halueval",
        "ratio": 0.8,
        "model_id": "random-mock",
        "pipeline_version": "test",
        "generation_version": "test",
        "eval_version": "test",
    }
    return EvalScope(**{**defaults, **overrides})


@pytest.fixture(scope="module")
def mini_test_examples() -> list[dict]:
    """Vraies données (HaluEval, téléchargées/mises en cache une fois si
    absentes) réduites à quelques questions complètes (réponse vraie ET
    fausse) — sans ça le mode généré ignorerait tout (pas de référence pour
    le juge)."""
    test_examples = get_test_examples(dataset="halueval")
    grouped = group_examples_by_question(test_examples)
    valid_questions = sorted(q for q, refs in grouped.items() if refs["correct_answers"] and refs["incorrect_answers"])
    mini_questions = set(valid_questions[:MINI_QUESTIONS])
    return [ex for ex in test_examples if ex["question"] in mini_questions]


@pytest.fixture
def store(tmp_path) -> LocalResultStore:
    return LocalResultStore(db_path=str(tmp_path / "eval.db"))


@pytest.fixture
def api_client(store, monkeypatch):
    """TestClient pointé sur le store isolé de ce test, pas la base locale
    réelle du dev — pas de pollution, pas de purge nécessaire. Force le mode
    mock (`MockBerluePipeline`, léger) au démarrage : ce test ne touche
    jamais `/predict`/`/llms`, pas besoin de charger un vrai RAG/LLM
    d'extraction — sinon ce test échouerait sur une machine sans index FAISS
    déjà construit, pour une raison sans rapport avec ce qu'il vérifie."""
    monkeypatch.setattr("berlue.api.fast.USE_MOCK", True)
    with TestClient(app) as client:
        app.state.result_store = store
        yield client


def test_mode_dataset_end_to_end_on_mini_real_dataset(store, mini_test_examples):
    scope = _scope()

    evaluate_model(RandomBerluePipeline(), scope=scope, store=store, test_examples=mini_test_examples)
    matrix = evaluate_model_matrix(scope, store=store, test_examples=mini_test_examples)

    assert _matrix_total(matrix) == len(mini_test_examples)
    assert store.get_matrix(scope) == matrix

    # `mini_test_examples` n'est qu'un sous-ensemble du vrai split HaluEval —
    # `dataset_test_size` doit refléter le total réel du split officiel
    # (4000 pour halueval@0.8), pas la taille du sous-ensemble utilisé ici.
    result = store.list_matrices(dataset=scope.dataset, ratio=scope.ratio, model_id=scope.model_id)[0]
    assert result["n_examples"] == len(mini_test_examples)
    assert result["dataset_test_size"] == 4000
    assert result["n_examples"] < result["dataset_test_size"]

    baseline_matrix = evaluate_baseline(test_examples=mini_test_examples)
    assert _matrix_total(baseline_matrix) == len(mini_test_examples)


def test_mode_generated_end_to_end_on_mini_real_dataset(store, mini_test_examples):
    """Berlue et baseline sont deux chemins totalement séparés en mode
    généré (même principe qu'en mode dataset ci-dessus) : chacun son
    remplissage de cache, chacun sa matrice, aucun des deux ne calcule ni ne
    stocke rien pour l'autre."""
    scope = _scope()

    evaluate_model_generated(
        RandomBerluePipeline(),
        scope,
        judge_client=FakeJudgeClient(),
        generator_client=FakeGeneratorClient(),
        store=store,
        test_examples=mini_test_examples,
    )
    berlue_matrix = evaluate_model_generated_matrix(scope, store=store, test_examples=mini_test_examples)

    evaluate_baseline_generated(scope, store=store, test_examples=mini_test_examples)
    baseline_matrix = evaluate_baseline_generated_matrix(scope, store=store, test_examples=mini_test_examples)

    n_valid_questions = len({ex["question"] for ex in mini_test_examples})
    assert _matrix_total(berlue_matrix) == n_valid_questions
    assert _matrix_total(baseline_matrix) == n_valid_questions
    assert store.get_generated_berlue_matrix(scope) == berlue_matrix
    assert (
        store.get_generated_baseline_matrix(
            scope.dataset, scope.ratio, scope.model_id, scope.generation_version, scope.eval_version
        )
        == baseline_matrix
    )

    # 2000 questions valides dans le vrai split HaluEval@0.8 (mode généré) —
    # même vérification full/partiel que le mode dataset.
    berlue_result = store.list_generated_berlue_matrices(dataset=scope.dataset, ratio=scope.ratio)[0]
    assert berlue_result["n_examples"] == n_valid_questions
    assert berlue_result["dataset_test_size"] == 2000


def test_both_modes_readable_via_api_on_mini_real_dataset(api_client, store, mini_test_examples):
    """Bout en bout complet : remplit les deux modes, puis relit tout via les
    6 routes API (pas juste le store directement)."""
    scope = _scope()

    evaluate_model(RandomBerluePipeline(), scope=scope, store=store, test_examples=mini_test_examples)
    evaluate_model_matrix(scope, store=store, test_examples=mini_test_examples)

    evaluate_model_generated(
        RandomBerluePipeline(),
        scope,
        judge_client=FakeJudgeClient(),
        generator_client=FakeGeneratorClient(),
        store=store,
        test_examples=mini_test_examples,
    )
    evaluate_model_generated_matrix(scope, store=store, test_examples=mini_test_examples)
    evaluate_baseline_generated(scope, store=store, test_examples=mini_test_examples)
    evaluate_baseline_generated_matrix(scope, store=store, test_examples=mini_test_examples)

    scope_params = {
        "dataset": scope.dataset,
        "ratio": scope.ratio,
        "model_id": scope.model_id,
        "pipeline_version": scope.pipeline_version,
        "eval_version": scope.eval_version,
    }
    generated_scope_params = {**scope_params, "generation_version": scope.generation_version}

    assert api_client.get("/evaluated-models", params={"model_id": "random-mock"}).status_code == 200
    assert api_client.get("/model-evaluation", params=scope_params).status_code == 200
    assert (
        api_client.get("/baseline-evaluation", params={"dataset": scope.dataset, "ratio": scope.ratio}).status_code
        == 200
    )

    assert api_client.get("/evaluated-models-generated", params={"model_id": "random-mock"}).status_code == 200
    assert api_client.get("/model-evaluation-generated", params=generated_scope_params).status_code == 200
    assert (
        api_client.get(
            "/baseline-evaluation-generated",
            params={
                "dataset": scope.dataset,
                "ratio": scope.ratio,
                "model_id": scope.model_id,
                "generation_version": scope.generation_version,
                "eval_version": scope.eval_version,
            },
        ).status_code
        == 200
    )
