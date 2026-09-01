"""Évaluation offline du pipeline Berlue complet vs baseline NLI sur des exemples
labellisés (HaluEval/TruthfulQA) — produit les chiffres comparatifs utilisés pour
la présentation finale.

Lancer avec : python -m berlue.evaluation.run_eval

Params utilisés indirectement (`berlue.params`, via `evaluation.data`,
`nli_baseline.predict` et `evaluation.result_store`) : `EVAL_DATASETS`,
`HALUEVAL_URL`, `HALUEVAL_DATA_PATH`, `TRUTHFULQA_URL`, `TRUTHFULQA_DATA_PATH`,
`TRAIN_RATIO`, `NLI_BASELINE_PATH`, `MLOPS_DB_PATH`, `PIPELINE_VERSION`,
`GENERATION_VERSION`, `EVAL_VERSION`.
"""

from berlue.evaluation.timing import mark

mark("module import start")

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import lru_cache

from berlue.api.schemas import ClaimResult, ConfusionMatrix
from berlue.core.schemas import Verdict
from berlue.evaluation.data import load_labeled_examples, split_train_test
from berlue.evaluation.judge import judge_answer
from berlue.evaluation.metrics import build_confusion_matrix
from berlue.evaluation.result_store import EvalScope, LocalResultStore, get_result_store
from berlue.llm.client import OllamaClient
from berlue.nli_baseline.predict import NliBaseline
from berlue.params import JUDGE_MODEL

mark("module imports done")

logger = logging.getLogger(__name__)

# Flush périodique du registre de scopes GCP (no-op en local) dans les
# boucles d'éval — pas de flush par ligne (cf. gcp_result_store.py), pas
# seulement en fin de boucle non plus (une longue boucle interrompue par
# autre chose qu'un Ctrl+C — ex. kill -9 — ne passerait pas par le `finally`).
_REGISTRY_FLUSH_EVERY_N_ITEMS = 20


class _StepTimer:
    """Chronomètre nommé par étape (`génération`, `juge`, `baseline NLI`,
    `Berlue`...) — accumule durée totale et nombre d'appels par étape au fil
    d'une boucle d'éval, pour un récapitulatif détaillé en fin de run (temps
    moyen/total par tâche) plutôt qu'un seul temps englobant (`time make
    ...`). Ne mesure que les calculs réels : un appel jamais fait (cache hit)
    n'entre jamais dans `measure()`, donc ne compte pas. `measure()` est
    thread-safe (verrou sur l'accumulation) — appelable depuis plusieurs
    workers d'un `ThreadPoolExecutor` en parallèle."""

    def __init__(self):
        self._totals: dict[str, float] = {}
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    @contextmanager
    def measure(self, step: str):
        start = time.perf_counter()
        yield
        elapsed = time.perf_counter() - start
        with self._lock:
            self._totals[step] = self._totals.get(step, 0.0) + elapsed
            self._counts[step] = self._counts.get(step, 0) + 1

    def summary(self) -> str:
        if not self._counts:
            return "aucun calcul réel (tout venait du cache)"
        return " | ".join(
            f"{step} : {total:.2f}s total, {total / self._counts[step]:.3f}s/appel (n={self._counts[step]})"
            for step, total in self._totals.items()
        )


def aggregate_verdict(claims: list[ClaimResult]) -> Verdict:
    """Réduit les verdicts par affirmation d'une réponse (`predict()` en retourne
    un par claim extraite) en un seul verdict comparable au label vérité-terrain
    de l'exemple : une seule affirmation contredite suffit à considérer toute la
    réponse comme fausse (pire cas), sinon une seule incertaine suffit à rendre
    la réponse indécise — sans affirmation, rien à valider.
    """
    if not claims:
        return Verdict.NOT_ENOUGH_INFO

    statuses = {claim.status for claim in claims}
    if "red" in statuses:
        return Verdict.CONTRADICTED
    if "orange" in statuses:
        return Verdict.NOT_ENOUGH_INFO
    return Verdict.SUPPORTED


@lru_cache(maxsize=8)
def _cached_split(dataset: str | None, ratio: float | None) -> tuple[dict, ...]:
    """Calcule et met en cache (mémoire du process, par `(dataset, ratio)`) le
    split de test — chargement/split d'un dataset est indépendant de tout ce
    qui suit (scope, model_id...), donc réutilisable tel quel entre appels.
    Sans ce cache, un process de longue durée (le service Cloud Run d'éval)
    recalculerait ce split identique à chaque requête. `maxsize=8` : large
    marge (2 datasets connus × quelques ratios distincts par session),
    jamais un vrai souci mémoire (le split est petit).

    Retourne un tuple (immuable, hashable — exigé pour un retour de fonction
    mise en cache) ; `get_test_examples` le reconvertit en `list`. Les dicts
    eux-mêmes restent partagés entre appels — sûr ici, rien dans ce module ne
    les mute (uniquement des lectures, `ex["question"]`/`ex["answer"]`/...)."""
    load_kwargs = {} if dataset is None else {"datasets": [dataset]}
    split_kwargs = {} if ratio is None else {"train_ratio": ratio}
    _, test_examples = split_train_test(load_labeled_examples(**load_kwargs), **split_kwargs)
    return tuple(test_examples)


def get_test_examples(
    test_examples: list[dict] | None = None,
    dataset: str | None = None,
    ratio: float | None = None,
) -> list[dict]:
    """Retourne `test_examples` tel quel s'il est fourni, sinon le split de
    test mis en cache pour `(dataset, ratio)` (cf. `_cached_split`) — évite de
    télécharger/resplitter deux fois quand baseline et modèle sont évalués
    sur le même jeu de test, ou entre deux requêtes successives sur un
    process de longue durée.

    `dataset`/`ratio` ciblent un scope précis (défaut : le premier dataset de
    `params.EVAL_DATASETS`/`params.TRAIN_RATIO`) — nécessaire pour comparer
    la baseline à un scope Berlue déjà évalué avec des paramètres différents
    des défauts globaux. Un seul dataset à la fois : les résultats ne
    mélangent jamais plusieurs datasets, cf. docs/evaluation/storage.md.
    """
    if test_examples is not None:
        return test_examples

    return list(_cached_split(dataset, ratio))


def _official_dataset_test_size(scope: EvalScope) -> int | None:
    """Taille du split de test officiel complet pour `scope.dataset`/
    `scope.ratio` — indépendante de tout `test_examples` fourni en override
    (tests, démos), donc utilisable pour savoir si une matrice construite sur
    un sous-ensemble couvre le split complet ou non (cf.
    docs/evaluation/storage.md). Le split est déterministe (seed fixe,
    versions numpy/pandas/scikit-learn épinglées) — deux machines qui
    l'appellent obtiennent le même total.

    `None` si `scope.dataset` n'est pas un dataset réel connu (ex. tests
    unitaires utilisant un nom fictif) — pas de total officiel dans ce cas.
    """
    try:
        official = get_test_examples(None, dataset=scope.dataset, ratio=scope.ratio)
    except ValueError:
        return None
    return len(official)


def _official_valid_question_count(scope: EvalScope) -> int | None:
    """Équivalent de `_official_dataset_test_size` pour le mode généré : nombre
    de questions du split de test officiel complet ayant au moins une
    réponse de référence correcte ET incorrecte (seules celles-ci sont
    traitées, cf. `evaluate_model_generated`) — même convention que
    `n_examples` sur `eval_matrices_generated_berlue`/`_baseline`."""
    try:
        official = get_test_examples(None, dataset=scope.dataset, ratio=scope.ratio)
    except ValueError:
        return None
    grouped = group_examples_by_question(official)
    return sum(1 for refs in grouped.values() if refs["correct_answers"] and refs["incorrect_answers"])


def run_confusion_matrix_eval(test_examples: list[dict], predict_one: Callable[[dict], Verdict]) -> ConfusionMatrix:
    """Évalue `predict_one(example) -> Verdict` sur `test_examples` et retourne
    la matrice de confusion correspondante.
    """
    ground_truths = [ex["ground_truth_label"] for ex in test_examples]
    predictions = [predict_one(ex) for ex in test_examples]
    return build_confusion_matrix(ground_truths, predictions)


def evaluate_baseline(
    baseline: NliBaseline | None = None,
    test_examples: list[dict] | None = None,
    dataset: str | None = None,
    ratio: float | None = None,
) -> ConfusionMatrix:
    """Évalue la baseline NLI seule sur le jeu de test (un seul dataset,
    partie non utilisée par `nli_baseline.train.train_baseline`) et retourne
    sa matrice de confusion. `dataset`/`ratio` ciblent un scope précis (cf.
    `get_test_examples`).
    """
    baseline = baseline or NliBaseline()
    test_examples = get_test_examples(test_examples, dataset=dataset, ratio=ratio)

    logger.info("🔍 Évaluation NLI Baseline sur %d exemples...", len(test_examples))
    start = time.perf_counter()
    matrix = run_confusion_matrix_eval(test_examples, lambda ex: baseline.predict(ex["question"], ex["answer"]))
    elapsed = time.perf_counter() - start
    per_example = f"{elapsed / len(test_examples):.4f}s/exemple" if test_examples else "n/a"
    print(f"✅ Évaluation terminée. ⏱ baseline NLI : {elapsed:.2f}s total, {per_example} (n={len(test_examples)}).")

    return matrix


def evaluate_model(
    pipeline,
    scope: EvalScope,
    start: int = 0,
    end: int | None = None,
    store: LocalResultStore | None = None,
    test_examples: list[dict] | None = None,
) -> None:
    """Remplit le cache de prédictions de `scope` sur `[start:end]` du jeu de
    test — pour chaque exemple, vérifie le cache avant d'appeler le pipeline
    (`pipeline.predict(question, answer)`, même contrat que
    `NliBaseline.predict` : on vérifie la réponse du dataset, on n'en génère
    pas une nouvelle). Ne construit pas de matrice de confusion — cf.
    `evaluate_model_matrix` pour ça, une fois le scope complet.

    Chaque prédiction est stockée immédiatement après son calcul (pas de
    buffer) : un Ctrl+C ne perd donc que la prédiction en cours, relancer
    (même scope, même tranche ou une autre) reprend là où c'était.
    """
    store = store or get_result_store()
    mark("store obtenu")
    test_examples = get_test_examples(test_examples, dataset=scope.dataset, ratio=scope.ratio)
    mark("dataset chargé")
    end = len(test_examples) if end is None else end
    subset = test_examples[start:end]

    logger.info(
        "🔍 Évaluation du pipeline Berlue sur [%d:%d] (%d exemples, scope=%s)...", start, end, len(subset), scope
    )

    timer = _StepTimer()
    n_cached, n_computed = 0, 0
    try:
        for i, ex in enumerate(subset):
            question, answer = ex["question"], ex["answer"]

            with timer.measure("store I/O (get)"):
                verdict = store.get_verdict(scope, question, answer)
            if verdict is not None:
                n_cached += 1
                continue

            with timer.measure("Berlue"):
                verdict = aggregate_verdict(pipeline.predict(question, answer).claims)
            with timer.measure("store I/O (put)"):
                store.put_prediction(scope, question, answer, ex["ground_truth_label"], verdict)
            n_computed += 1

            if (i + 1) % _REGISTRY_FLUSH_EVERY_N_ITEMS == 0:
                store.flush_registry()
        mark("boucle terminée")
    finally:
        store.flush_registry()
    mark("registre flushé (fin)")

    print(
        f"✅ Terminé : {n_cached} déjà en cache, {n_computed} nouvelle(s) prédiction(s) calculée(s) et stockée(s). "
        f"⏱ {timer.summary()}"
    )


def evaluate_model_matrix(
    scope: EvalScope, store: LocalResultStore | None = None, test_examples: list[dict] | None = None
) -> ConfusionMatrix:
    """Construit et stocke la matrice de confusion finale d'un `scope`, à
    partir de tout ce qui est déjà en cache — n'appelle jamais le pipeline.

    Lève une erreur explicite si le cache est incomplet (une ou plusieurs
    questions du jeu de test du scope n'ont pas encore de prédiction stockée)
    plutôt que de calculer silencieusement une matrice partielle — lancer
    `evaluate_model` pour compléter le scope avant de rappeler cette fonction.
    """
    store = store or get_result_store()
    test_examples = get_test_examples(test_examples, dataset=scope.dataset, ratio=scope.ratio)

    missing = 0
    ground_truths = []
    predictions = []
    for ex in test_examples:
        verdict = store.get_verdict(scope, ex["question"], ex["answer"])
        if verdict is None:
            missing += 1
            continue
        ground_truths.append(ex["ground_truth_label"])
        predictions.append(verdict)

    if missing:
        raise ValueError(
            f"❌ Cache incomplet pour {scope} : {missing}/{len(test_examples)} prédictions manquantes. "
            "Lancer `evaluate_model` sur les tranches manquantes avant de construire la matrice."
        )

    matrix = build_confusion_matrix(ground_truths, predictions)
    dataset_test_size = _official_dataset_test_size(scope)
    store.put_matrix(scope, matrix, n_examples=len(test_examples), dataset_test_size=dataset_test_size)

    full = (
        ""
        if dataset_test_size is None
        else " (split complet)"
        if len(test_examples) == dataset_test_size
        else " (PARTIEL)"
    )
    print(f"✅ Matrice construite et stockée pour {scope} ({len(test_examples)} exemples{full}).")
    return matrix


def coverage_report(
    scope: EvalScope,
    store: LocalResultStore | None = None,
    test_examples: list[dict] | None = None,
    mode: str = "dataset",
) -> dict:
    """Combien d'éléments un scope compte au total (pour préparer un
    découpage `--start`/`--end` — sans rien calculer), et lesquels sont déjà
    en cache / manquent — une seule requête groupée, jamais un
    `get_verdict`/`get_generated_answer` par élément.

    `mode="dataset"` (défaut) : `total` = nombre de lignes (question+réponse)
    du split de test, mêmes index que `evaluate_model`/`--start`/`--end`.
    `mode="generated"` : `total` = nombre de questions distinctes, mêmes
    index que `evaluate_model_generated`/`--start`/`--end` (qui itère sur
    *toutes* les questions, y compris celles sans référence complète —
    silencieusement ignorées à l'exécution, cf. `skipped_indices`
    ci-dessous ; ce n'est donc pas le même total que
    `_official_valid_question_count`). "Fait" = réponse déjà générée
    (`llm_answers`) — le premier des 3 axes du mode généré, donc
    l'indicateur le plus représentatif de "cette question a déjà été
    traitée".

    Retourne `{"total", "done_indices", "missing_indices",
    "skipped_indices"}`, index dans l'ordre déterministe du split train/test
    (mêmes index que `--start`/`--end`) — `skipped_indices` toujours vide en
    mode dataset (pas de notion de référence incomplète pour ce mode)."""
    store = store or get_result_store()
    test_examples = get_test_examples(test_examples, dataset=scope.dataset, ratio=scope.ratio)

    if mode == "generated":
        grouped = group_examples_by_question(test_examples)
        questions = sorted(grouped)  # même ordre que evaluate_model_generated
        answered = store.list_generated_answers(scope.model_id, scope.generation_version)

        done_indices, missing_indices, skipped_indices = [], [], []
        for i, question in enumerate(questions):
            refs = grouped[question]
            if not refs["correct_answers"] or not refs["incorrect_answers"]:
                skipped_indices.append(i)
                continue
            (done_indices if question in answered else missing_indices).append(i)

        return {
            "total": len(questions),
            "done_indices": done_indices,
            "missing_indices": missing_indices,
            "skipped_indices": skipped_indices,
        }

    cached_keys = {(p["question"], p["answer"]) for p in store.list_predictions(scope)}

    done_indices = []
    missing_indices = []
    for i, ex in enumerate(test_examples):
        target = done_indices if (ex["question"], ex["answer"]) in cached_keys else missing_indices
        target.append(i)

    return {
        "total": len(test_examples),
        "done_indices": done_indices,
        "missing_indices": missing_indices,
        "skipped_indices": [],
    }


def format_index_ranges(indices: list[int]) -> str:
    """Compacte une liste d'index triés en plages lisibles — `[0,1,2,5,6,9]`
    devient `"0-2, 5-6, 9"`."""
    if not indices:
        return "(aucun)"

    ranges = []
    start = prev = indices[0]
    for i in indices[1:]:
        if i == prev + 1:
            prev = i
            continue
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = i
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(ranges)


def group_examples_by_question(test_examples: list[dict]) -> dict[str, dict[str, list[str]]]:
    """Regroupe `test_examples` (une ligne par (question, réponse)) par
    question unique — nécessaire au mode 2, qui a besoin de toutes les
    réponses de référence vraies ET fausses d'une question ensemble (pour le
    juge), contrairement au mode 1 qui traite chaque ligne indépendamment.
    """
    grouped: dict[str, dict[str, list[str]]] = {}
    for ex in test_examples:
        entry = grouped.setdefault(ex["question"], {"correct_answers": [], "incorrect_answers": []})
        key = "correct_answers" if ex["ground_truth_label"] else "incorrect_answers"
        entry[key].append(ex["answer"])
    return grouped


GENERATION_INSTRUCTION = "Answer clearly and concisely, in 3 to 5 sentences maximum."
# Large marge au-dessus d'une réponse de 3 à 5 phrases légitime (mesuré : 50 à
# 150 tokens en usage réel) — borne le pire cas d'une réponse qui ne suit pas
# la consigne plutôt qu'un plafond serré (cf. OllamaClient.generate).
GENERATION_MAX_TOKENS = 300


def evaluate_model_generated(
    pipeline,
    scope: EvalScope,
    judge_model: str = JUDGE_MODEL,
    judge_client=None,
    generator_client=None,
    start: int = 0,
    end: int | None = None,
    store: LocalResultStore | None = None,
    test_examples: list[dict] | None = None,
    warmup: bool = False,
    concurrency: int = 1,
) -> None:
    """Mode 2, Berlue seul : sur `[start:end]`, génère une réponse pour
    chaque question (vrai appel LLM — `generator_client`, `scope.model_id`
    par défaut), puis la fait fact-checker par Berlue (`HurluBerlu`, via
    `BerluePipeline`), puis juger par un LLM-juge ancré sur les
    réponses de référence du dataset (vérité-terrain de substitution) — un
    passage complet par étape sur l'ensemble des questions, pas les 3 étapes
    question par question (chaque étape ne dépend que de la réponse générée,
    jamais du résultat d'une autre étape). Remplit les 3 caches
    correspondants (`llm_answers`, `eval_berlue_generated`, `judge_verdicts`)
    — ne construit pas de matrice.

    `concurrency` : nombre de questions traitées en parallèle *au sein* de
    chaque étape (`ThreadPoolExecutor`) — 1 par défaut (séquentiel,
    comportement historique). À aligner sur le `OLLAMA_NUM_PARALLEL` réel du
    serveur ciblé, pas une valeur arbitraire (cf.
    docs/gcp/ollama-gpu-parallelism.md) : au-delà, les requêtes en surplus
    s'empilent en file côté serveur sans rien gagner.

    Ne touche jamais la baseline — c'est le rôle exclusif d'`evaluate_baseline_generated`,
    en aval, sur la réponse déjà générée ici (même principe qu'en mode 1 :
    `evaluate_model`/`evaluate_baseline` sont deux chemins totalement séparés).

    Questions sans au moins une réponse vraie ET une réponse fausse dans le
    dataset sont ignorées (rien à comparer, pas de juge possible).

    `warmup=True` charge `generator_client`/`judge_client` en VRAM (appel
    jetable chacun) avant de démarrer la boucle chronométrée — sans ça, le
    premier appel réel de chaque modèle paierait ce chargement et fausserait
    le récapitulatif de temps affiché en fin de run (cf. `OllamaClient.warmup`).
    """
    store = store or get_result_store()
    # Construits ici plutôt que de laisser judge_answer/l'appel de génération
    # défaulter tout seuls : sinon un judge_model/model_id différent du défaut
    # sans client explicite ferait exécuter un modèle différent de celui
    # utilisé comme clé de cache.
    judge_client = judge_client or OllamaClient(model=judge_model)
    generator_client = generator_client or OllamaClient(model=scope.model_id)
    test_examples = get_test_examples(test_examples, dataset=scope.dataset, ratio=scope.ratio)

    if warmup:
        generation_warmup = generator_client.warmup()
        judge_warmup = judge_client.warmup()
        logger.info("🔥 Warmup : %.2fs (génération), %.2fs (juge).", generation_warmup, judge_warmup)

    grouped = group_examples_by_question(test_examples)
    questions = sorted(grouped)  # ordre déterministe, reproductible entre invocations
    end = len(questions) if end is None else end
    candidates = questions[start:end]
    subset = [q for q in candidates if grouped[q]["correct_answers"] and grouped[q]["incorrect_answers"]]
    n_skipped = len(candidates) - len(subset)

    logger.info(
        "🔍 Évaluation générée+juge sur [%d:%d] (%d questions, scope=%s, concurrency=%d)...",
        start,
        end,
        len(candidates),
        scope,
        concurrency,
    )

    # Une étape à la fois sur la totalité de `subset`, plutôt que les 3 étapes
    # question par question — chaque étape ne dépend que de la réponse
    # générée (jamais du verdict d'une autre étape). Au sein d'une étape, les
    # questions pas encore en cache sont dépilées par un pool de threads
    # (cf. docs/gcp/ollama-gpu-parallelism.md pour pourquoi séquencer les
    # étapes plutôt que les entrelacer). Le cache par étape (déjà en place)
    # rend ce découpage transparent : reprendre un run interrompu au milieu
    # d'une étape saute exactement les mêmes calculs déjà faits.
    timer = _StepTimer()
    registry_lock = threading.Lock()
    n_flushed = {"n": 0}

    def _maybe_flush_registry():
        with registry_lock:
            n_flushed["n"] += 1
            if n_flushed["n"] % _REGISTRY_FLUSH_EVERY_N_ITEMS == 0:
                store.flush_registry()

    def _run_pool(todo: list[str], worker: Callable[[str], None]) -> None:
        if not todo:
            return
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            # list() force la consommation de map() : une exception dans un
            # worker doit remonter ici (et donc via le `finally` plus bas),
            # pas rester silencieusement dans un Future jamais lu.
            list(executor.map(worker, todo))

    def _generate_one(question: str) -> None:
        prompt = f"{question}\n\n[Instruction: {GENERATION_INSTRUCTION}]"
        with timer.measure("génération"):
            generated_answer = generator_client.generate(prompt=prompt, num_predict=GENERATION_MAX_TOKENS)
        store.put_generated_answer(scope.model_id, scope.generation_version, question, generated_answer)
        _maybe_flush_registry()

    def _berlue_one(question: str) -> None:
        # `pipeline.predict` doit être thread-safe pour un `concurrency` > 1 —
        # vrai pour `BerluePipeline` (appels LLM sans état partagé, comme
        # `generator_client`/`judge_client` ; `RagRetriever.verify_claim`
        # n'écrit dans aucun état d'instance partagé non plus).
        generated_answer = store.get_generated_answer(scope.model_id, scope.generation_version, question)
        with timer.measure("Berlue"):
            berlue_verdict = aggregate_verdict(pipeline.predict(question, generated_answer).claims)
        store.put_generated_berlue_verdict(scope, question, berlue_verdict)
        _maybe_flush_registry()

    def _judge_one(question: str) -> None:
        refs = grouped[question]
        generated_answer = store.get_generated_answer(scope.model_id, scope.generation_version, question)
        with timer.measure("juge"):
            judge_verdict = judge_answer(
                question,
                refs["correct_answers"][0],
                refs["incorrect_answers"],
                generated_answer,
                client=judge_client,
            )
        store.put_judge_verdict(
            scope.model_id, scope.generation_version, judge_model, scope.eval_version, question, judge_verdict
        )
        _maybe_flush_registry()

    try:
        _run_pool(
            [q for q in subset if store.get_generated_answer(scope.model_id, scope.generation_version, q) is None],
            _generate_one,
        )
        _run_pool(
            [q for q in subset if store.get_generated_berlue_verdict(scope, q) is None],
            _berlue_one,
        )
        _run_pool(
            [
                q
                for q in subset
                if store.get_judge_verdict(scope.model_id, scope.generation_version, judge_model, scope.eval_version, q)
                is None
            ],
            _judge_one,
        )
    finally:
        store.flush_registry()

    print(
        f"✅ Terminé : {len(subset)} question(s) traitée(s), {n_skipped} ignorée(s) (référence manquante). "
        f"⏱ {timer.summary()}"
    )


def evaluate_baseline_generated(
    scope: EvalScope,
    baseline: NliBaseline | None = None,
    start: int = 0,
    end: int | None = None,
    store: LocalResultStore | None = None,
    test_examples: list[dict] | None = None,
) -> None:
    """Mode 2, baseline seule : classifie par la baseline NLI les réponses
    déjà générées (`llm_answers`) pour ce scope, sans regénérer ni appeler
    le juge/Berlue — c'est le **seul** endroit où la baseline mode 2 est
    calculée (`evaluate_model_generated` ne s'occupe que de Berlue, jamais
    de la baseline, même principe qu'en mode 1 avec `evaluate_model`/
    `evaluate_baseline`). Questions sans réponse déjà générée : ignorées
    (rien à classifier)."""
    store = store or get_result_store()
    baseline = baseline or NliBaseline()
    test_examples = get_test_examples(test_examples, dataset=scope.dataset, ratio=scope.ratio)

    grouped = group_examples_by_question(test_examples)
    questions = sorted(q for q, refs in grouped.items() if refs["correct_answers"] and refs["incorrect_answers"])
    end = len(questions) if end is None else end
    subset = questions[start:end]

    logger.info("🔍 Baseline (mode généré) sur [%d:%d] (%d questions, scope=%s)...", start, end, len(subset), scope)

    timer = _StepTimer()
    n_classified, n_skipped = 0, 0
    for question in subset:
        generated_answer = store.get_generated_answer(scope.model_id, scope.generation_version, question)
        if generated_answer is None:
            n_skipped += 1
            continue

        if (
            store.get_generated_baseline_verdict(
                scope.dataset, scope.ratio, scope.model_id, scope.generation_version, scope.eval_version, question
            )
            is None
        ):
            with timer.measure("baseline NLI"):
                baseline_verdict = baseline.predict(question, generated_answer)
            store.put_generated_baseline_verdict(
                scope.dataset,
                scope.ratio,
                scope.model_id,
                scope.generation_version,
                scope.eval_version,
                question,
                baseline_verdict,
            )
            n_classified += 1

    print(
        f"✅ Terminé : {n_classified} question(s) classifiée(s), {n_skipped} ignorée(s) (réponse pas encore générée). "
        f"⏱ {timer.summary()}"
    )


def evaluate_baseline_generated_matrix(
    scope: EvalScope,
    judge_model: str = JUDGE_MODEL,
    store: LocalResultStore | None = None,
    test_examples: list[dict] | None = None,
) -> ConfusionMatrix:
    """Construit et stocke la matrice baseline-vs-juge (mode 2), à partir de
    tout ce qui est déjà en cache (`eval_baseline_generated`, `judge_verdicts`)
    — n'appelle jamais le classifieur ni le juge, et ne dépend jamais du
    verdict Berlue : équivalent mode généré d'`evaluate_baseline`, chemin
    totalement séparé d'`evaluate_model_generated_matrix` (Berlue-vs-juge).

    Lève une erreur explicite si une question valide (avec les deux
    références du dataset) n'a pas encore ses 2 verdicts en cache (juge,
    baseline) plutôt que de calculer silencieusement une matrice partielle.
    """
    store = store or get_result_store()
    test_examples = get_test_examples(test_examples, dataset=scope.dataset, ratio=scope.ratio)

    grouped = group_examples_by_question(test_examples)
    valid_questions = sorted(q for q, refs in grouped.items() if refs["correct_answers"] and refs["incorrect_answers"])

    missing = 0
    ground_truths = []
    baseline_predictions = []
    for question in valid_questions:
        judge_verdict = store.get_judge_verdict(
            scope.model_id, scope.generation_version, judge_model, scope.eval_version, question
        )
        baseline_verdict = store.get_generated_baseline_verdict(
            scope.dataset, scope.ratio, scope.model_id, scope.generation_version, scope.eval_version, question
        )

        if judge_verdict is None or baseline_verdict is None:
            missing += 1
            continue

        ground_truths.append(judge_verdict == Verdict.SUPPORTED)
        baseline_predictions.append(baseline_verdict)

    if missing:
        raise ValueError(
            f"❌ Cache incomplet pour {scope} (mode généré, baseline) : {missing}/{len(valid_questions)} "
            "question(s) manquante(s). Lancer `evaluate_model_generated` (pour le juge) et/ou "
            "`evaluate_baseline_generated` (pour la baseline) sur les tranches manquantes avant "
            "de construire la matrice."
        )

    baseline_matrix = build_confusion_matrix(ground_truths, baseline_predictions)
    dataset_test_size = _official_valid_question_count(scope)
    store.put_generated_baseline_matrix(
        scope.dataset,
        scope.ratio,
        scope.model_id,
        scope.generation_version,
        scope.eval_version,
        baseline_matrix,
        n_examples=len(valid_questions),
        dataset_test_size=dataset_test_size,
    )

    full = (
        ""
        if dataset_test_size is None
        else " (split complet)"
        if len(valid_questions) == dataset_test_size
        else " (PARTIEL)"
    )
    print(
        f"✅ Matrice baseline (mode généré) construite et stockée pour {scope} "
        f"({len(valid_questions)} questions{full})."
    )
    return baseline_matrix


def evaluate_model_generated_matrix(
    scope: EvalScope,
    judge_model: str = JUDGE_MODEL,
    store: LocalResultStore | None = None,
    test_examples: list[dict] | None = None,
) -> ConfusionMatrix:
    """Construit et stocke la matrice Berlue-vs-juge (mode 2), à partir de
    tout ce qui est déjà en cache (`judge_verdicts`, `eval_berlue_generated`)
    — n'appelle jamais le pipeline ni le juge, et ne dépend jamais du verdict
    baseline : chemin totalement séparé d'`evaluate_baseline_generated_matrix`
    (baseline-vs-juge).

    Lève une erreur explicite si une question valide (avec les deux
    références du dataset) n'a pas encore ses 2 verdicts en cache (juge,
    Berlue) plutôt que de calculer silencieusement une matrice partielle.
    """
    store = store or get_result_store()
    test_examples = get_test_examples(test_examples, dataset=scope.dataset, ratio=scope.ratio)

    grouped = group_examples_by_question(test_examples)
    valid_questions = sorted(q for q, refs in grouped.items() if refs["correct_answers"] and refs["incorrect_answers"])

    missing = 0
    ground_truths = []
    berlue_predictions = []
    for question in valid_questions:
        judge_verdict = store.get_judge_verdict(
            scope.model_id, scope.generation_version, judge_model, scope.eval_version, question
        )
        berlue_verdict = store.get_generated_berlue_verdict(scope, question)

        if judge_verdict is None or berlue_verdict is None:
            missing += 1
            continue

        ground_truths.append(judge_verdict == Verdict.SUPPORTED)
        berlue_predictions.append(berlue_verdict)

    if missing:
        raise ValueError(
            f"❌ Cache incomplet pour {scope} (mode généré) : {missing}/{len(valid_questions)} "
            "question(s) manquante(s). Lancer `evaluate_model_generated` sur les tranches "
            "manquantes avant de construire la matrice."
        )

    berlue_matrix = build_confusion_matrix(ground_truths, berlue_predictions)
    dataset_test_size = _official_valid_question_count(scope)

    store.put_generated_berlue_matrix(
        scope, berlue_matrix, n_examples=len(valid_questions), dataset_test_size=dataset_test_size
    )

    full = (
        ""
        if dataset_test_size is None
        else " (split complet)"
        if len(valid_questions) == dataset_test_size
        else " (PARTIEL)"
    )
    print(
        f"✅ Matrice Berlue (mode généré) construite et stockée pour {scope} ({len(valid_questions)} questions{full})."
    )
    return berlue_matrix


def build_arg_parser():
    """Construit le parser CLI complet — séparé de `run_from_args` pour être
    réutilisable tel quel par `berlue.api.eval_service` (HTTP), qui construit
    ses propres `argv` depuis un corps JSON puis appelle
    `parser.parse_args(argv)` exactement comme le ferait la CLI."""
    import argparse

    from berlue.params import EVAL_VERSION, GENERATION_VERSION, PIPELINE_VERSION, TRAIN_RATIO

    parser = argparse.ArgumentParser(description="Évalue le pipeline Berlue (HurluBerlu) sur un scope.")
    parser.add_argument("--dataset", default="halueval", help="Un seul dataset (jamais mélangé).")
    parser.add_argument("--ratio", type=float, default=TRAIN_RATIO, help="Ratio train/test.")
    parser.add_argument("--model-id", default="random-mock", help="Identité du modèle évalué.")
    parser.add_argument("--pipeline-version", default=PIPELINE_VERSION, help="Version du pipeline Berlue.")
    parser.add_argument("--generation-version", default=GENERATION_VERSION, help="Version de la génération LLM.")
    parser.add_argument("--eval-version", default=EVAL_VERSION, help="Version de la méthodologie d'éval.")
    parser.add_argument("--start", type=int, default=0, help="Index de départ dans le jeu de test.")
    parser.add_argument("--end", type=int, default=None, help="Index de fin (exclu) — défaut : jusqu'au bout.")
    parser.add_argument(
        "--mode",
        choices=["dataset", "generated"],
        default="dataset",
        help="dataset (défaut) : Berlue vérifie la réponse du dataset. "
        "generated : le LLM génère sa réponse, jugée par un LLM-juge ancré sur les références du dataset.",
    )
    parser.add_argument("--judge-model", default=JUDGE_MODEL, help="Modèle du LLM-juge (mode generated uniquement).")
    parser.add_argument(
        "--warmup",
        action="store_true",
        help="Mode generated uniquement : précharge generator/judge en VRAM (appel jetable) avant "
        "de démarrer le chrono de la boucle — pour un récapitulatif de temps qui ne compte pas le "
        "chargement modèle. Sans effet avec --matrix (aucun appel LLM dans ce chemin).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Mode generated uniquement : nombre de questions traitées en parallèle au sein de chaque "
        "étape (génération, Berlue, juge) — 1 par défaut (séquentiel). À aligner sur le "
        "OLLAMA_NUM_PARALLEL réel du serveur ciblé.",
    )
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="Construit et stocke la/les matrice(s) finale(s) au lieu de remplir le cache "
        "(échoue si le scope est incomplet).",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Affiche le total d'éléments du scope (pour préparer un découpage --start/--end) et les index "
        "déjà en cache / manquants, sans rien calculer. Respecte --mode (dataset : lignes ; generated : "
        "questions).",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Évalue la baseline NLI seule au lieu de Berlue, jamais les deux — respecte --mode : "
        "dataset (défaut), recalculée à la volée, ignore les autres options ; generated, classifie "
        "les réponses déjà générées pour ce scope (--start/--end), sans regénérer ni appeler le "
        "juge/Berlue.",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Supprime les résultats en cache correspondant aux filtres --purge-*, au lieu d'évaluer. "
        "Chaque filtre omis est un joker.",
    )
    parser.add_argument(
        "--purge-scope",
        choices=["all", "results", "matrices"],
        default="all",
        help="Limite la purge aux résultats individuels, aux matrices, ou aux deux (défaut).",
    )
    parser.add_argument("--purge-dataset", default=None, help="Filtre de purge : dataset.")
    parser.add_argument("--purge-ratio", type=float, default=None, help="Filtre de purge : ratio train/test.")
    parser.add_argument("--purge-model-id", default=None, help="Filtre de purge : modèle.")
    parser.add_argument("--purge-pipeline-version", default=None, help="Filtre de purge : version du pipeline Berlue.")
    parser.add_argument("--purge-generation-version", default=None, help="Filtre de purge : version de génération.")
    parser.add_argument(
        "--purge-eval-version", default=None, help="Filtre de purge : version de la méthodologie d'éval."
    )
    parser.add_argument("--purge-judge-model", default=None, help="Filtre de purge : modèle du LLM-juge (mode 2).")
    parser.add_argument(
        "--log-level",
        choices=["ERROR", "WARNING", "INFO", "DEBUG"],
        default=None,
        help="Niveau de log (défaut : BERLUE_LOG_LEVEL, ou INFO). CLI uniquement, sans effet via /invoke "
        "(berlue.api.eval_service configure son propre logging au démarrage).",
    )
    return parser


def run_from_args(args, store: LocalResultStore | None = None):
    """Dispatch central sur les flags CLI (`args`, un `argparse.Namespace`
    produit par `build_arg_parser().parse_args(...)`) — réutilisé tel quel
    par `__main__` (CLI) et par `berlue.api.eval_service` (HTTP, un service
    Cloud Run chaud). `store` : store déjà construit à passer aux fonctions
    qui l'acceptent, pour éviter d'en reconstruire un (et de repayer
    `_ensure_bq_tables()` côté GCP) à chaque appel sur un service déjà
    préchauffé — `None` (défaut CLI) laisse chaque fonction construire le
    sien via `get_result_store()`, comme avant ce refactor.

    Retourne la valeur produite (déjà affichée via `print()` comme avant) —
    `None` pour les branches qui ne font que remplir le cache.
    """
    from berlue.evaluation.berlue_pipeline import BerluePipeline

    if args.purge:
        result = (store or get_result_store()).purge(
            dataset=args.purge_dataset,
            ratio=args.purge_ratio,
            model_id=args.purge_model_id,
            pipeline_version=args.purge_pipeline_version,
            generation_version=args.purge_generation_version,
            eval_version=args.purge_eval_version,
            judge_model=args.purge_judge_model,
            scope=args.purge_scope,
        )
        print(result)
        return result

    scope = EvalScope(
        dataset=args.dataset,
        ratio=args.ratio,
        model_id=args.model_id,
        pipeline_version=args.pipeline_version,
        generation_version=args.generation_version,
        eval_version=args.eval_version,
    )

    if args.baseline:
        if args.mode == "generated":
            if args.matrix:
                result = evaluate_baseline_generated_matrix(scope, judge_model=args.judge_model, store=store)
                print(result)
                return result
            evaluate_baseline_generated(scope, start=args.start, end=args.end, store=store)
            return None
        result = evaluate_baseline(dataset=args.dataset, ratio=args.ratio)
        print(result)
        return result

    if args.coverage:
        report = coverage_report(scope, store=store, mode=args.mode)
        unit = "questions" if args.mode == "generated" else "exemples"
        print(f"Total : {report['total']} {unit}")
        print(f"Fait     : {format_index_ranges(report['done_indices'])}")
        print(f"Manquant : {format_index_ranges(report['missing_indices'])}")
        if report["skipped_indices"]:
            print(f"Ignoré   : {format_index_ranges(report['skipped_indices'])} (référence manquante)")
        return report

    if args.mode == "generated":
        if args.matrix:
            result = evaluate_model_generated_matrix(scope, judge_model=args.judge_model, store=store)
            print(result)
            return result
        evaluate_model_generated(
            BerluePipeline(),
            scope,
            judge_model=args.judge_model,
            start=args.start,
            end=args.end,
            warmup=args.warmup,
            concurrency=args.concurrency,
            store=store,
        )
        return None

    if args.matrix:
        result = evaluate_model_matrix(scope, store=store)
        print(result)
        return result

    evaluate_model(BerluePipeline(), scope=scope, start=args.start, end=args.end, store=store)
    return None


if __name__ == "__main__":
    mark("__main__ start")
    parser = build_arg_parser()
    args = parser.parse_args()
    mark("CLI parsée")

    run_from_args(args)
