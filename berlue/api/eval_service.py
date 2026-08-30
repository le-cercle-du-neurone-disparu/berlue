"""Service Cloud Run dédié à l'éval du pipeline Berlue (`Dockerfile.eval-service`)
— tourne en continu (`min-instances=1`, cf. `make gcp_up`/`gcp_down`) plutôt
qu'un conteneur neuf par exécution : les imports Python tiers
(pandas/sklearn/google-cloud-bigquery...) et la construction du store GCP
ne sont payés qu'une fois, au démarrage de l'instance (avant que Cloud Run
ne la marque "ready") — cf. `lifespan` ci-dessous — plutôt qu'à chaque
appel. Temps mesurés : `docs/evaluation/execution-benchmark.md`.

Un seul endpoint générique (`/invoke`) plutôt qu'une route par fonction —
reçoit exactement les mêmes flags que la CLI (`berlue.evaluation.run_eval`,
`build_arg_parser()`/`run_from_args()`), en JSON au lieu d'argv : zéro
logique dupliquée avec la CLI. La purge fait exception : `/purge`, endpoint
séparé — jamais un simple flag dans `InvokeBody`, pour qu'un body `/invoke`
mal formé ne puisse jamais déclencher une suppression par accident (cf.
`purge` ci-dessous).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from berlue.evaluation.result_store import get_result_store
from berlue.evaluation.run_eval import build_arg_parser, run_from_args


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Construit le store UNE FOIS ici, au démarrage de l'instance — c'est ce
    # qui absorbe les imports lourds et (côté GCP) `_ensure_bq_tables()` dans
    # le préchauffage, avant que Cloud Run ne marque l'instance "ready" et se
    # mette à router du trafic dessus. Réutilisé par tous les appels
    # `/invoke` suivants sur cette même instance (jamais reconstruit).
    app.state.store = get_result_store()
    app.state.parser = build_arg_parser()
    yield


app = FastAPI(title="Berlue Eval Service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


class InvokeBody(BaseModel):
    """Champs optionnels — mêmes noms que les flags CLI de `run_eval.py`
    (sans le `--`, underscores au lieu de tirets), mêmes défauts (gérés par
    `build_arg_parser()`, pas dupliqués ici). Tout absent garde le défaut CLI.
    Pas de champ purge ici — cf. `PurgeBody`/`POST /purge`, endpoint séparé."""

    dataset: str | None = None
    ratio: float | None = None
    model_id: str | None = None
    pipeline_version: str | None = None
    generation_version: str | None = None
    eval_version: str | None = None
    start: int | None = None
    end: int | None = None
    mode: str | None = None
    judge_model: str | None = None
    warmup: bool | None = None
    matrix: bool | None = None
    coverage: bool | None = None
    baseline: bool | None = None


_FLAG_FIELDS = {"warmup", "matrix", "coverage", "baseline"}


def _argv_from_body(body: InvokeBody) -> list[str]:
    """Traduit les champs non-`None` du body en argv CLI équivalent (ex.
    `{"dataset": "halueval", "start": 0}` -> `["--dataset", "halueval",
    "--start", "0"]`) — les flags `store_true` (`_FLAG_FIELDS`) ne sont
    ajoutés à argv que s'ils sont vrais (comme sur une ligne de commande,
    absent = False)."""
    argv = []
    for name, value in body.model_dump(exclude_none=True).items():
        flag = "--" + name.replace("_", "-")
        if name in _FLAG_FIELDS:
            if value:
                argv.append(flag)
        else:
            argv.extend([flag, str(value)])
    return argv


def _jsonable(result):
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return result


@app.post("/invoke")
def invoke(body: InvokeBody, request: Request):
    """Équivalent HTTP d'un appel CLI à `run_eval.py` — reçoit les mêmes
    flags (cf. `InvokeBody`), réutilise le store déjà chaud de cette
    instance (`request.app.state.store`, construit une seule fois par
    `lifespan`)."""
    argv = _argv_from_body(body)
    try:
        args = request.app.state.parser.parse_args(argv)
    except SystemExit as e:
        # argparse appelle sys.exit(2) sur des args invalides — fatal pour un
        # process CLI jetable, mais tuerait ce process ASGI de longue durée.
        raise HTTPException(status_code=400, detail=f"Arguments invalides : {argv}") from e

    try:
        result = run_from_args(args, store=request.app.state.store)
    except ValueError as e:
        # Erreurs métier attendues (cache incomplet pour --matrix, dataset
        # inconnu...) — déjà des messages utilisateur clairs côté
        # `run_eval.py`, juste mal reflétés par le 500 générique par défaut.
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"result": _jsonable(result)}


class PurgeBody(BaseModel):
    """Filtres de purge — mêmes noms que les flags CLI `--purge-*` de
    `run_eval.py`, sans le préfixe `purge_` (implicite : ce endpoint ne fait
    que ça). Chaque filtre omis est un joker — cf. `docs/evaluation/storage.md`
    pour lequel des 3 axes de version filtre quelle table, et pourquoi un
    filtre trop large peut déborder sur des données qu'on ne voulait pas
    toucher (`eval_version` est le seul axe qui filtre systématiquement
    toutes les tables)."""

    scope: str | None = None
    dataset: str | None = None
    ratio: float | None = None
    model_id: str | None = None
    pipeline_version: str | None = None
    generation_version: str | None = None
    eval_version: str | None = None
    judge_model: str | None = None


@app.post("/purge")
def purge(body: PurgeBody, request: Request):
    """Supprime des résultats en cache — délibérément un endpoint séparé de
    `/invoke` (jamais un flag dans `InvokeBody`) : une purge est
    destructive, jamais question qu'un body `/invoke` mal formé ou un
    copier-coller d'une requête précédente la déclenche par accident. Mêmes
    filtres que `run_eval.py --purge`, cf. `PurgeBody`."""
    argv = ["--purge"]
    for name, value in body.model_dump(exclude_none=True).items():
        argv.extend([f"--purge-{name.replace('_', '-')}", str(value)])
    try:
        args = request.app.state.parser.parse_args(argv)
    except SystemExit as e:
        raise HTTPException(status_code=400, detail=f"Arguments invalides : {argv}") from e

    try:
        result = run_from_args(args, store=request.app.state.store)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"result": _jsonable(result)}
