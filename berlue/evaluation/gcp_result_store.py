"""Store GCP des résultats d'évaluation — même interface publique que
`LocalResultStore` (cf. `berlue.evaluation.result_store`), utilisé quand
`EVAL_STORE_TARGET=gcp`. Deux backends, un par famille de table (cf.
`docs/evaluation/storage.md` pour le détail du découpage et sa
justification) :

- **Firestore** pour les résultats individuels (5 collections, une par table
  `LocalResultStore`) — profil transactionnel, dédoublonnage atomique via
  une création avec `documentId` imposé (409 si le document existe déjà).
- **BigQuery** pour les matrices (3 tables, dataset `params.BQ_DATASET`) —
  écriture rare, lecture/listing fréquent ; upsert via `MERGE`.

**Registre de scopes** (`_scope_registry`, collection Firestore à part) —
Firestore n'a pas de `GROUP BY` natif ; scanner une collection de résultats
individuels pour savoir quels scopes existent coûterait une lecture
facturée par document. Le registre résume `(table, scope) -> n_rows`,
incrémenté atomiquement, mais **pas à chaque ligne** — bufferisé en mémoire
(`GcpResultStore._registry_buffer`) et envoyé par lots (`flush_registry`),
appelée périodiquement et en fin de run par `run_eval.py`. C'est un résumé
de navigation, pas la source de vérité : le perdre (crash dur, pas juste
Ctrl+C) ne perd aucune donnée réelle.

**Auth, en local (poste de développeur)** : ni Firestore ni BigQuery ne
passent par l'Application Default Credentials standard sur ce projet — une
politique de réauth (Google Workspace "Cloud session length") bloque le
rafraîchissement des ADC spécifiquement pour ces deux APIs (Storage n'est
pas concerné), et la lib cliente Firestore échoue par ailleurs avec
`Invalid database id %28default%29` même avec des credentials valides (bug
non résolu de la lib, constaté en conditions réelles, indépendant de
l'auth). Contournement dans les deux cas : la session `gcloud` CLI
elle-même n'est pas soumise à cette politique — `_access_token()`
s'authentifie via `gcloud auth print-access-token
--impersonate-service-account`, rafraîchi automatiquement avant expiration
(~1h), en **impersonant systématiquement `params.EVAL_SERVICE_ACCOUNT`**
(`sa-berlue` par défaut) plutôt que la session humaine directement — mêmes
droits en local qu'une fois déployé, jamais plus larges. Nécessite
`roles/iam.serviceAccountTokenCreator` sur ce SA (cf. `make gcp_setup`,
`docs/gcp/auth.md`) — sans ce rôle, `_access_token()` échoue
avec un `PERMISSION_DENIED` explicite, pas un repli silencieux sur la
session humaine.

**Auth, en exécution Cloud Run** (service ou job attaché à `sa-berlue`,
détecté via `K_SERVICE`/`CLOUD_RUN_JOB`) : ADC standard via le serveur de
métadonnées (`google.auth.default()`) — la politique Workspace ne
s'applique qu'aux sessions OAuth humaines, pas aux credentials d'un compte
de service obtenues ainsi ; pas d'impersonation nécessaire, l'identité du
Job est déjà `sa-berlue`. Le bug Firestore reste présent (indépendant de
l'auth), donc `_FirestoreRest` (REST direct plutôt que la lib cliente)
s'utilise dans les deux contextes, seule la source du jeton diffère.

Si l'admin Workspace lève la politique de réauth ADC et que le bug
Firestore est corrigé en amont, la branche locale de `_access_token()` peut
disparaître au profit des ADC standard partout — écart documenté ici et
dans `_access_token()`.

Params utilisés (`berlue.params`) : `EVAL_FIRESTORE_PROJECT`,
`EVAL_BIGQUERY_PROJECT`, `BQ_DATASET`, `EVAL_SERVICE_ACCOUNT`.
"""

import json
import logging
import os
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta

import google.auth
import google.auth.credentials
import google.auth.transport.requests
import requests
from google.cloud import bigquery

from berlue.api.schemas import ConfusionMatrix
from berlue.core.schemas import Verdict
from berlue.evaluation.result_store import EvalScope, _hash, _matrix_row_to_object, _matrix_to_values
from berlue.evaluation.signals import SIGNALS_FORMAT_VERSION
from berlue.evaluation.timing import mark
from berlue.params import BQ_DATASET, EVAL_BIGQUERY_PROJECT, EVAL_FIRESTORE_PROJECT, EVAL_SERVICE_ACCOUNT

_MATRIX_COLUMNS = (
    "ground_truth_true_predicted_true",
    "ground_truth_true_predicted_undecided",
    "ground_truth_true_predicted_false",
    "ground_truth_false_predicted_true",
    "ground_truth_false_predicted_undecided",
    "ground_truth_false_predicted_false",
)


def _doc_id(*parts) -> str:
    """Id de document déterministe à partir des composantes d'une clé
    unique — deux appels avec les mêmes composantes retombent sur le même
    id, ce qui permet le dédoublonnage à la création (409 si déjà présent)."""
    return _hash("|".join(str(p) for p in parts))


def _running_on_cloud_run() -> bool:
    """Vrai à l'intérieur d'un service ou job Cloud Run — `K_SERVICE`/
    `CLOUD_RUN_JOB` sont posées automatiquement par la plateforme, jamais en
    local. Détermine la source du jeton d'accès, cf. `_access_token()`."""
    return bool(os.environ.get("K_SERVICE") or os.environ.get("CLOUD_RUN_JOB"))


def _access_token() -> str:
    """Jeton d'accès pour Firestore/BigQuery, authentifié comme
    `params.EVAL_SERVICE_ACCOUNT` (`sa-berlue`) dans tous les cas — source
    différente selon où le code tourne :

    - **Cloud Run** (service ou job attaché à `sa-berlue`) : ADC standard via
      le serveur de métadonnées — déjà `sa-berlue`, pas besoin
      d'impersonation. La politique Workspace qui bloque le rafraîchissement
      des ADC (cf. docstring du module) cible les sessions OAuth humaines,
      pas les credentials d'un compte de service obtenues ainsi.
    - **Local** (poste de développeur) : session `gcloud` CLI, avec
      impersonation explicite de `sa-berlue` — les ADC standard n'ont pas
      cette option ici (bloquées par la même politique), cf. docstring du
      module. Nécessite `roles/iam.serviceAccountTokenCreator` sur ce SA.
    """
    if _running_on_cloud_run():
        mark("_access_token() start (ADC via métadonnées)")
        credentials, _ = google.auth.default()
        credentials.refresh(google.auth.transport.requests.Request())
        mark("_access_token() fini")
        return credentials.token

    if not EVAL_SERVICE_ACCOUNT:
        raise RuntimeError(
            "❌ EVAL_SERVICE_ACCOUNT non résolu (GCP_PROJECT absent ?) — impossible de s'authentifier auprès de GCP."
        )
    cmd = ["gcloud", "auth", "print-access-token", "--impersonate-service-account", EVAL_SERVICE_ACCOUNT]
    return subprocess.check_output(cmd, text=True).strip()


class _AccessTokenCredentials(google.auth.credentials.Credentials):
    """Credentials basées sur `_access_token()` plutôt que l'ADC classique de
    `google.cloud.bigquery.Client` — cf. docstring du module. Se rafraîchit
    automatiquement avant expiration."""

    def refresh(self, request) -> None:
        self.token = _access_token()
        self.expiry = datetime.utcnow() + timedelta(minutes=50)  # naive UTC, convention google-auth


class _FirestoreRest:
    """Client Firestore minimal en REST direct — cf. docstring du module
    pour pourquoi (bug de la lib cliente officielle sur ce projet)."""

    _API_BASE = "https://firestore.googleapis.com/v1"

    def __init__(self, project: str):
        self.project = project
        self._token: str | None = None
        self._token_expires_at = 0.0

    def _headers(self) -> dict:
        if self._token is None or time.monotonic() >= self._token_expires_at:
            self._token = _access_token()
            self._token_expires_at = time.monotonic() + 50 * 60
        return {"Authorization": f"Bearer {self._token}"}

    def _documents_url(self) -> str:
        return f"{self._API_BASE}/projects/{self.project}/databases/(default)/documents"

    def _doc_url(self, collection: str, doc_id: str) -> str:
        return f"{self._documents_url()}/{collection}/{doc_id}"

    def _resource_name(self, collection: str, doc_id: str) -> str:
        return f"projects/{self.project}/databases/(default)/documents/{collection}/{doc_id}"

    def get(self, collection: str, doc_id: str) -> dict | None:
        response = requests.get(self._doc_url(collection, doc_id), headers=self._headers())
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return _from_fields(response.json().get("fields", {}))

    def create(self, collection: str, doc_id: str, data: dict) -> bool:
        """Crée le document avec l'id imposé `doc_id` — retourne `False`
        (pas d'erreur) si un document avec cet id existe déjà (409)."""
        response = requests.post(
            f"{self._documents_url()}/{collection}",
            params={"documentId": doc_id},
            headers=self._headers(),
            json={"fields": _to_fields(data)},
        )
        if response.status_code == 409:
            return False
        response.raise_for_status()
        return True

    def increment(self, collection: str, doc_id: str, field: str, by: int) -> None:
        """Incrémente atomiquement `field` de `by` sur un document déjà
        existant (transform Firestore, pas un GET+PATCH — évite toute
        perte d'incrément entre deux appels concurrents)."""
        body = {
            "writes": [
                {
                    "transform": {
                        "document": self._resource_name(collection, doc_id),
                        "fieldTransforms": [{"fieldPath": field, "increment": {"integerValue": str(by)}}],
                    }
                }
            ]
        }
        response = requests.post(f"{self._documents_url()}:commit", headers=self._headers(), json=body)
        response.raise_for_status()

    def query(self, collection: str, filters: dict) -> list[dict]:
        """Documents de `collection` dont tous les champs de `filters`
        correspondent (égalité) — jokers si `filters` est vide."""
        return [entry["fields"] for entry in self._query_raw(collection, filters)]

    def _query_raw(self, collection: str, filters: dict) -> list[dict]:
        """Comme `query`, mais garde le nom complet du document (`name`) —
        nécessaire pour la suppression en masse (`purge`)."""
        body = {"structuredQuery": {"from": [{"collectionId": collection}]}}
        if filters:
            field_filters = [
                {"fieldFilter": {"field": {"fieldPath": k}, "op": "EQUAL", "value": _to_value(v)}}
                for k, v in filters.items()
            ]
            where = (
                field_filters[0]
                if len(field_filters) == 1
                else {"compositeFilter": {"op": "AND", "filters": field_filters}}
            )
            body["structuredQuery"]["where"] = where

        response = requests.post(f"{self._documents_url()}:runQuery", headers=self._headers(), json=body)
        response.raise_for_status()
        results = []
        for entry in response.json():
            doc = entry.get("document")
            if doc:
                results.append({"name": doc["name"], "fields": _from_fields(doc.get("fields", {}))})
        return results

    def delete_matching(self, collection: str, filters: dict) -> int:
        """Supprime tous les documents de `collection` correspondant à
        `filters` (jokers si vide) — écriture par lots de 500 (limite
        Firestore par `commit`). Retourne le nombre de documents supprimés."""
        names = [entry["name"] for entry in self._query_raw(collection, filters)]
        for i in range(0, len(names), 500):
            chunk = names[i : i + 500]
            body = {"writes": [{"delete": name} for name in chunk]}
            response = requests.post(f"{self._documents_url()}:commit", headers=self._headers(), json=body)
            response.raise_for_status()
        return len(names)


def _to_value(v) -> dict:
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def _to_fields(data: dict) -> dict:
    return {k: _to_value(v) for k, v in data.items()}


def _from_value(fv: dict):
    if "stringValue" in fv:
        return fv["stringValue"]
    if "integerValue" in fv:
        return int(fv["integerValue"])
    if "doubleValue" in fv:
        return fv["doubleValue"]
    if "booleanValue" in fv:
        return fv["booleanValue"]
    raise ValueError(f"Type Firestore non géré : {fv}")


def _from_fields(fields: dict) -> dict:
    return {k: _from_value(v) for k, v in fields.items()}


logger = logging.getLogger(__name__)


def _non_null(**kwargs) -> dict:
    """Filtre les kwargs à `None` — construit un dict de filtres à partir
    d'une liste de paramètres optionnels, jokers si omis."""
    return {k: v for k, v in kwargs.items() if v is not None}


class GcpResultStore:
    """Store de résultats d'évaluation sur GCP (Firestore + BigQuery)."""

    # cf. docstring du module — flush automatique au-delà de ce nombre de
    # lignes comptées en mémoire depuis le dernier flush.
    REGISTRY_FLUSH_EVERY = 20

    def __init__(self, firestore_project: str = EVAL_FIRESTORE_PROJECT, bigquery_project: str = EVAL_BIGQUERY_PROJECT):
        mark("GcpResultStore.__init__ start")
        self.fs = _FirestoreRest(firestore_project)
        self.bq = bigquery.Client(project=bigquery_project, credentials=_AccessTokenCredentials())
        mark("bigquery.Client() construit")
        self.bq_dataset = BQ_DATASET
        self._ensure_bq_tables()
        mark("_ensure_bq_tables() fait (3x create_table exists_ok)")
        self._registry_buffer: dict[tuple[str, tuple], int] = {}
        # Ce store est utilisable depuis plusieurs threads à la fois (éval
        # parallélisée, cf. `evaluate_model_generated(..., concurrency=N)`) —
        # protège les lectures/écritures/vidage de `_registry_buffer`, jamais
        # tenu pendant un appel réseau Firestore (cf. `flush_registry`).
        self._registry_lock = threading.Lock()

    # -- Registre de scopes ------------------------------------------------

    def _register_new_row(self, table: str, scope_fields: dict) -> None:
        """Compte une nouvelle ligne pour `table`/`scope_fields` dans le
        registre de scopes — bufferisé en mémoire, aucun appel réseau ici."""
        key = (table, tuple(scope_fields.items()))
        with self._registry_lock:
            self._registry_buffer[key] = self._registry_buffer.get(key, 0) + 1
            should_flush = sum(self._registry_buffer.values()) >= self.REGISTRY_FLUSH_EVERY
        if should_flush:
            self.flush_registry()

    def flush_registry(self) -> None:
        """Envoie au registre de scopes les incréments accumulés depuis le
        dernier flush. Idempotent (rien à faire si le buffer est vide) — à
        appeler périodiquement pendant un run, et systématiquement à la fin
        (y compris sur Ctrl+C, cf. `run_eval.py`). Vide le buffer sous verrou
        puis fait les appels réseau sur cette copie locale, jamais sous
        verrou — un autre thread peut continuer à accumuler dans un buffer
        neuf pendant ce temps, flushé à son tour plus tard."""
        with self._registry_lock:
            pending = dict(self._registry_buffer)
            self._registry_buffer.clear()
        for (table, scope_items), count in pending.items():
            scope_fields = dict(scope_items)
            doc_id = _doc_id(table, *scope_fields.values())
            self.fs.create("_scope_registry", doc_id, {"table": table, **scope_fields, "n_rows": 0})
            self.fs.increment("_scope_registry", doc_id, "n_rows", count)

    def _list_registry_scopes(self, table: str) -> list[dict]:
        entries = self.fs.query("_scope_registry", {"table": table})
        results = []
        for entry in entries:
            entry = dict(entry)
            entry.pop("table")
            n_rows = entry.pop("n_rows")
            entry["n_rows"] = n_rows
            results.append(entry)
        return results

    # -- BigQuery : schéma ------------------------------------------------

    def _bq_table_ref(self, table: str) -> str:
        return f"{self.bq.project}.{self.bq_dataset}.{table}"

    def _ensure_bq_tables(self) -> None:
        """Crée les 3 tables de matrices si elles n'existent pas déjà —
        équivalent BigQuery de `CREATE TABLE IF NOT EXISTS` côté local."""

        def field(name: str, bq_type: str = "STRING", mode: str = "REQUIRED") -> bigquery.SchemaField:
            return bigquery.SchemaField(name, bq_type, mode=mode)

        score_fields = [field(col, "INT64") for col in _MATRIX_COLUMNS] + [
            field("n_examples", "INT64"),
            # NULLABLE : inconnu quand le dataset n'est pas reconnu (cf.
            # `run_eval._official_dataset_test_size`), pas un défaut à 0.
            field("dataset_test_size", "INT64", mode="NULLABLE"),
            field("computed_at", "TIMESTAMP"),
        ]
        common = [field("dataset"), field("ratio", "FLOAT64"), field("model_id")]

        schemas = {
            "eval_matrices": [*common, field("pipeline_version"), field("eval_version"), *score_fields],
            "eval_matrices_generated_berlue": [
                *common,
                field("pipeline_version"),
                field("generation_version"),
                field("eval_version"),
                *score_fields,
            ],
            "eval_matrices_generated_baseline": [
                *common,
                field("generation_version"),
                field("eval_version"),
                *score_fields,
            ],
        }
        for table, schema in schemas.items():
            table_ref = bigquery.Table(self._bq_table_ref(table), schema=schema)
            self.bq.create_table(table_ref, exists_ok=True)

    # -- Mode 1 : résultats individuels -------------------------------------

    def get_verdict(self, scope: EvalScope, question: str, answer: str) -> Verdict | None:
        doc = self.fs.get("eval_predictions", self._prediction_id(scope, question, answer))
        return Verdict(doc["verdict"]) if doc else None

    def put_prediction(
        self, scope: EvalScope, question: str, answer: str, ground_truth_label: bool, verdict: Verdict
    ) -> bool:
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "eval_version")
        created = self.fs.create(
            "eval_predictions",
            self._prediction_id(scope, question, answer),
            {
                **key,
                "question": question,
                "answer": answer,
                "ground_truth_label": ground_truth_label,
                "verdict": verdict.value,
                "computed_at": datetime.now(UTC).isoformat(),
            },
        )
        if created:
            self._register_new_row("eval_predictions", key)
        return created

    def _prediction_id(self, scope: EvalScope, question: str, answer: str) -> str:
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "eval_version")
        return _doc_id(*key.values(), _hash(question), _hash(answer))

    def get_signals(self, scope: EvalScope, question: str, answer: str) -> dict | None:
        """Signaux pré-fusion déjà en cache, ou `None`. Un cache hit signifie qu'on ne
        rappelle ni le RAG ni SelfCheck : seule la fusion sera recalculée."""
        doc = self.fs.get("eval_signals", self._signals_id(scope, question, answer))
        if not doc:
            return None
        signals = json.loads(doc["signals"])
        # Un format plus ancien est traité comme une absence : mieux vaut recalculer
        # que relire de travers.
        return signals if signals.get("format_version") == SIGNALS_FORMAT_VERSION else None

    def put_signals(self, scope: EvalScope, question: str, answer: str, signals: dict) -> bool:
        """Stocke les signaux pré-fusion s'ils ne sont pas déjà en cache."""
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version")
        created = self.fs.create(
            "eval_signals",
            self._signals_id(scope, question, answer),
            {
                **key,
                "question": question,
                "answer": answer,
                # Sérialisé en une chaîne plutôt qu'en map imbriquée : Firestore ne
                # sait pas indexer des tableaux d'objets, et rien ici n'est requêté
                # autrement que par identifiant de document.
                "signals": json.dumps(signals, ensure_ascii=False),
                "computed_at": datetime.now(UTC).isoformat(),
            },
        )
        if created:
            self._register_new_row("eval_signals", key)
        return created

    def _signals_id(self, scope: EvalScope, question: str, answer: str) -> str:
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version")
        return _doc_id(*key.values(), _hash(question), _hash(answer))

    def list_predictions(self, scope: EvalScope) -> list[dict]:
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "eval_version")
        docs = self.fs.query("eval_predictions", key)
        return [
            {
                "question": doc["question"],
                "answer": doc["answer"],
                "ground_truth_label": bool(doc["ground_truth_label"]),
                "verdict": Verdict(doc["verdict"]),
                "computed_at": doc["computed_at"],
            }
            for doc in docs
        ]

    def list_prediction_scopes(self) -> list[dict]:
        return self._list_registry_scopes("eval_predictions")

    def get_generated_answer(self, model_id: str, generation_version: str, question: str) -> str | None:
        doc = self.fs.get("llm_answers", _doc_id(model_id, generation_version, _hash(question)))
        return doc["answer"] if doc else None

    def put_generated_answer(self, model_id: str, generation_version: str, question: str, answer: str) -> bool:
        key = {"model_id": model_id, "generation_version": generation_version}
        created = self.fs.create(
            "llm_answers",
            _doc_id(model_id, generation_version, _hash(question)),
            {**key, "question": question, "answer": answer, "computed_at": datetime.now(UTC).isoformat()},
        )
        if created:
            self._register_new_row("llm_answers", key)
        return created

    def list_generated_answer_scopes(self) -> list[dict]:
        return self._list_registry_scopes("llm_answers")

    def list_generated_answers(self, model_id: str, generation_version: str) -> set[str]:
        docs = self.fs.query("llm_answers", {"model_id": model_id, "generation_version": generation_version})
        return {doc["question"] for doc in docs}

    def get_judge_verdict(
        self, model_id: str, generation_version: str, judge_model: str, eval_version: str, question: str
    ) -> Verdict | None:
        doc_id = _doc_id(model_id, generation_version, judge_model, eval_version, _hash(question))
        doc = self.fs.get("judge_verdicts", doc_id)
        return Verdict(doc["verdict"]) if doc else None

    def put_judge_verdict(
        self,
        model_id: str,
        generation_version: str,
        judge_model: str,
        eval_version: str,
        question: str,
        verdict: Verdict,
    ) -> bool:
        key = {
            "model_id": model_id,
            "generation_version": generation_version,
            "judge_model": judge_model,
            "eval_version": eval_version,
        }
        doc_id = _doc_id(model_id, generation_version, judge_model, eval_version, _hash(question))
        created = self.fs.create(
            "judge_verdicts",
            doc_id,
            {**key, "question": question, "verdict": verdict.value, "computed_at": datetime.now(UTC).isoformat()},
        )
        if created:
            self._register_new_row("judge_verdicts", key)
        return created

    def list_judge_verdict_scopes(self) -> list[dict]:
        return self._list_registry_scopes("judge_verdicts")

    def get_generated_berlue_verdict(self, scope: EvalScope, question: str) -> Verdict | None:
        doc = self.fs.get("eval_berlue_generated", self._berlue_generated_id(scope, question))
        return Verdict(doc["verdict"]) if doc else None

    def put_generated_berlue_verdict(self, scope: EvalScope, question: str, verdict: Verdict) -> bool:
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "generation_version", "eval_version")
        created = self.fs.create(
            "eval_berlue_generated",
            self._berlue_generated_id(scope, question),
            {**key, "question": question, "verdict": verdict.value, "computed_at": datetime.now(UTC).isoformat()},
        )
        if created:
            self._register_new_row("eval_berlue_generated", key)
        return created

    def _berlue_generated_id(self, scope: EvalScope, question: str) -> str:
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "generation_version", "eval_version")
        return _doc_id(*key.values(), _hash(question))

    def list_generated_berlue_verdict_scopes(self) -> list[dict]:
        return self._list_registry_scopes("eval_berlue_generated")

    def get_generated_baseline_verdict(
        self, dataset: str, ratio: float, model_id: str, generation_version: str, eval_version: str, question: str
    ) -> Verdict | None:
        doc_id = self._baseline_generated_id(dataset, ratio, model_id, generation_version, eval_version, question)
        doc = self.fs.get("eval_baseline_generated", doc_id)
        return Verdict(doc["verdict"]) if doc else None

    def put_generated_baseline_verdict(
        self,
        dataset: str,
        ratio: float,
        model_id: str,
        generation_version: str,
        eval_version: str,
        question: str,
        verdict: Verdict,
    ) -> bool:
        key = {
            "dataset": dataset,
            "ratio": ratio,
            "model_id": model_id,
            "generation_version": generation_version,
            "eval_version": eval_version,
        }
        doc_id = self._baseline_generated_id(dataset, ratio, model_id, generation_version, eval_version, question)
        created = self.fs.create(
            "eval_baseline_generated",
            doc_id,
            {**key, "question": question, "verdict": verdict.value, "computed_at": datetime.now(UTC).isoformat()},
        )
        if created:
            self._register_new_row("eval_baseline_generated", key)
        return created

    def _baseline_generated_id(
        self, dataset: str, ratio: float, model_id: str, generation_version: str, eval_version: str, question: str
    ) -> str:
        return _doc_id(dataset, ratio, model_id, generation_version, eval_version, _hash(question))

    def list_generated_baseline_verdict_scopes(self) -> list[dict]:
        return self._list_registry_scopes("eval_baseline_generated")

    # -- BigQuery : matrices ------------------------------------------------

    def _put_matrix(
        self,
        table: str,
        key_fields: dict,
        matrix: ConfusionMatrix,
        n_examples: int,
        dataset_test_size: int | None = None,
    ) -> None:
        """Upsert générique (MERGE) partagé par les 3 tables de matrices —
        `key_fields` porte les colonnes de la clé unique de `table`."""
        key_columns = list(key_fields)
        values = dict(key_fields)
        values.update(dict(zip(_MATRIX_COLUMNS, _matrix_to_values(matrix), strict=True)))
        values["n_examples"] = n_examples
        values["dataset_test_size"] = dataset_test_size
        values["computed_at"] = datetime.now(UTC)

        all_columns = key_columns + list(_MATRIX_COLUMNS) + ["n_examples", "dataset_test_size", "computed_at"]
        on_clause = " AND ".join(f"T.{c} = S.{c}" for c in key_columns)
        update_clause = ", ".join(f"{c} = S.{c}" for c in all_columns if c not in key_columns)
        select_clause = ", ".join(f"@{c} AS {c}" for c in all_columns)

        query = f"""
            MERGE `{self._bq_table_ref(table)}` T
            USING (SELECT {select_clause}) S
            ON {on_clause}
            WHEN MATCHED THEN UPDATE SET {update_clause}
            WHEN NOT MATCHED THEN INSERT ({", ".join(all_columns)})
            VALUES ({", ".join(f"S.{c}" for c in all_columns)})
        """
        params = [_bq_param(c, v, bq_type="INT64" if c == "dataset_test_size" else None) for c, v in values.items()]
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        self.bq.query(query, job_config=job_config).result()

    def _get_matrix(self, table: str, key_fields: dict) -> ConfusionMatrix | None:
        where_clause, params = _bq_where(key_fields)
        query = f"SELECT {', '.join(_MATRIX_COLUMNS)} FROM `{self._bq_table_ref(table)}` {where_clause} LIMIT 1"
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        rows = list(self.bq.query(query, job_config=job_config).result())
        return _matrix_row_to_object(tuple(rows[0].values())) if rows else None

    def put_matrix(
        self, scope: EvalScope, matrix: ConfusionMatrix, n_examples: int, dataset_test_size: int | None = None
    ) -> None:
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "eval_version")
        self._put_matrix("eval_matrices", key, matrix, n_examples, dataset_test_size)

    def get_matrix(self, scope: EvalScope) -> ConfusionMatrix | None:
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "eval_version")
        return self._get_matrix("eval_matrices", key)

    def list_matrices(
        self,
        dataset: str | None = None,
        ratio: float | None = None,
        model_id: str | None = None,
        pipeline_version: str | None = None,
        eval_version: str | None = None,
    ) -> list[dict]:
        filters = _non_null(
            dataset=dataset,
            ratio=ratio,
            model_id=model_id,
            pipeline_version=pipeline_version,
            eval_version=eval_version,
        )
        return self._list_matrices(
            "eval_matrices", ["dataset", "ratio", "model_id", "pipeline_version", "eval_version"], filters
        )

    def put_generated_berlue_matrix(
        self, scope: EvalScope, matrix: ConfusionMatrix, n_examples: int, dataset_test_size: int | None = None
    ) -> None:
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "generation_version", "eval_version")
        self._put_matrix("eval_matrices_generated_berlue", key, matrix, n_examples, dataset_test_size)

    def get_generated_berlue_matrix(self, scope: EvalScope) -> ConfusionMatrix | None:
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "generation_version", "eval_version")
        return self._get_matrix("eval_matrices_generated_berlue", key)

    def list_generated_berlue_matrices(
        self,
        dataset: str | None = None,
        ratio: float | None = None,
        model_id: str | None = None,
        pipeline_version: str | None = None,
        generation_version: str | None = None,
        eval_version: str | None = None,
    ) -> list[dict]:
        filters = _non_null(
            dataset=dataset,
            ratio=ratio,
            model_id=model_id,
            pipeline_version=pipeline_version,
            generation_version=generation_version,
            eval_version=eval_version,
        )
        columns = ["dataset", "ratio", "model_id", "pipeline_version", "generation_version", "eval_version"]
        return self._list_matrices("eval_matrices_generated_berlue", columns, filters)

    def put_generated_baseline_matrix(
        self,
        dataset: str,
        ratio: float,
        model_id: str,
        generation_version: str,
        eval_version: str,
        matrix: ConfusionMatrix,
        n_examples: int,
        dataset_test_size: int | None = None,
    ) -> None:
        key = {
            "dataset": dataset,
            "ratio": ratio,
            "model_id": model_id,
            "generation_version": generation_version,
            "eval_version": eval_version,
        }
        self._put_matrix("eval_matrices_generated_baseline", key, matrix, n_examples, dataset_test_size)

    def get_generated_baseline_matrix(
        self, dataset: str, ratio: float, model_id: str, generation_version: str, eval_version: str
    ) -> ConfusionMatrix | None:
        key = {
            "dataset": dataset,
            "ratio": ratio,
            "model_id": model_id,
            "generation_version": generation_version,
            "eval_version": eval_version,
        }
        return self._get_matrix("eval_matrices_generated_baseline", key)

    def list_generated_baseline_matrices(
        self,
        dataset: str | None = None,
        ratio: float | None = None,
        model_id: str | None = None,
        generation_version: str | None = None,
        eval_version: str | None = None,
    ) -> list[dict]:
        filters = _non_null(
            dataset=dataset,
            ratio=ratio,
            model_id=model_id,
            generation_version=generation_version,
            eval_version=eval_version,
        )
        columns = ["dataset", "ratio", "model_id", "generation_version", "eval_version"]
        return self._list_matrices("eval_matrices_generated_baseline", columns, filters)

    def _list_matrices(self, table: str, columns: list[str], filters: dict) -> list[dict]:
        where_clause, params = _bq_where(filters)
        query = f"""
            SELECT {", ".join(columns)}, {", ".join(_MATRIX_COLUMNS)}, n_examples, dataset_test_size, computed_at
            FROM `{self._bq_table_ref(table)}` {where_clause}
        """
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        results = []
        for row in self.bq.query(query, job_config=job_config).result():
            entry = {c: row[c] for c in columns}
            entry["matrix"] = _matrix_row_to_object(tuple(row[c] for c in _MATRIX_COLUMNS))
            entry["n_examples"] = row["n_examples"]
            entry["dataset_test_size"] = row["dataset_test_size"]
            entry["computed_at"] = row["computed_at"].isoformat()
            results.append(entry)
        return results

    # -- Purge --------------------------------------------------------------

    def purge(
        self,
        dataset: str | None = None,
        ratio: float | None = None,
        model_id: str | None = None,
        pipeline_version: str | None = None,
        generation_version: str | None = None,
        eval_version: str | None = None,
        judge_model: str | None = None,
        scope: str = "all",
    ) -> dict[str, int]:
        scopes_valides = ("all", "results", "matrices", "signals", "fusion")
        if scope not in scopes_valides:
            raise ValueError(f"❌ scope de purge invalide : {scope!r} (doit être {', '.join(scopes_valides)})")

        mode1_filters = _non_null(
            dataset=dataset,
            ratio=ratio,
            model_id=model_id,
            pipeline_version=pipeline_version,
            eval_version=eval_version,
        )
        mode1_gen_filters = _non_null(**mode1_filters, generation_version=generation_version)
        # Les signaux ne portent pas d'eval_version (cf. LocalResultStore._create_tables).
        signals_filters = {k: v for k, v in mode1_filters.items() if k != "eval_version"}
        answer_filters = _non_null(model_id=model_id, generation_version=generation_version)
        judge_filters = _non_null(**answer_filters, judge_model=judge_model, eval_version=eval_version)
        baseline_filters = _non_null(
            dataset=dataset,
            ratio=ratio,
            model_id=model_id,
            generation_version=generation_version,
            eval_version=eval_version,
        )

        # Le registre de scopes doit refléter la purge — sinon un scope
        # entièrement supprimé resterait listé (résumé de navigation, pas la
        # source de vérité, mais un résumé faux n'est pas utile). Flush
        # d'abord ce qui est encore bufferisé, pour ne pas perdre un
        # incrément en cours au passage.
        self.flush_registry()

        # Si AUCUN des filtres demandés ne s'applique à une table, on l'exclut : la
        # suppression y serait non bornée alors qu'on a demandé quelque chose de précis
        # (cf. LocalResultStore.purge). Un filtre partiellement applicable, lui, reste
        # honoré — purger un scope complet doit atteindre les tables qui n'ont pas tous
        # ses axes.
        demandes = _non_null(
            dataset=dataset,
            ratio=ratio,
            model_id=model_id,
            pipeline_version=pipeline_version,
            generation_version=generation_version,
            eval_version=eval_version,
            judge_model=judge_model,
        )

        def concerne(filters: dict) -> bool:
            """Vrai si au moins un filtre demandé s'applique à cette table."""
            return not demandes or any(k in filters for k in demandes)

        def firestore(table: str, filters: dict) -> int:
            if not concerne(filters):
                return 0
            n = self.fs.delete_matching(table, filters)
            self.fs.delete_matching("_scope_registry", {"table": table, **filters})
            return n

        def bigquery(table: str, filters: dict) -> int:
            return self._purge_bigquery(table, filters) if concerne(filters) else 0

        counts: dict[str, int] = {}
        if scope in ("all", "results", "fusion"):
            counts["predictions_deleted"] = firestore("eval_predictions", mode1_filters)
        if scope in ("all", "signals"):
            counts["signals_deleted"] = firestore("eval_signals", signals_filters)
        if scope in ("all", "results"):
            counts["llm_answers_deleted"] = firestore("llm_answers", answer_filters)
            counts["judge_verdicts_deleted"] = firestore("judge_verdicts", judge_filters)
            counts["berlue_generated_deleted"] = firestore("eval_berlue_generated", mode1_gen_filters)
            counts["baseline_generated_deleted"] = firestore("eval_baseline_generated", baseline_filters)
        if scope in ("all", "matrices", "fusion"):
            counts["matrices_deleted"] = bigquery("eval_matrices", mode1_filters)
        # Les matrices du mode 2 ne sont pas des sorties de fusion du mode 1 :
        # "fusion" ne doit pas y toucher.
        if scope in ("all", "matrices"):
            counts["matrices_generated_berlue_deleted"] = bigquery("eval_matrices_generated_berlue", mode1_gen_filters)
            counts["matrices_generated_baseline_deleted"] = bigquery(
                "eval_matrices_generated_baseline", baseline_filters
            )
        return counts

    def _purge_bigquery(self, table: str, filters: dict) -> int:
        where_clause, params = _bq_where(filters)
        if not where_clause:
            where_clause = "WHERE TRUE"  # DELETE sans WHERE refusé par BigQuery
        query = f"DELETE FROM `{self._bq_table_ref(table)}` {where_clause}"
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        job = self.bq.query(query, job_config=job_config)
        job.result()
        return job.num_dml_affected_rows or 0


def _bq_param(name: str, value, bq_type: str | None = None) -> bigquery.ScalarQueryParameter:
    """`bq_type` : à préciser explicitement quand `value` peut être `None`
    (le type ne peut alors pas être déduit de la valeur elle-même — ex.
    `dataset_test_size`, NULLABLE)."""
    if bq_type is None:
        if isinstance(value, bool):
            bq_type = "BOOL"
        elif isinstance(value, int):
            bq_type = "INT64"
        elif isinstance(value, float):
            bq_type = "FLOAT64"
        elif isinstance(value, datetime):
            bq_type = "TIMESTAMP"
        else:
            bq_type = "STRING"
    return bigquery.ScalarQueryParameter(name, bq_type, value)


def _bq_where(filters: dict) -> tuple[str, list]:
    if not filters:
        return "", []
    clause = "WHERE " + " AND ".join(f"{c}=@{c}" for c in filters)
    params = [_bq_param(c, v) for c, v in filters.items()]
    return clause, params
