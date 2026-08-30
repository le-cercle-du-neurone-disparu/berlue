"""Routes de lecture des résultats d'évaluation du pipeline Berlue déjà en
cache (`berlue.evaluation.result_store`) — six routes en lecture seule,
aucune ne déclenche de calcul (cf. docs/evaluation/api.md pour le détail et
des exemples de réponse). Montées sur `app` par `berlue.api.fast`.
"""

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query

from berlue.api.schemas import ConfusionMatrix, EvaluationListOutput, EvaluationResult
from berlue.evaluation.result_store import LocalResultStore, get_result_store
from berlue.evaluation.run_eval import evaluate_baseline

eval_router = APIRouter()


@lru_cache(maxsize=1)
def get_store() -> LocalResultStore:
    """Store de résultats d'éval, créé une seule fois à la première requête
    (pas au démarrage de l'app — lazy) et réutilisé ensuite, cf.
    `evaluation.result_store.get_result_store` pour le choix local/GCP."""
    return get_result_store()


@eval_router.get("/evaluated-models", response_model=EvaluationListOutput)
def list_evaluations(
    store: LocalResultStore = Depends(get_store),  # noqa: B008 -- idiome FastAPI, Depends() dans le défaut est volontaire
    model_id: str | None = None,
    ratio: float | None = None,
    pipeline_version: str | None = None,
    eval_version: str | None = None,
):
    """
    Liste les résultats d'évaluation du pipeline Berlue déjà en cache
    (jamais de calcul déclenché ici, jamais de matrice partielle) —
    filtrable par `model_id`/`ratio`/`pipeline_version`/`eval_version`.
    """

    try:
        results = store.list_matrices(
            ratio=ratio, model_id=model_id, pipeline_version=pipeline_version, eval_version=eval_version
        )
        return {"evaluations": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de lecture des évaluations : {str(e)}") from e


@eval_router.get("/model-evaluation", response_model=EvaluationResult)
def get_model_evaluation(
    store: LocalResultStore = Depends(get_store),  # noqa: B008 -- idiome FastAPI, Depends() dans le défaut est volontaire
    dataset: str = Query(...),  # noqa: B008 -- idiome FastAPI, Query() dans le défaut est volontaire
    ratio: float = Query(...),  # noqa: B008
    model_id: str = Query(...),  # noqa: B008
    pipeline_version: str = Query(...),  # noqa: B008
    eval_version: str = Query(...),  # noqa: B008
):
    """
    Matrice Berlue d'un scope précis (identité obtenue via `/evaluated-models`)
    — répond **uniquement** si ce scope est déjà évalué et stocké (404
    sinon) ; ne déclenche jamais de calcul. `dataset_test_size` (dans la réponse)
    permet de savoir si `n_examples` couvre le split de test officiel complet
    ou un sous-ensemble partiel. Pas de `generation_version` (cette table n'en
    dépend pas, cf. docs/evaluation/storage.md).
    """

    results = store.list_matrices(
        dataset=dataset, ratio=ratio, model_id=model_id, pipeline_version=pipeline_version, eval_version=eval_version
    )
    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"Aucune évaluation en cache pour dataset={dataset!r}, ratio={ratio}, "
            f"model_id={model_id!r}, pipeline_version={pipeline_version!r}, eval_version={eval_version!r}.",
        )

    return results[0]


@eval_router.get("/baseline-evaluation", response_model=ConfusionMatrix)
def get_baseline_evaluation(
    dataset: str = Query(...),  # noqa: B008 -- idiome FastAPI, Query() dans le défaut est volontaire
    ratio: float = Query(...),  # noqa: B008
):
    """
    Matrice baseline pour un `(dataset, ratio)` donné — recalculée à la
    volée sur le jeu de test correspondant, jamais stockée ni mise en cache.
    Indépendante de `model_id`/`pipeline_version` (la baseline ne dépend pas
    du pipeline Berlue) : un seul appel sert pour tous les scopes qui
    partagent le même `(dataset, ratio)`, pas besoin de la redemander à
    chaque scope.
    """
    try:
        return evaluate_baseline(dataset=dataset, ratio=ratio)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de calcul de la baseline : {str(e)}") from e


@eval_router.get("/evaluated-models-generated", response_model=EvaluationListOutput)
def list_generated_evaluations(
    store: LocalResultStore = Depends(get_store),  # noqa: B008 -- idiome FastAPI, Depends() dans le défaut est volontaire
    model_id: str | None = None,
    ratio: float | None = None,
    pipeline_version: str | None = None,
    generation_version: str | None = None,
    eval_version: str | None = None,
):
    """
    Liste les résultats Berlue-vs-juge (mode 2 : réponse générée par le LLM
    sous test, jugée par un LLM-juge ancré sur les références du dataset)
    déjà en cache — filtrable par `model_id`/`ratio`/`pipeline_version`/
    `generation_version`/`eval_version`.
    """

    try:
        results = store.list_generated_berlue_matrices(
            ratio=ratio,
            model_id=model_id,
            pipeline_version=pipeline_version,
            generation_version=generation_version,
            eval_version=eval_version,
        )
        return {"evaluations": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de lecture des évaluations : {str(e)}") from e


@eval_router.get("/model-evaluation-generated", response_model=EvaluationResult)
def get_generated_model_evaluation(
    store: LocalResultStore = Depends(get_store),  # noqa: B008 -- idiome FastAPI, Depends() dans le défaut est volontaire
    dataset: str = Query(...),  # noqa: B008 -- idiome FastAPI, Query() dans le défaut est volontaire
    ratio: float = Query(...),  # noqa: B008
    model_id: str = Query(...),  # noqa: B008
    pipeline_version: str = Query(...),  # noqa: B008
    generation_version: str = Query(...),  # noqa: B008
    eval_version: str = Query(...),  # noqa: B008
):
    """
    Matrice Berlue-vs-juge (mode 2) d'un scope précis — répond **uniquement**
    si déjà stockée (404 sinon) ; ne déclenche jamais de calcul. `dataset_test_size`
    (dans la réponse) permet de savoir si `n_examples` couvre le split de test
    officiel complet ou un sous-ensemble partiel.
    """

    results = store.list_generated_berlue_matrices(
        dataset=dataset,
        ratio=ratio,
        model_id=model_id,
        pipeline_version=pipeline_version,
        generation_version=generation_version,
        eval_version=eval_version,
    )
    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"Aucune évaluation générée en cache pour dataset={dataset!r}, ratio={ratio}, "
            f"model_id={model_id!r}, pipeline_version={pipeline_version!r}, "
            f"generation_version={generation_version!r}, eval_version={eval_version!r}.",
        )

    return results[0]


@eval_router.get("/baseline-evaluation-generated", response_model=EvaluationResult)
def get_generated_baseline_evaluation(
    store: LocalResultStore = Depends(get_store),  # noqa: B008 -- idiome FastAPI, Depends() dans le défaut est volontaire
    dataset: str = Query(...),  # noqa: B008 -- idiome FastAPI, Query() dans le défaut est volontaire
    ratio: float = Query(...),  # noqa: B008
    model_id: str = Query(...),  # noqa: B008
    generation_version: str = Query(...),  # noqa: B008
    eval_version: str = Query(...),  # noqa: B008
):
    """
    Matrice baseline-vs-juge (mode 2) pour un `(dataset, ratio, model_id,
    generation_version, eval_version)` précis — contrairement à
    `/baseline-evaluation` (mode 1), **pas de calcul à la volée** : cette
    matrice dépend de la réponse générée par ce modèle précis, donc elle est
    mise en cache comme le reste du mode 2. Répond uniquement si déjà
    stockée (404 sinon). `dataset_test_size` (dans la réponse) permet de savoir si
    `n_examples` couvre le split de test officiel complet ou un sous-ensemble
    partiel. Pas de `pipeline_version` (indépendante du pipeline Berlue).
    """

    results = store.list_generated_baseline_matrices(
        dataset=dataset,
        ratio=ratio,
        model_id=model_id,
        generation_version=generation_version,
        eval_version=eval_version,
    )
    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"Aucune évaluation baseline générée en cache pour dataset={dataset!r}, "
            f"ratio={ratio}, model_id={model_id!r}, generation_version={generation_version!r}, "
            f"eval_version={eval_version!r}.",
        )

    return results[0]
