"""Cache des prédictions individuelles de l'évaluation du pipeline Berlue —
équivalent local (SQLite) du store GCP (Firestore + BigQuery, cf.
`berlue.evaluation.gcp_result_store`) utilisé quand `EVAL_STORE_TARGET=gcp`.

Une entrée de cache est identifiée par un `EvalScope` (le paramétrage global
d'une évaluation — dataset, ratio, modèle, versions — PAS un run précis) plus
la question et la réponse vérifiées. Plusieurs invocations avec le même scope
(reprise après interruption, plusieurs workers en parallèle) partagent ainsi
le même cache : si une prédiction y est déjà, le pipeline n'est jamais
rappelé pour elle.

Un scope porte toujours un seul `dataset` — un résultat ou une matrice ne
mélange jamais plusieurs datasets, cf. `docs/evaluation/storage.md`.

Trois axes de version indépendants (`params.PIPELINE_VERSION`,
`GENERATION_VERSION`, `EVAL_VERSION`) — quelle table dépend de quel axe,
cf. `docs/evaluation/storage.md`.

Params utilisés (`berlue.params`) : `MLOPS_DB_PATH`.
"""

import hashlib
import json
import logging
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from berlue.api.schemas import ConfusionMatrix, ConfusionRow
from berlue.core.schemas import Verdict
from berlue.evaluation.signals import SIGNALS_FORMAT_VERSION

if TYPE_CHECKING:
    from berlue.evaluation.gcp_result_store import GcpResultStore
from berlue.params import EVAL_STORE_TARGET, MLOPS_DB_PATH

logger = logging.getLogger(__name__)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _matrix_row_to_object(row: tuple[int, int, int, int, int, int]) -> ConfusionMatrix:
    """Reconstruit un `ConfusionMatrix` à partir des 6 colonnes à plat d'une
    ligne de table `eval_matrices*` — partagé par les 3 variantes (mode 1,
    mode 2 Berlue, mode 2 baseline)."""
    gt_true_true, gt_true_undecided, gt_true_false, gt_false_true, gt_false_undecided, gt_false_false = row
    return ConfusionMatrix(
        ground_truth_true=ConfusionRow(
            predicted_true=gt_true_true, predicted_undecided=gt_true_undecided, predicted_false=gt_true_false
        ),
        ground_truth_false=ConfusionRow(
            predicted_true=gt_false_true, predicted_undecided=gt_false_undecided, predicted_false=gt_false_false
        ),
    )


def _matrix_to_values(matrix: ConfusionMatrix) -> tuple[int, int, int, int, int, int]:
    """Inverse de `_matrix_row_to_object` — les 6 colonnes à plat, dans le même
    ordre."""
    return (
        matrix.ground_truth_true.predicted_true,
        matrix.ground_truth_true.predicted_undecided,
        matrix.ground_truth_true.predicted_false,
        matrix.ground_truth_false.predicted_true,
        matrix.ground_truth_false.predicted_undecided,
        matrix.ground_truth_false.predicted_false,
    )


def _where_from_filters(filters: dict) -> tuple[str, list]:
    """Clause `WHERE` + params à partir d'un dict — une clé absente ou à
    `None` est un joker (ignorée), pas une contrainte "colonne vide"."""
    items = [(k, v) for k, v in filters.items() if v is not None]
    if not items:
        return "", []
    where = "WHERE " + " AND ".join(f"{k}=?" for k, _ in items)
    return where, [v for _, v in items]


@dataclass(frozen=True)
class EvalScope:
    """Paramétrage global d'une évaluation — identifie un ensemble de
    résultats, pas un run précis. Un scope porte toujours un seul dataset.
    """

    dataset: str
    ratio: float
    model_id: str
    pipeline_version: str
    generation_version: str
    eval_version: str

    def as_dict(self, *fields: str) -> dict:
        """Sous-ensemble des champs du scope, dans l'ordre demandé — chaque
        table n'utilise que les axes de version dont elle dépend réellement
        (cf. docstring du module)."""
        return {f: getattr(self, f) for f in fields}


class LocalResultStore:
    """Cache de prédictions en SQLite local (`params.MLOPS_DB_PATH`)."""

    def __init__(self, db_path: str = MLOPS_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        with closing(self._connect()) as conn:
            self._create_tables(conn)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_predictions (
                dataset TEXT NOT NULL,
                ratio REAL NOT NULL,
                model_id TEXT NOT NULL,
                pipeline_version TEXT NOT NULL,
                eval_version TEXT NOT NULL,
                question_hash TEXT NOT NULL,
                answer_hash TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                ground_truth_label INTEGER NOT NULL,
                verdict TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                UNIQUE(dataset, ratio, model_id, pipeline_version, eval_version, question_hash, answer_hash)
            )
            """
        )

        # Signaux du pipeline AVANT fusion (affirmations, verdicts RAG, scores
        # SelfCheck). Ne dépend pas d'`eval_version` : la méthodologie d'éval n'a
        # aucune influence sur ce que le RAG et SelfCheck produisent pour un couple
        # (question, réponse) donné. Les garder permet de rejouer la fusion avec
        # d'autres `FUSION_*` sans rappeler le moindre modèle.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_signals (
                dataset TEXT NOT NULL,
                ratio REAL NOT NULL,
                model_id TEXT NOT NULL,
                pipeline_version TEXT NOT NULL,
                question_hash TEXT NOT NULL,
                answer_hash TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                signals TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                UNIQUE(dataset, ratio, model_id, pipeline_version, question_hash, answer_hash)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_matrices (
                dataset TEXT NOT NULL,
                ratio REAL NOT NULL,
                model_id TEXT NOT NULL,
                pipeline_version TEXT NOT NULL,
                eval_version TEXT NOT NULL,
                ground_truth_true_predicted_true INTEGER NOT NULL,
                ground_truth_true_predicted_undecided INTEGER NOT NULL,
                ground_truth_true_predicted_false INTEGER NOT NULL,
                ground_truth_false_predicted_true INTEGER NOT NULL,
                ground_truth_false_predicted_undecided INTEGER NOT NULL,
                ground_truth_false_predicted_false INTEGER NOT NULL,
                n_examples INTEGER NOT NULL,
                dataset_test_size INTEGER,
                computed_at TEXT NOT NULL,
                UNIQUE(dataset, ratio, model_id, pipeline_version, eval_version)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_answers (
                model_id TEXT NOT NULL,
                generation_version TEXT NOT NULL,
                question_hash TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                UNIQUE(model_id, generation_version, question_hash)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS judge_verdicts (
                model_id TEXT NOT NULL,
                generation_version TEXT NOT NULL,
                judge_model TEXT NOT NULL,
                eval_version TEXT NOT NULL,
                question_hash TEXT NOT NULL,
                question TEXT NOT NULL,
                verdict TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                UNIQUE(model_id, generation_version, judge_model, eval_version, question_hash)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_berlue_generated (
                dataset TEXT NOT NULL,
                ratio REAL NOT NULL,
                model_id TEXT NOT NULL,
                pipeline_version TEXT NOT NULL,
                generation_version TEXT NOT NULL,
                eval_version TEXT NOT NULL,
                question_hash TEXT NOT NULL,
                question TEXT NOT NULL,
                verdict TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                UNIQUE(dataset, ratio, model_id, pipeline_version, generation_version, eval_version, question_hash)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_baseline_generated (
                dataset TEXT NOT NULL,
                ratio REAL NOT NULL,
                model_id TEXT NOT NULL,
                generation_version TEXT NOT NULL,
                eval_version TEXT NOT NULL,
                question_hash TEXT NOT NULL,
                question TEXT NOT NULL,
                verdict TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                UNIQUE(dataset, ratio, model_id, generation_version, eval_version, question_hash)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_matrices_generated_berlue (
                dataset TEXT NOT NULL,
                ratio REAL NOT NULL,
                model_id TEXT NOT NULL,
                pipeline_version TEXT NOT NULL,
                generation_version TEXT NOT NULL,
                eval_version TEXT NOT NULL,
                ground_truth_true_predicted_true INTEGER NOT NULL,
                ground_truth_true_predicted_undecided INTEGER NOT NULL,
                ground_truth_true_predicted_false INTEGER NOT NULL,
                ground_truth_false_predicted_true INTEGER NOT NULL,
                ground_truth_false_predicted_undecided INTEGER NOT NULL,
                ground_truth_false_predicted_false INTEGER NOT NULL,
                n_examples INTEGER NOT NULL,
                dataset_test_size INTEGER,
                computed_at TEXT NOT NULL,
                UNIQUE(dataset, ratio, model_id, pipeline_version, generation_version, eval_version)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_matrices_generated_baseline (
                dataset TEXT NOT NULL,
                ratio REAL NOT NULL,
                model_id TEXT NOT NULL,
                generation_version TEXT NOT NULL,
                eval_version TEXT NOT NULL,
                ground_truth_true_predicted_true INTEGER NOT NULL,
                ground_truth_true_predicted_undecided INTEGER NOT NULL,
                ground_truth_true_predicted_false INTEGER NOT NULL,
                ground_truth_false_predicted_true INTEGER NOT NULL,
                ground_truth_false_predicted_undecided INTEGER NOT NULL,
                ground_truth_false_predicted_false INTEGER NOT NULL,
                n_examples INTEGER NOT NULL,
                dataset_test_size INTEGER,
                computed_at TEXT NOT NULL,
                UNIQUE(dataset, ratio, model_id, generation_version, eval_version)
            )
            """
        )
        conn.commit()

    # -- Mode 1 : résultats individuels ------------------------------------

    def get_verdict(self, scope: EvalScope, question: str, answer: str) -> Verdict | None:
        """Verdict déjà en cache pour cette prédiction, ou `None` si absente —
        un cache hit signifie qu'on ne rappelle pas le pipeline."""
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "eval_version")
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT verdict FROM eval_predictions
                WHERE dataset=? AND ratio=? AND model_id=? AND pipeline_version=? AND eval_version=?
                  AND question_hash=? AND answer_hash=?
                """,
                (*key.values(), _hash(question), _hash(answer)),
            ).fetchone()
        return Verdict(row[0]) if row else None

    def put_prediction(
        self, scope: EvalScope, question: str, answer: str, ground_truth_label: bool, verdict: Verdict
    ) -> bool:
        """Stocke une prédiction si elle n'est pas déjà en cache. Retourne
        `True` si c'est une nouvelle entrée, `False` si elle existait déjà
        (ex. course avec un autre worker sur la même question)."""
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "eval_version")
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO eval_predictions
                (dataset, ratio, model_id, pipeline_version, eval_version, question_hash, answer_hash,
                 question, answer, ground_truth_label, verdict, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    *key.values(),
                    _hash(question),
                    _hash(answer),
                    question,
                    answer,
                    int(ground_truth_label),
                    verdict.value,
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()
        return cursor.rowcount > 0

    def get_signals(self, scope: EvalScope, question: str, answer: str) -> dict | None:
        """Signaux pré-fusion déjà en cache, ou `None`. Un cache hit signifie qu'on ne
        rappelle ni le RAG ni SelfCheck : seule la fusion sera recalculée."""
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version")
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT signals FROM eval_signals
                WHERE dataset=? AND ratio=? AND model_id=? AND pipeline_version=?
                  AND question_hash=? AND answer_hash=?
                """,
                (*key.values(), _hash(question), _hash(answer)),
            ).fetchone()
        if not row:
            return None
        signals = json.loads(row[0])
        # Un format plus ancien est traité comme une absence : mieux vaut recalculer
        # que relire de travers.
        return signals if signals.get("format_version") == SIGNALS_FORMAT_VERSION else None

    def put_signals(self, scope: EvalScope, question: str, answer: str, signals: dict) -> bool:
        """Stocke les signaux pré-fusion s'ils ne sont pas déjà en cache. Retourne
        `True` si c'est une nouvelle entrée."""
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version")
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO eval_signals
                (dataset, ratio, model_id, pipeline_version, question_hash, answer_hash,
                 question, answer, signals, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    *key.values(),
                    _hash(question),
                    _hash(answer),
                    question,
                    answer,
                    json.dumps(signals, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()
        return cursor.rowcount > 0

    def list_predictions(self, scope: EvalScope) -> list[dict]:
        """Toutes les prédictions en cache pour `scope`, peu importe quelle
        invocation/quel worker les a produites."""
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "eval_version")
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT question, answer, ground_truth_label, verdict, computed_at
                FROM eval_predictions
                WHERE dataset=? AND ratio=? AND model_id=? AND pipeline_version=? AND eval_version=?
                """,
                tuple(key.values()),
            ).fetchall()
        return [
            {
                "question": question,
                "answer": answer,
                "ground_truth_label": bool(ground_truth_label),
                "verdict": Verdict(verdict),
                "computed_at": computed_at,
            }
            for question, answer, ground_truth_label, verdict, computed_at in rows
        ]

    def _group_count(self, table: str, columns: list[str]) -> list[dict]:
        """`SELECT <columns>, COUNT(*) FROM <table> GROUP BY <columns>` —
        partagé par les méthodes `list_*_scopes`, qui ne diffèrent que par
        la table et ses colonnes de clé."""
        cols = ", ".join(columns)
        with closing(self._connect()) as conn:
            rows = conn.execute(f"SELECT {cols}, COUNT(*) FROM {table} GROUP BY {cols}").fetchall()
        return [{**dict(zip(columns, row[:-1], strict=True)), "n_rows": row[-1]} for row in rows]

    def list_prediction_scopes(self) -> list[dict]:
        """Résumé de tous les scopes déjà présents dans `eval_predictions`
        (pas leur contenu ligne à ligne, cf. `list_predictions`) — pour
        explorer ce qui existe sans déjà connaître le scope exact."""
        return self._group_count(
            "eval_predictions", ["dataset", "ratio", "model_id", "pipeline_version", "eval_version"]
        )

    def flush_registry(self) -> None:
        """No-op côté local — le registre de scopes (`GcpResultStore`) existe
        pour éviter un scan complet des collections Firestore (pas de
        GROUP BY natif), un problème que SQLite n'a pas. Présent ici
        uniquement pour la parité d'interface : `run_eval.py` peut l'appeler
        sans savoir quel store est utilisé."""

    # -- Mode 1 : matrices ---------------------------------------------------

    def put_matrix(
        self, scope: EvalScope, matrix: ConfusionMatrix, n_examples: int, dataset_test_size: int | None = None
    ) -> None:
        """Stocke (ou remplace) la matrice de confusion finale (mode 1) d'un
        scope. `dataset_test_size` : taille du split de test officiel complet
        (indépendant de `n_examples`, qui peut être un sous-ensemble) — `None`
        si inconnu (dataset non reconnu, cf. `run_eval._official_dataset_test_size`)."""
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "eval_version")
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO eval_matrices
                (dataset, ratio, model_id, pipeline_version, eval_version,
                 ground_truth_true_predicted_true, ground_truth_true_predicted_undecided,
                 ground_truth_true_predicted_false, ground_truth_false_predicted_true,
                 ground_truth_false_predicted_undecided, ground_truth_false_predicted_false,
                 n_examples, dataset_test_size, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset, ratio, model_id, pipeline_version, eval_version) DO UPDATE SET
                    ground_truth_true_predicted_true=excluded.ground_truth_true_predicted_true,
                    ground_truth_true_predicted_undecided=excluded.ground_truth_true_predicted_undecided,
                    ground_truth_true_predicted_false=excluded.ground_truth_true_predicted_false,
                    ground_truth_false_predicted_true=excluded.ground_truth_false_predicted_true,
                    ground_truth_false_predicted_undecided=excluded.ground_truth_false_predicted_undecided,
                    ground_truth_false_predicted_false=excluded.ground_truth_false_predicted_false,
                    n_examples=excluded.n_examples,
                    dataset_test_size=excluded.dataset_test_size,
                    computed_at=excluded.computed_at
                """,
                (
                    *key.values(),
                    *_matrix_to_values(matrix),
                    n_examples,
                    dataset_test_size,
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()

    def get_matrix(self, scope: EvalScope) -> ConfusionMatrix | None:
        """Matrice de confusion (mode 1) déjà stockée pour `scope`, ou `None`
        si aucune n'a encore été construite."""
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "eval_version")
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT ground_truth_true_predicted_true, ground_truth_true_predicted_undecided,
                       ground_truth_true_predicted_false, ground_truth_false_predicted_true,
                       ground_truth_false_predicted_undecided, ground_truth_false_predicted_false
                FROM eval_matrices
                WHERE dataset=? AND ratio=? AND model_id=? AND pipeline_version=? AND eval_version=?
                """,
                tuple(key.values()),
            ).fetchone()
        return _matrix_row_to_object(row) if row else None

    def list_matrices(
        self,
        dataset: str | None = None,
        ratio: float | None = None,
        model_id: str | None = None,
        pipeline_version: str | None = None,
        eval_version: str | None = None,
    ) -> list[dict]:
        """Toutes les matrices déjà stockées correspondant aux filtres fournis
        (jokers si omis) — lecture seule, ne calcule ni ne complète rien."""
        where_clause, params = _where_from_filters(
            {
                "dataset": dataset,
                "ratio": ratio,
                "model_id": model_id,
                "pipeline_version": pipeline_version,
                "eval_version": eval_version,
            }
        )
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT dataset, ratio, model_id, pipeline_version, eval_version,
                       ground_truth_true_predicted_true, ground_truth_true_predicted_undecided,
                       ground_truth_true_predicted_false, ground_truth_false_predicted_true,
                       ground_truth_false_predicted_undecided, ground_truth_false_predicted_false,
                       n_examples, dataset_test_size, computed_at
                FROM eval_matrices {where_clause}
                """,
                params,
            ).fetchall()
        return [
            {
                "dataset": row[0],
                "ratio": row[1],
                "model_id": row[2],
                "pipeline_version": row[3],
                "eval_version": row[4],
                "matrix": _matrix_row_to_object(row[5:11]),
                "n_examples": row[11],
                "dataset_test_size": row[12],
                "computed_at": row[13],
            }
            for row in rows
        ]

    # -- Mode 2 : réponse générée + verdicts individuels ---------------------

    def get_generated_answer(self, model_id: str, generation_version: str, question: str) -> str | None:
        """Réponse déjà générée par `model_id`/`generation_version` pour cette
        question, ou `None` si absente — indépendant de `dataset`/`ratio`
        (une réponse générée ne dépend pas du split train/test choisi)."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT answer FROM llm_answers WHERE model_id=? AND generation_version=? AND question_hash=?",
                (model_id, generation_version, _hash(question)),
            ).fetchone()
        return row[0] if row else None

    def put_generated_answer(self, model_id: str, generation_version: str, question: str, answer: str) -> bool:
        """Stocke une réponse générée si elle n'est pas déjà en cache. Retourne
        `True` si nouvelle, `False` si déjà présente."""
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO llm_answers
                (model_id, generation_version, question_hash, question, answer, computed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (model_id, generation_version, _hash(question), question, answer, datetime.now(UTC).isoformat()),
            )
            conn.commit()
        return cursor.rowcount > 0

    def list_generated_answer_scopes(self) -> list[dict]:
        """Résumé de tous les couples `(model_id, generation_version)` déjà
        présents dans `llm_answers`."""
        return self._group_count("llm_answers", ["model_id", "generation_version"])

    def list_generated_answers(self, model_id: str, generation_version: str) -> set[str]:
        """Questions déjà répondues pour `model_id`/`generation_version` —
        une seule requête, pas un `get_generated_answer` par question (cf.
        `coverage_report`, mode généré)."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT question FROM llm_answers WHERE model_id=? AND generation_version=?",
                (model_id, generation_version),
            ).fetchall()
        return {row[0] for row in rows}

    def get_judge_verdict(
        self, model_id: str, generation_version: str, judge_model: str, eval_version: str, question: str
    ) -> Verdict | None:
        """Verdict du juge déjà en cache pour la réponse générée par
        `model_id`/`generation_version` à cette question, ou `None` si
        absent — indépendant de `dataset`/`ratio`/`pipeline_version` (le juge
        ne voit jamais le verdict de Berlue, seulement la réponse générée et
        les références du dataset)."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT verdict FROM judge_verdicts
                WHERE model_id=? AND generation_version=? AND judge_model=? AND eval_version=? AND question_hash=?
                """,
                (model_id, generation_version, judge_model, eval_version, _hash(question)),
            ).fetchone()
        return Verdict(row[0]) if row else None

    def put_judge_verdict(
        self,
        model_id: str,
        generation_version: str,
        judge_model: str,
        eval_version: str,
        question: str,
        verdict: Verdict,
    ) -> bool:
        """Stocke un verdict de juge s'il n'est pas déjà en cache. Retourne
        `True` si nouveau, `False` si déjà présent."""
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO judge_verdicts
                (model_id, generation_version, judge_model, eval_version, question_hash, question, verdict, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id,
                    generation_version,
                    judge_model,
                    eval_version,
                    _hash(question),
                    question,
                    verdict.value,
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()
        return cursor.rowcount > 0

    def list_judge_verdict_scopes(self) -> list[dict]:
        """Résumé de tous les combos `(model_id, generation_version,
        judge_model, eval_version)` déjà présents dans `judge_verdicts`."""
        return self._group_count("judge_verdicts", ["model_id", "generation_version", "judge_model", "eval_version"])

    def get_generated_berlue_verdict(self, scope: EvalScope, question: str) -> Verdict | None:
        """Verdict Berlue déjà en cache pour la réponse générée (mode 2) de
        `scope` sur cette question, ou `None` si absent."""
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "generation_version", "eval_version")
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT verdict FROM eval_berlue_generated
                WHERE dataset=? AND ratio=? AND model_id=? AND pipeline_version=? AND generation_version=?
                  AND eval_version=? AND question_hash=?
                """,
                (*key.values(), _hash(question)),
            ).fetchone()
        return Verdict(row[0]) if row else None

    def put_generated_berlue_verdict(self, scope: EvalScope, question: str, verdict: Verdict) -> bool:
        """Stocke un verdict Berlue sur une réponse générée (mode 2) s'il n'est
        pas déjà en cache. Retourne `True` si nouveau, `False` si déjà présent."""
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "generation_version", "eval_version")
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO eval_berlue_generated
                (dataset, ratio, model_id, pipeline_version, generation_version, eval_version,
                 question_hash, question, verdict, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*key.values(), _hash(question), question, verdict.value, datetime.now(UTC).isoformat()),
            )
            conn.commit()
        return cursor.rowcount > 0

    def list_generated_berlue_verdict_scopes(self) -> list[dict]:
        """Résumé de tous les scopes déjà présents dans
        `eval_berlue_generated`."""
        return self._group_count(
            "eval_berlue_generated",
            ["dataset", "ratio", "model_id", "pipeline_version", "generation_version", "eval_version"],
        )

    def get_generated_baseline_verdict(
        self, dataset: str, ratio: float, model_id: str, generation_version: str, eval_version: str, question: str
    ) -> Verdict | None:
        """Verdict baseline déjà en cache pour la réponse générée (mode 2) sur
        cette question, ou `None` si absent — pas de `pipeline_version` (la
        baseline ne dépend pas de la version du pipeline Berlue)."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT verdict FROM eval_baseline_generated
                WHERE dataset=? AND ratio=? AND model_id=? AND generation_version=?
                  AND eval_version=? AND question_hash=?
                """,
                (dataset, ratio, model_id, generation_version, eval_version, _hash(question)),
            ).fetchone()
        return Verdict(row[0]) if row else None

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
        """Stocke un verdict baseline sur une réponse générée (mode 2) s'il
        n'est pas déjà en cache. Retourne `True` si nouveau, `False` si déjà
        présent."""
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO eval_baseline_generated
                (dataset, ratio, model_id, generation_version, eval_version,
                 question_hash, question, verdict, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset,
                    ratio,
                    model_id,
                    generation_version,
                    eval_version,
                    _hash(question),
                    question,
                    verdict.value,
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()
        return cursor.rowcount > 0

    def list_generated_baseline_verdict_scopes(self) -> list[dict]:
        """Résumé de tous les scopes déjà présents dans
        `eval_baseline_generated` (pas de `pipeline_version`)."""
        return self._group_count(
            "eval_baseline_generated", ["dataset", "ratio", "model_id", "generation_version", "eval_version"]
        )

    # -- Mode 2 : matrices ----------------------------------------------------

    def put_generated_berlue_matrix(
        self, scope: EvalScope, matrix: ConfusionMatrix, n_examples: int, dataset_test_size: int | None = None
    ) -> None:
        """Stocke (ou remplace) la matrice de confusion Berlue-vs-juge (mode 2)
        d'un scope. `dataset_test_size` : nombre de questions valides (réf.
        correcte + incorrecte) du split de test officiel complet — `None` si
        inconnu."""
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "generation_version", "eval_version")
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO eval_matrices_generated_berlue
                (dataset, ratio, model_id, pipeline_version, generation_version, eval_version,
                 ground_truth_true_predicted_true, ground_truth_true_predicted_undecided,
                 ground_truth_true_predicted_false, ground_truth_false_predicted_true,
                 ground_truth_false_predicted_undecided, ground_truth_false_predicted_false,
                 n_examples, dataset_test_size, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset, ratio, model_id, pipeline_version, generation_version, eval_version) DO UPDATE SET
                    ground_truth_true_predicted_true=excluded.ground_truth_true_predicted_true,
                    ground_truth_true_predicted_undecided=excluded.ground_truth_true_predicted_undecided,
                    ground_truth_true_predicted_false=excluded.ground_truth_true_predicted_false,
                    ground_truth_false_predicted_true=excluded.ground_truth_false_predicted_true,
                    ground_truth_false_predicted_undecided=excluded.ground_truth_false_predicted_undecided,
                    ground_truth_false_predicted_false=excluded.ground_truth_false_predicted_false,
                    n_examples=excluded.n_examples,
                    dataset_test_size=excluded.dataset_test_size,
                    computed_at=excluded.computed_at
                """,
                (
                    *key.values(),
                    *_matrix_to_values(matrix),
                    n_examples,
                    dataset_test_size,
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()

    def get_generated_berlue_matrix(self, scope: EvalScope) -> ConfusionMatrix | None:
        """Matrice Berlue-vs-juge (mode 2) déjà stockée pour `scope`, ou `None`
        si aucune n'a encore été construite."""
        key = scope.as_dict("dataset", "ratio", "model_id", "pipeline_version", "generation_version", "eval_version")
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT ground_truth_true_predicted_true, ground_truth_true_predicted_undecided,
                       ground_truth_true_predicted_false, ground_truth_false_predicted_true,
                       ground_truth_false_predicted_undecided, ground_truth_false_predicted_false
                FROM eval_matrices_generated_berlue
                WHERE dataset=? AND ratio=? AND model_id=? AND pipeline_version=?
                  AND generation_version=? AND eval_version=?
                """,
                tuple(key.values()),
            ).fetchone()
        return _matrix_row_to_object(row) if row else None

    def list_generated_berlue_matrices(
        self,
        dataset: str | None = None,
        ratio: float | None = None,
        model_id: str | None = None,
        pipeline_version: str | None = None,
        generation_version: str | None = None,
        eval_version: str | None = None,
    ) -> list[dict]:
        """Toutes les matrices Berlue-vs-juge (mode 2) déjà stockées
        correspondant aux filtres fournis (jokers si omis)."""
        where_clause, params = _where_from_filters(
            {
                "dataset": dataset,
                "ratio": ratio,
                "model_id": model_id,
                "pipeline_version": pipeline_version,
                "generation_version": generation_version,
                "eval_version": eval_version,
            }
        )
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT dataset, ratio, model_id, pipeline_version, generation_version, eval_version,
                       ground_truth_true_predicted_true, ground_truth_true_predicted_undecided,
                       ground_truth_true_predicted_false, ground_truth_false_predicted_true,
                       ground_truth_false_predicted_undecided, ground_truth_false_predicted_false,
                       n_examples, dataset_test_size, computed_at
                FROM eval_matrices_generated_berlue {where_clause}
                """,
                params,
            ).fetchall()
        return [
            {
                "dataset": row[0],
                "ratio": row[1],
                "model_id": row[2],
                "pipeline_version": row[3],
                "generation_version": row[4],
                "eval_version": row[5],
                "matrix": _matrix_row_to_object(row[6:12]),
                "n_examples": row[12],
                "dataset_test_size": row[13],
                "computed_at": row[14],
            }
            for row in rows
        ]

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
        """Stocke (ou remplace) la matrice de confusion baseline-vs-juge
        (mode 2) — pas de `pipeline_version`, la baseline ne dépend pas de la
        version du pipeline Berlue. `dataset_test_size` : nombre de questions
        valides du split de test officiel complet, `None` si inconnu."""
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO eval_matrices_generated_baseline
                (dataset, ratio, model_id, generation_version, eval_version,
                 ground_truth_true_predicted_true, ground_truth_true_predicted_undecided,
                 ground_truth_true_predicted_false, ground_truth_false_predicted_true,
                 ground_truth_false_predicted_undecided, ground_truth_false_predicted_false,
                 n_examples, dataset_test_size, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset, ratio, model_id, generation_version, eval_version) DO UPDATE SET
                    ground_truth_true_predicted_true=excluded.ground_truth_true_predicted_true,
                    ground_truth_true_predicted_undecided=excluded.ground_truth_true_predicted_undecided,
                    ground_truth_true_predicted_false=excluded.ground_truth_true_predicted_false,
                    ground_truth_false_predicted_true=excluded.ground_truth_false_predicted_true,
                    ground_truth_false_predicted_undecided=excluded.ground_truth_false_predicted_undecided,
                    ground_truth_false_predicted_false=excluded.ground_truth_false_predicted_false,
                    n_examples=excluded.n_examples,
                    dataset_test_size=excluded.dataset_test_size,
                    computed_at=excluded.computed_at
                """,
                (
                    dataset,
                    ratio,
                    model_id,
                    generation_version,
                    eval_version,
                    *_matrix_to_values(matrix),
                    n_examples,
                    dataset_test_size,
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()

    def get_generated_baseline_matrix(
        self, dataset: str, ratio: float, model_id: str, generation_version: str, eval_version: str
    ) -> ConfusionMatrix | None:
        """Matrice baseline-vs-juge (mode 2) déjà stockée, ou `None` si aucune
        n'a encore été construite."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT ground_truth_true_predicted_true, ground_truth_true_predicted_undecided,
                       ground_truth_true_predicted_false, ground_truth_false_predicted_true,
                       ground_truth_false_predicted_undecided, ground_truth_false_predicted_false
                FROM eval_matrices_generated_baseline
                WHERE dataset=? AND ratio=? AND model_id=? AND generation_version=? AND eval_version=?
                """,
                (dataset, ratio, model_id, generation_version, eval_version),
            ).fetchone()
        return _matrix_row_to_object(row) if row else None

    def list_generated_baseline_matrices(
        self,
        dataset: str | None = None,
        ratio: float | None = None,
        model_id: str | None = None,
        generation_version: str | None = None,
        eval_version: str | None = None,
    ) -> list[dict]:
        """Toutes les matrices baseline-vs-juge (mode 2) déjà stockées
        correspondant aux filtres fournis (jokers si omis) — pas de
        `pipeline_version` (la baseline n'en dépend pas)."""
        where_clause, params = _where_from_filters(
            {
                "dataset": dataset,
                "ratio": ratio,
                "model_id": model_id,
                "generation_version": generation_version,
                "eval_version": eval_version,
            }
        )
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT dataset, ratio, model_id, generation_version, eval_version,
                       ground_truth_true_predicted_true, ground_truth_true_predicted_undecided,
                       ground_truth_true_predicted_false, ground_truth_false_predicted_true,
                       ground_truth_false_predicted_undecided, ground_truth_false_predicted_false,
                       n_examples, dataset_test_size, computed_at
                FROM eval_matrices_generated_baseline {where_clause}
                """,
                params,
            ).fetchall()
        return [
            {
                "dataset": row[0],
                "ratio": row[1],
                "model_id": row[2],
                "generation_version": row[3],
                "eval_version": row[4],
                "matrix": _matrix_row_to_object(row[5:11]),
                "n_examples": row[11],
                "dataset_test_size": row[12],
                "computed_at": row[13],
            }
            for row in rows
        ]

    # -- Purge ----------------------------------------------------------------

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
        """Supprime ce qui correspond aux filtres fournis — chaque filtre
        omis (`None`) est un joker.

        Un filtre sans colonne correspondante dans une table est ignoré **pour
        cette table** — purger un scope complet doit atteindre les tables qui
        n'ont pas tous ses axes (ex. `eval_baseline_generated` n'a pas de
        `pipeline_version`).

        En revanche, si **aucun** des filtres demandés ne s'applique à une table,
        elle est **exclue** : la suppression y serait non bornée alors qu'on a
        demandé quelque chose de précis. Sans cette garde,
        `--purge-pipeline-version X` vidait intégralement `llm_answers` et
        `judge_verdicts`, qui n'ont pas cette colonne. `scope` limite à "results" (résultats individuels,
        5 tables), "matrices" (3 tables), "signals" (les signaux pré-fusion
        seuls), "fusion" (prédictions + matrice du mode 1, en **gardant** les
        signaux — de quoi rejouer la seule fusion avec d'autres `FUSION_*` sans
        rappeler RAG ni SelfCheck), ou "all" (les 9, défaut). Retourne le nombre
        de lignes supprimées par table.
        """
        scopes_valides = ("all", "results", "matrices", "signals", "fusion")
        if scope not in scopes_valides:
            raise ValueError(f"❌ scope de purge invalide : {scope!r} (doit être {', '.join(scopes_valides)})")

        mode1_filters = {
            "dataset": dataset,
            "ratio": ratio,
            "model_id": model_id,
            "pipeline_version": pipeline_version,
            "eval_version": eval_version,
        }
        mode1_gen_filters = {**mode1_filters, "generation_version": generation_version}
        # Les signaux ne portent pas d'eval_version (cf. création de la table).
        signals_filters = {k: v for k, v in mode1_filters.items() if k != "eval_version"}
        answer_filters = {"model_id": model_id, "generation_version": generation_version}
        judge_filters = {**answer_filters, "judge_model": judge_model, "eval_version": eval_version}
        baseline_filters = {
            "dataset": dataset,
            "ratio": ratio,
            "model_id": model_id,
            "generation_version": generation_version,
            "eval_version": eval_version,
        }

        # Tous les filtres explicitement demandés, quelle que soit la table.
        demandes = {
            k: v
            for k, v in (
                ("dataset", dataset),
                ("ratio", ratio),
                ("model_id", model_id),
                ("pipeline_version", pipeline_version),
                ("generation_version", generation_version),
                ("eval_version", eval_version),
                ("judge_model", judge_model),
            )
            if v is not None
        }

        counts: dict[str, int] = {}
        with closing(self._connect()) as conn:

            def delete(table: str, filters: dict) -> int:
                # Aucun des filtres demandés ne s'applique à cette table : la
                # suppression y serait non bornée, on s'abstient.
                if demandes and not any(k in filters for k in demandes):
                    logger.info(
                        "⏭️  %s non purgée : aucun des filtres demandés (%s) ne s'y applique.",
                        table,
                        ", ".join(demandes),
                    )
                    return 0
                where_clause, params = _where_from_filters(filters)
                return conn.execute(f"DELETE FROM {table} {where_clause}", params).rowcount

            if scope in ("all", "results", "fusion"):
                counts["predictions_deleted"] = delete("eval_predictions", mode1_filters)
            if scope in ("all", "results"):
                counts["llm_answers_deleted"] = delete("llm_answers", answer_filters)
                counts["judge_verdicts_deleted"] = delete("judge_verdicts", judge_filters)
                counts["berlue_generated_deleted"] = delete("eval_berlue_generated", mode1_gen_filters)
                counts["baseline_generated_deleted"] = delete("eval_baseline_generated", baseline_filters)
            if scope in ("all", "signals"):
                counts["signals_deleted"] = delete("eval_signals", signals_filters)
            if scope in ("all", "matrices", "fusion"):
                counts["matrices_deleted"] = delete("eval_matrices", mode1_filters)
            # Les matrices du mode 2 ne sont pas des sorties de fusion du mode 1 :
            # "fusion" ne doit pas y toucher.
            if scope in ("all", "matrices"):
                counts["matrices_generated_berlue_deleted"] = delete(
                    "eval_matrices_generated_berlue", mode1_gen_filters
                )
                counts["matrices_generated_baseline_deleted"] = delete(
                    "eval_matrices_generated_baseline", baseline_filters
                )
            conn.commit()

        return counts


def get_result_store(target: str = EVAL_STORE_TARGET) -> LocalResultStore | GcpResultStore:
    """Retourne le store de résultats d'évaluation selon `target`
    (`params.EVAL_STORE_TARGET` par défaut, "local" ou "gcp"). Import local
    du store GCP pour éviter un import circulaire (il importe des helpers de
    ce module)."""
    if target == "local":
        return LocalResultStore()
    if target == "gcp":
        from berlue.evaluation.gcp_result_store import GcpResultStore

        return GcpResultStore()
    raise ValueError(f"❌ EVAL_STORE_TARGET invalide : {target!r} (doit être local ou gcp)")
