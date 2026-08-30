"""Routes de lecture des résultats d'évaluation du pipeline Berlue déjà en
cache (`berlue.evaluation.result_store`) — quatre routes en lecture seule,
aucune ne déclenche de calcul (cf. docs/evaluation/api.md pour le détail et
des exemples de réponse). Montées sur `app` par `berlue.api.fast`.

`/evaluated-models`/`/model-evaluation` prennent un paramètre `mode` (`dataset`
défaut, ou `generated`) plutôt que d'avoir chacune une route `-generated`
dupliquée à côté — même `response_model`, même store en lecture seule des
deux côtés (juste `generation_version` en plus en mode généré), donc un seul
handler qui bascule entre `list_matrices`/`list_generated_berlue_matrices`.
`/baseline-evaluation` reste séparée de `/baseline-evaluation-generated` :
`response_model` différent (`ConfusionMatrix` nue vs `EvaluationResult`) et
comportement différent (mode 1 calcule à la volée, jamais stocké ; mode 2
lit uniquement le cache, jamais recalculé) — un paramètre `mode` sur une
route unique aurait forcé un type de réponse variable selon sa valeur, pas
representable proprement dans `response_model`/le schéma OpenAPI.
"""

from functools import lru_cache
from typing import Literal

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
    mode: Literal["dataset", "generated"] = "dataset",
    model_id: str | None = None,
    ratio: float | None = None,
    pipeline_version: str | None = None,
    generation_version: str | None = None,
    eval_version: str | None = None,
):
    """
    Liste les résultats d'évaluation du pipeline Berlue déjà en cache
    (jamais de calcul déclenché ici, jamais de matrice partielle) —
    filtrable par `model_id`/`ratio`/`pipeline_version`/`eval_version`, plus
    `generation_version` en `mode=generated` (ignoré sinon, cette table n'en
    dépend pas, cf. docs/evaluation/storage.md).
    """

    try:
        if mode == "generated":
            results = store.list_generated_berlue_matrices(
                ratio=ratio,
                model_id=model_id,
                pipeline_version=pipeline_version,
                generation_version=generation_version,
                eval_version=eval_version,
            )
        else:
            results = store.list_matrices(
                ratio=ratio, model_id=model_id, pipeline_version=pipeline_version, eval_version=eval_version
            )
        return {"evaluations": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de lecture des évaluations : {str(e)}") from e


@eval_router.get("/model-evaluation", response_model=EvaluationResult)
def get_model_evaluation(
    store: LocalResultStore = Depends(get_store),  # noqa: B008 -- idiome FastAPI, Depends() dans le défaut est volontaire
    mode: Literal["dataset", "generated"] = "dataset",
    dataset: str = Query(...),  # noqa: B008 -- idiome FastAPI, Query() dans le défaut est volontaire
    ratio: float = Query(...),  # noqa: B008
    model_id: str = Query(...),  # noqa: B008
    pipeline_version: str = Query(...),  # noqa: B008
    generation_version: str | None = Query(None),  # noqa: B008
    eval_version: str = Query(...),  # noqa: B008
):
    """
    Matrice Berlue d'un scope précis (identité obtenue via `/evaluated-models`)
    — répond **uniquement** si ce scope est déjà évalué et stocké (404
    sinon) ; ne déclenche jamais de calcul. `dataset_test_size` (dans la réponse)
    permet de savoir si `n_examples` couvre le split de test officiel complet
    ou un sous-ensemble partiel. `generation_version` requis en
    `mode=generated` (422 sinon), absent/ignoré en mode dataset (cette table
    n'en dépend pas, cf. docs/evaluation/storage.md).
    """
    if mode == "generated":
        if generation_version is None:
            raise HTTPException(status_code=422, detail="generation_version requis quand mode=generated.")
        results = store.list_generated_berlue_matrices(
            dataset=dataset,
            ratio=ratio,
            model_id=model_id,
            pipeline_version=pipeline_version,
            generation_version=generation_version,
            eval_version=eval_version,
        )
    else:
        results = store.list_matrices(
            dataset=dataset,
            ratio=ratio,
            model_id=model_id,
            pipeline_version=pipeline_version,
            eval_version=eval_version,
        )
    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"Aucune évaluation en cache pour mode={mode!r}, dataset={dataset!r}, ratio={ratio}, "
            f"model_id={model_id!r}, pipeline_version={pipeline_version!r}, "
            f"generation_version={generation_version!r}, eval_version={eval_version!r}.",
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
