"""Tests pour `berlue.evaluation.run_eval` — pipeline et store factices, aucune
infra externe requise (pas d'appel LLM, pas de téléchargement de dataset)."""

import threading
import time

import pytest

from berlue.api.schemas import ClaimResult, LLMConfig, PredictOutput
from berlue.core.schemas import Verdict
from berlue.evaluation.result_store import EvalScope, LocalResultStore
from berlue.evaluation.run_eval import (
    _StepTimer,
    aggregate_verdict,
    coverage_report,
    evaluate_baseline_generated,
    evaluate_baseline_generated_matrix,
    evaluate_model,
    evaluate_model_generated,
    evaluate_model_generated_matrix,
    evaluate_model_matrix,
    format_index_ranges,
    group_examples_by_question,
)
from berlue.params import JUDGE_MODEL


def _claim(status: str) -> ClaimResult:
    return ClaimResult(claim_text="x", status=status, fusion_score=0.5, evidence_source="s", evidence_text="e")


class FakePipeline:
    """Renvoie toujours le même statut pour chaque claim — piste aussi le
    nombre d'appels réels, pour vérifier que le cache les évite bien."""

    def __init__(self, status: str = "green"):
        self.status = status
        self.calls: list[tuple[str, str]] = []

    def predict(self, question: str, answer: str | None = None, llm: LLMConfig | None = None) -> PredictOutput:
        self.calls.append((question, answer))
        return PredictOutput(
            question=question,
            llm_used=llm or LLMConfig(),
            full_llm_answer=answer if answer is not None else f"generated:{question}",
            claims=[_claim(self.status)],
        )


class FakeBaseline:
    """Renvoie toujours le même verdict — piste les appels pour vérifier le
    cache."""

    def __init__(self, verdict: Verdict = Verdict.SUPPORTED):
        self.verdict = verdict
        self.calls: list[tuple[str, str]] = []

    def predict(self, question: str, answer: str) -> Verdict:
        self.calls.append((question, answer))
        return self.verdict


class FakeJudgeClient:
    """Renvoie toujours la même réponse brute — piste les appels."""

    def __init__(self, response: str = "TRUE"):
        self.response = response
        self.calls: list[str] = []
        self.warmup_calls = 0

    def generate(self, prompt: str, temperature: float = 0.0, num_predict: int | None = None) -> str:
        self.calls.append(prompt)
        return self.response

    def warmup(self, prompt: str = "Bonjour", temperature: float = 0.0) -> float:
        self.warmup_calls += 1
        return 0.0


class FakeGeneratorClient:
    """Renvoie un texte déterministe distinguable — piste les appels pour
    vérifier que la génération n'a lieu qu'une fois par question (cache)."""

    def __init__(self):
        self.calls: list[str] = []
        self.warmup_calls = 0

    def generate(self, prompt: str, temperature: float = 0.0, num_predict: int | None = None) -> str:
        self.calls.append(prompt)
        return f"generated:{prompt}"

    def warmup(self, prompt: str = "Bonjour", temperature: float = 0.0) -> float:
        self.warmup_calls += 1
        return 0.0


def _examples(n: int) -> list[dict]:
    return [
        {"question": f"q{i}", "answer": f"a{i}", "ground_truth_label": i % 2 == 0, "source": "synthetic"}
        for i in range(n)
    ]


def _scope(**overrides) -> EvalScope:
    defaults = {
        "dataset": "synthetic",
        "ratio": 0.8,
        "model_id": "fake",
        "pipeline_version": "v1",
        "generation_version": "v1",
        "eval_version": "v1",
    }
    return EvalScope(**{**defaults, **overrides})


def _paired_examples(n_questions: int) -> list[dict]:
    """`n_questions` questions distinctes, chacune avec une réponse vraie et
    une fausse — forme requise pour le mode 2 (le juge a besoin des deux)."""
    examples = []
    for i in range(n_questions):
        examples.append({"question": f"q{i}", "answer": f"correcte{i}", "ground_truth_label": True})
        examples.append({"question": f"q{i}", "answer": f"fausse{i}", "ground_truth_label": False})
    return examples


# --- aggregate_verdict ---------------------------------------------------


def test_aggregate_verdict_no_claims_is_undecided():
    assert aggregate_verdict([]) == Verdict.NOT_ENOUGH_INFO


def test_aggregate_verdict_all_green_is_supported():
    assert aggregate_verdict([_claim("green"), _claim("green")]) == Verdict.SUPPORTED


def test_aggregate_verdict_any_orange_is_undecided():
    assert aggregate_verdict([_claim("green"), _claim("orange")]) == Verdict.NOT_ENOUGH_INFO


def test_aggregate_verdict_any_red_wins_over_orange():
    """Le pire cas l'emporte : une seule affirmation contredite suffit, même
    en présence d'une autre incertaine."""
    assert aggregate_verdict([_claim("orange"), _claim("red")]) == Verdict.CONTRADICTED


# --- evaluate_model --------------------------------------------------------


def test_evaluate_model_fills_cache_and_calls_pipeline_once_per_example(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    pipeline = FakePipeline(status="green")

    evaluate_model(pipeline, scope=scope, store=store, test_examples=_examples(3))

    assert len(pipeline.calls) == 3
    for i in range(3):
        assert store.get_verdict(scope, f"q{i}", f"a{i}") == Verdict.SUPPORTED


def test_evaluate_model_skips_pipeline_on_cache_hit(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    pipeline = FakePipeline(status="green")
    examples = _examples(3)

    evaluate_model(pipeline, scope=scope, store=store, test_examples=examples)
    evaluate_model(pipeline, scope=scope, store=store, test_examples=examples)

    assert len(pipeline.calls) == 3, "le pipeline n'aurait pas dû être rappelé au deuxième passage"


def test_evaluate_model_respects_start_end_slice(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    pipeline = FakePipeline(status="green")

    evaluate_model(pipeline, scope=scope, store=store, test_examples=_examples(5), start=1, end=3)

    assert pipeline.calls == [("q1", "a1"), ("q2", "a2")]
    assert store.get_verdict(scope, "q0", "a0") is None
    assert store.get_verdict(scope, "q3", "a3") is None


# --- evaluate_model_matrix --------------------------------------------------


def test_evaluate_model_matrix_raises_if_cache_incomplete(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _examples(3)

    evaluate_model(FakePipeline(), scope=scope, store=store, test_examples=examples, end=2)

    with pytest.raises(ValueError, match="Cache incomplet"):
        evaluate_model_matrix(scope, store=store, test_examples=examples)

    assert store.get_matrix(scope) is None


def test_evaluate_model_matrix_builds_and_stores_matrix_once_complete(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _examples(4)  # 2 ground_truth True (q0, q2), 2 False (q1, q3)

    evaluate_model(FakePipeline(status="green"), scope=scope, store=store, test_examples=examples)
    matrix = evaluate_model_matrix(scope, store=store, test_examples=examples)

    # "green" -> Verdict.SUPPORTED pour toutes les prédictions
    assert matrix.ground_truth_true.predicted_true == 2
    assert matrix.ground_truth_false.predicted_true == 2
    assert store.get_matrix(scope) == matrix


def test_evaluate_model_matrix_dataset_test_size_is_none_for_unknown_dataset(tmp_path):
    """`scope.dataset="synthetic"` n'est pas un dataset réel (`data.KNOWN_DATASETS`)
    — pas de split officiel à comparer, donc `dataset_test_size` reste `None`
    plutôt que de prétendre à tort que ce sous-ensemble de test est complet."""
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _examples(4)

    evaluate_model(FakePipeline(), scope=scope, store=store, test_examples=examples)
    evaluate_model_matrix(scope, store=store, test_examples=examples)

    result = store.list_matrices(dataset=scope.dataset)[0]
    assert result["n_examples"] == 4
    assert result["dataset_test_size"] is None


# --- coverage_report ---------------------------------------------------------


def test_coverage_report_all_missing_when_cache_empty(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _examples(5)

    report = coverage_report(scope, store=store, test_examples=examples)

    assert report == {
        "total": 5,
        "done_indices": [],
        "missing_indices": [0, 1, 2, 3, 4],
        "skipped_indices": [],
    }


def test_coverage_report_reflects_partial_fill(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _examples(5)

    evaluate_model(FakePipeline(), scope=scope, store=store, test_examples=examples, start=1, end=3)
    report = coverage_report(scope, store=store, test_examples=examples)

    assert report == {
        "total": 5,
        "done_indices": [1, 2],
        "missing_indices": [0, 3, 4],
        "skipped_indices": [],
    }


def test_coverage_report_generated_mode_total_matches_start_end_semantics(tmp_path):
    """`total` doit compter *toutes* les questions (y compris celles sans
    référence complète) — c'est ce sur quoi `--start`/`--end` itère
    réellement pour `evaluate_model_generated`, pas seulement les valides."""
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _paired_examples(2) + [{"question": "q_incomplete", "answer": "seule", "ground_truth_label": True}]

    report = coverage_report(scope, store=store, test_examples=examples, mode="generated")

    assert report["total"] == 3
    assert report["skipped_indices"] == [2]  # q_incomplete, triée après q0/q1
    assert report["missing_indices"] == [0, 1]
    assert report["done_indices"] == []


def test_coverage_report_generated_mode_reflects_partial_fill(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _paired_examples(3)

    evaluate_model_generated(
        FakePipeline(),
        scope,
        generator_client=FakeGeneratorClient(),
        judge_client=FakeJudgeClient(response="TRUE"),
        store=store,
        test_examples=examples,
        start=0,
        end=2,
    )
    report = coverage_report(scope, store=store, test_examples=examples, mode="generated")

    assert report == {
        "total": 3,
        "done_indices": [0, 1],
        "missing_indices": [2],
        "skipped_indices": [],
    }


def test_format_index_ranges_compacts_consecutive_runs():
    assert format_index_ranges([0, 1, 2, 5, 6, 9]) == "0-2, 5-6, 9"


def test_format_index_ranges_empty_list():
    assert format_index_ranges([]) == "(aucun)"


# --- group_examples_by_question ---------------------------------------------


def test_group_examples_by_question_separates_correct_and_incorrect():
    examples = [
        {"question": "q1", "answer": "vraie", "ground_truth_label": True},
        {"question": "q1", "answer": "fausse", "ground_truth_label": False},
        {"question": "q2", "answer": "vraie2", "ground_truth_label": True},
    ]

    grouped = group_examples_by_question(examples)

    assert grouped == {
        "q1": {"correct_answers": ["vraie"], "incorrect_answers": ["fausse"]},
        "q2": {"correct_answers": ["vraie2"], "incorrect_answers": []},
    }


# --- evaluate_model_generated (mode 2, Berlue seul) -------------------------


def test_evaluate_model_generated_fills_three_caches_never_baseline(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    pipeline = FakePipeline(status="green")
    judge_client = FakeJudgeClient(response="TRUE")
    generator_client = FakeGeneratorClient()

    evaluate_model_generated(
        pipeline,
        scope,
        judge_client=judge_client,
        generator_client=generator_client,
        store=store,
        test_examples=_paired_examples(1),
    )

    assert store.get_generated_answer("fake", "v1", "q0") is not None
    assert len(generator_client.calls) == 1, "la génération doit passer par generator_client, pas par pipeline"
    assert store.get_generated_berlue_verdict(scope, "q0") == Verdict.SUPPORTED
    assert store.get_judge_verdict("fake", "v1", JUDGE_MODEL, "v1", "q0") == Verdict.SUPPORTED
    # Le point du refactor : la baseline n'est jamais calculée ici — seul
    # `evaluate_baseline_generated` s'en charge, en aval.
    assert store.get_generated_baseline_verdict(scope.dataset, scope.ratio, scope.model_id, "v1", "v1", "q0") is None


def test_evaluate_model_generated_skips_questions_missing_a_reference(tmp_path):
    """Une question sans réponse vraie ET fausse dans le dataset n'a rien à
    comparer, ni de vérité-terrain possible — elle doit être ignorée."""
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = [{"question": "q_incomplete", "answer": "seule reponse", "ground_truth_label": True}]

    evaluate_model_generated(
        FakePipeline(),
        scope,
        generator_client=FakeGeneratorClient(),
        store=store,
        test_examples=examples,
    )

    assert store.get_generated_answer("fake", "v1", "q_incomplete") is None


def test_evaluate_model_generated_generates_once_via_generator_client_not_pipeline(tmp_path):
    """La génération passe par `generator_client`, jamais par `pipeline` (qui
    reste le mock Berlue, réservé au fact-check) — un seul appel par
    question."""
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    pipeline = FakePipeline()
    generator_client = FakeGeneratorClient()

    evaluate_model_generated(
        pipeline,
        scope,
        judge_client=FakeJudgeClient(response="TRUE"),
        generator_client=generator_client,
        store=store,
        test_examples=_paired_examples(1),
    )

    assert len(generator_client.calls) == 1
    assert all(call[1] is not None for call in pipeline.calls), "pipeline ne doit jamais être appelé sans réponse"


def test_evaluate_model_generated_skips_pipeline_on_second_run(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    pipeline = FakePipeline()
    generator_client = FakeGeneratorClient()
    examples = _paired_examples(1)

    evaluate_model_generated(
        pipeline,
        scope,
        judge_client=FakeJudgeClient(response="TRUE"),
        generator_client=generator_client,
        store=store,
        test_examples=examples,
    )
    evaluate_model_generated(
        pipeline,
        scope,
        judge_client=FakeJudgeClient(response="TRUE"),
        generator_client=generator_client,
        store=store,
        test_examples=examples,
    )

    assert len(generator_client.calls) == 1, "génération une seule fois, pas rejouée au 2e passage"
    assert len(pipeline.calls) == 1, "fact-check Berlue une seule fois, pas rejoué au 2e passage"


def test_evaluate_model_generated_respects_start_end_slice(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()

    evaluate_model_generated(
        FakePipeline(),
        scope,
        judge_client=FakeJudgeClient(response="TRUE"),
        generator_client=FakeGeneratorClient(),
        store=store,
        test_examples=_paired_examples(3),
        start=1,
        end=2,
    )

    assert store.get_generated_answer("fake", "v1", "q0") is None
    assert store.get_generated_answer("fake", "v1", "q1") is not None
    assert store.get_generated_answer("fake", "v1", "q2") is None


class SlowThreadSafeClient:
    """Comme `FakeGeneratorClient`/`FakeJudgeClient`, mais dort `delay_s` par
    appel et piste les appels sous verrou — sert à vérifier qu'un
    `concurrency` > 1 exécute vraiment les appels en parallèle (temps total
    << somme des délais individuels), pas juste qu'il ne casse rien."""

    def __init__(self, delay_s: float = 0.05):
        self.delay_s = delay_s
        self.calls: list[str] = []
        self._lock = threading.Lock()
        self.warmup_calls = 0

    def generate(self, prompt: str, temperature: float = 0.0, num_predict: int | None = None) -> str:
        time.sleep(self.delay_s)
        with self._lock:
            self.calls.append(prompt)
        return f"generated:{prompt}"

    def warmup(self, prompt: str = "Bonjour", temperature: float = 0.0) -> float:
        self.warmup_calls += 1
        return 0.0


def test_evaluate_model_generated_concurrency_runs_questions_in_parallel(tmp_path):
    """5 questions, chaque étape à 0.05s/appel : séquentiel (`concurrency=1`)
    prendrait ~0.25s par étape (~0.75s pour les 3), `concurrency=5` doit
    rester largement en dessous — la seule façon d'observer que le pool
    exécute vraiment les workers en parallèle, pas seulement qu'il ne plante
    pas."""
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    generator_client = SlowThreadSafeClient(delay_s=0.05)
    judge_client = SlowThreadSafeClient(delay_s=0.05)

    start = time.monotonic()
    evaluate_model_generated(
        FakePipeline(),
        scope,
        judge_client=judge_client,
        generator_client=generator_client,
        store=store,
        test_examples=_paired_examples(5),
        concurrency=5,
    )
    elapsed = time.monotonic() - start

    assert elapsed < 0.3, f"pas de vrai parallélisme observé ({elapsed:.2f}s pour 5×2 appels à 0.05s)"
    assert len(generator_client.calls) == 5
    assert len(judge_client.calls) == 5
    for i in range(5):
        assert store.get_generated_answer("fake", "v1", f"q{i}") is not None
        assert store.get_judge_verdict("fake", "v1", JUDGE_MODEL, "v1", f"q{i}") is not None


def test_evaluate_model_generated_concurrency_matches_sequential_result(tmp_path):
    """`concurrency=4` doit remplir exactement le même cache que
    `concurrency=1` sur les mêmes exemples (deux stores séparés) — la
    parallélisation ne doit rien changer au résultat, seulement au temps."""
    examples = _paired_examples(6)

    store_sequential = LocalResultStore(db_path=str(tmp_path / "sequential.db"))
    evaluate_model_generated(
        FakePipeline(status="orange"),
        _scope(),
        judge_client=FakeJudgeClient(response="FALSE"),
        generator_client=FakeGeneratorClient(),
        store=store_sequential,
        test_examples=examples,
        concurrency=1,
    )

    store_parallel = LocalResultStore(db_path=str(tmp_path / "parallel.db"))
    evaluate_model_generated(
        FakePipeline(status="orange"),
        _scope(),
        judge_client=FakeJudgeClient(response="FALSE"),
        generator_client=FakeGeneratorClient(),
        store=store_parallel,
        test_examples=examples,
        concurrency=4,
    )

    for i in range(6):
        q = f"q{i}"
        assert store_sequential.get_generated_answer("fake", "v1", q) == store_parallel.get_generated_answer(
            "fake", "v1", q
        )
        assert store_sequential.get_judge_verdict(
            "fake", "v1", JUDGE_MODEL, "v1", q
        ) == store_parallel.get_judge_verdict("fake", "v1", JUDGE_MODEL, "v1", q)


# --- evaluate_model_generated_matrix (mode 2, Berlue-vs-juge seule) ---------


def test_evaluate_model_generated_matrix_raises_if_cache_incomplete(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _paired_examples(2)

    with pytest.raises(ValueError, match="Cache incomplet"):
        evaluate_model_generated_matrix(scope, store=store, test_examples=examples)

    assert store.get_generated_berlue_matrix(scope) is None


def test_evaluate_model_generated_matrix_builds_and_stores_berlue_matrix_only(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _paired_examples(2)

    evaluate_model_generated(
        FakePipeline(status="green"),
        scope,
        judge_client=FakeJudgeClient(response="TRUE"),
        generator_client=FakeGeneratorClient(),
        store=store,
        test_examples=examples,
    )
    berlue_matrix = evaluate_model_generated_matrix(scope, store=store, test_examples=examples)

    # Juge TRUE partout -> ground_truth_true pour les 2 questions, Berlue
    # "SUPPORTED" partout -> tout tombe dans predicted_true.
    assert berlue_matrix.ground_truth_true.predicted_true == 2
    assert store.get_generated_berlue_matrix(scope) == berlue_matrix

    berlue_result = store.list_generated_berlue_matrices(dataset=scope.dataset)[0]
    assert berlue_result["dataset_test_size"] is None  # "synthetic" : pas de split officiel

    # Le point du refactor : cette fonction ne touche jamais la matrice
    # baseline, même si aucune baseline n'a jamais tourné sur ce scope.
    assert store.get_generated_baseline_matrix(scope.dataset, scope.ratio, scope.model_id, "v1", "v1") is None


def test_evaluate_model_generated_matrix_ignores_questions_missing_a_reference(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _paired_examples(1) + [
        {"question": "q_incomplete", "answer": "seule reponse", "ground_truth_label": True}
    ]

    evaluate_model_generated(
        FakePipeline(),
        scope,
        judge_client=FakeJudgeClient(response="TRUE"),
        generator_client=FakeGeneratorClient(),
        store=store,
        test_examples=examples,
    )
    berlue_matrix = evaluate_model_generated_matrix(scope, store=store, test_examples=examples)

    total = (
        berlue_matrix.ground_truth_true.predicted_true
        + berlue_matrix.ground_truth_true.predicted_undecided
        + berlue_matrix.ground_truth_true.predicted_false
        + berlue_matrix.ground_truth_false.predicted_true
        + berlue_matrix.ground_truth_false.predicted_undecided
        + berlue_matrix.ground_truth_false.predicted_false
    )
    assert total == 1, "q_incomplete (une seule réponse) ne doit compter dans aucune matrice"


# --- evaluate_baseline_generated_matrix (mode 2, baseline seule) -----------


def test_evaluate_baseline_generated_matrix_raises_if_cache_incomplete(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _paired_examples(2)

    with pytest.raises(ValueError, match="Cache incomplet"):
        evaluate_baseline_generated_matrix(scope, store=store, test_examples=examples)

    assert store.get_generated_baseline_matrix(scope.dataset, scope.ratio, scope.model_id, "v1", "v1") is None


def test_evaluate_baseline_generated_matrix_never_needs_a_berlue_verdict(tmp_path):
    """Le point du refactor : contrairement à `evaluate_model_generated_matrix`,
    cette matrice se construit uniquement à partir du juge et de la baseline —
    aucun verdict Berlue en cache n'est nécessaire ni lu."""
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _paired_examples(2)

    for question in ("q0", "q1"):
        store.put_generated_answer(scope.model_id, scope.generation_version, question, f"reponse:{question}")
        store.put_judge_verdict(
            scope.model_id, scope.generation_version, JUDGE_MODEL, scope.eval_version, question, Verdict.SUPPORTED
        )
        store.put_generated_baseline_verdict(
            scope.dataset,
            scope.ratio,
            scope.model_id,
            scope.generation_version,
            scope.eval_version,
            question,
            Verdict.SUPPORTED,
        )
        assert store.get_generated_berlue_verdict(scope, question) is None

    baseline_matrix = evaluate_baseline_generated_matrix(scope, store=store, test_examples=examples)

    assert baseline_matrix.ground_truth_true.predicted_true == 2
    assert (
        store.get_generated_baseline_matrix(scope.dataset, scope.ratio, scope.model_id, "v1", "v1") == baseline_matrix
    )


def test_evaluate_baseline_generated_matrix_reuses_cache_from_earlier_calls(tmp_path):
    """Enchaînement réaliste, désormais en 2 temps bien séparés :
    `evaluate_model_generated` remplit génération+Berlue+juge, puis
    `evaluate_baseline_generated` remplit la baseline en aval — la matrice se
    construit ensuite sans rappeler ni le juge ni le classifieur ni Berlue."""
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _paired_examples(2)
    baseline = FakeBaseline(verdict=Verdict.CONTRADICTED)
    judge_client = FakeJudgeClient(response="FALSE")

    evaluate_model_generated(
        FakePipeline(),
        scope,
        judge_client=judge_client,
        generator_client=FakeGeneratorClient(),
        store=store,
        test_examples=examples,
    )
    evaluate_baseline_generated(scope, baseline=baseline, store=store, test_examples=examples)
    n_baseline_calls, n_judge_calls = len(baseline.calls), len(judge_client.calls)

    baseline_matrix = evaluate_baseline_generated_matrix(scope, store=store, test_examples=examples)

    assert len(baseline.calls) == n_baseline_calls  # aucun rappel : baseline déjà en cache
    assert len(judge_client.calls) == n_judge_calls  # aucun rappel : juge déjà en cache
    # Juge FALSE partout -> ground_truth_false ; baseline CONTRADICTED partout -> predicted_false.
    assert baseline_matrix.ground_truth_false.predicted_false == 2


# --- _StepTimer --------------------------------------------------------------


def test_step_timer_summary_before_any_measure():
    timer = _StepTimer()

    assert timer.summary() == "aucun calcul réel (tout venait du cache)"


def test_step_timer_accumulates_total_and_count_per_step():
    timer = _StepTimer()

    with timer.measure("juge"):
        pass
    with timer.measure("juge"):
        pass
    with timer.measure("baseline NLI"):
        pass

    summary = timer.summary()
    assert "juge : " in summary
    assert "n=2" in summary
    assert "baseline NLI : " in summary
    assert "n=1" in summary


# --- warmup et timers détaillés (mode 2) --------------------------------------


def test_evaluate_model_generated_warmup_false_never_calls_warmup(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _paired_examples(1)
    generator_client = FakeGeneratorClient()
    judge_client = FakeJudgeClient()

    evaluate_model_generated(
        FakePipeline(),
        scope,
        judge_client=judge_client,
        generator_client=generator_client,
        store=store,
        test_examples=examples,
    )

    assert generator_client.warmup_calls == 0
    assert judge_client.warmup_calls == 0


def test_evaluate_model_generated_warmup_true_warms_both_clients_once(tmp_path):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _paired_examples(1)
    generator_client = FakeGeneratorClient()
    judge_client = FakeJudgeClient()

    evaluate_model_generated(
        FakePipeline(),
        scope,
        judge_client=judge_client,
        generator_client=generator_client,
        store=store,
        test_examples=examples,
        warmup=True,
    )

    assert generator_client.warmup_calls == 1
    assert judge_client.warmup_calls == 1
    # Le warmup précède la boucle mais ne s'y substitue pas : la génération et
    # le jugement réels ont quand même eu lieu, une fois chacun.
    assert len(generator_client.calls) == 1
    assert len(judge_client.calls) == 1


def test_evaluate_model_generated_prints_detailed_timer_summary(tmp_path, capsys):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _paired_examples(1)

    evaluate_model_generated(
        FakePipeline(),
        scope,
        judge_client=FakeJudgeClient(),
        generator_client=FakeGeneratorClient(),
        store=store,
        test_examples=examples,
    )

    output = capsys.readouterr().out
    assert "⏱" in output
    for step in ("génération", "Berlue", "juge"):
        assert step in output
    # Le point du refactor : la baseline n'apparaît plus dans ce récap, elle
    # n'est jamais calculée ici.
    assert "baseline NLI" not in output


def test_evaluate_baseline_generated_prints_detailed_timer_summary(tmp_path, capsys):
    store = LocalResultStore(db_path=str(tmp_path / "eval.db"))
    scope = _scope()
    examples = _paired_examples(1)
    store.put_generated_answer(scope.model_id, scope.generation_version, "q0", "une reponse")

    evaluate_baseline_generated(scope, baseline=FakeBaseline(), store=store, test_examples=examples)

    output = capsys.readouterr().out
    assert "⏱" in output
    assert "baseline NLI" in output
