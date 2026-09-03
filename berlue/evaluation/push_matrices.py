"""Publie les matrices de confusion locales vers le magasin GCP.

Seules les matrices : ce sont elles qu'on partage et qu'on relit, quelques
lignes contre des milliers pour les résultats individuels. Les prédictions et
les réponses générées restent locales — les republier coûterait des milliers
d'écritures Firestore pour des données que personne ne consulte directement.

Sens unique, local vers GCP.
"""

import argparse
import sqlite3
import sys
from contextlib import closing

from berlue.api.schemas import ConfusionMatrix, ConfusionRow
from berlue.evaluation.result_store import EvalScope, LocalResultStore, get_result_store

_COLONNES_MATRICE = (
    "ground_truth_true_predicted_true",
    "ground_truth_true_predicted_undecided",
    "ground_truth_true_predicted_false",
    "ground_truth_false_predicted_true",
    "ground_truth_false_predicted_undecided",
    "ground_truth_false_predicted_false",
)


def _matrice(r: sqlite3.Row) -> ConfusionMatrix:
    return ConfusionMatrix(
        ground_truth_true=ConfusionRow(
            predicted_true=r["ground_truth_true_predicted_true"],
            predicted_undecided=r["ground_truth_true_predicted_undecided"],
            predicted_false=r["ground_truth_true_predicted_false"],
        ),
        ground_truth_false=ConfusionRow(
            predicted_true=r["ground_truth_false_predicted_true"],
            predicted_undecided=r["ground_truth_false_predicted_undecided"],
            predicted_false=r["ground_truth_false_predicted_false"],
        ),
    )


def pousser(distant, chemin_local: str) -> dict[str, int]:
    """Copie les matrices du mode généré vers `distant`. Rend le décompte par table."""
    comptes = {"berlue": 0, "baseline": 0}
    with closing(sqlite3.connect(chemin_local)) as conn:
        conn.row_factory = sqlite3.Row

        for r in conn.execute("SELECT * FROM eval_matrices_generated_berlue"):
            scope = EvalScope(
                dataset=r["dataset"],
                ratio=r["ratio"],
                model_id=r["model_id"],
                pipeline_version=r["pipeline_version"],
                generation_version=r["generation_version"],
                eval_version=r["eval_version"],
            )
            distant.put_generated_berlue_matrix(scope, _matrice(r), r["n_examples"], r["dataset_test_size"])
            comptes["berlue"] += 1
            print(f"  ☁️  berlue   {r['dataset']:12} ratio={r['ratio']} {r['model_id']}")

        for r in conn.execute("SELECT * FROM eval_matrices_generated_baseline"):
            distant.put_generated_baseline_matrix(
                r["dataset"],
                r["ratio"],
                r["model_id"],
                r["generation_version"],
                r["eval_version"],
                _matrice(r),
                r["n_examples"],
                r["dataset_test_size"],
            )
            comptes["baseline"] += 1
            print(f"  ☁️  baseline {r['dataset']:12} ratio={r['ratio']} {r['model_id']}")

    return comptes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publie les matrices locales vers GCP.")
    parser.parse_args(argv)

    local = LocalResultStore()
    try:
        distant = get_result_store(target="gcp")
    except Exception as e:
        print(f"❌ Magasin GCP inaccessible : {e}")
        return 1

    comptes = pousser(distant, str(local.db_path))
    total = sum(comptes.values())
    if not total:
        print("📭 Aucune matrice locale à publier.")
        return 0

    # Le registre de scopes n'est écrit qu'au flush : sans lui, les matrices sont
    # dans Firestore mais invisibles des listings.
    if hasattr(distant, "flush_registry"):
        distant.flush_registry()
    print(f"✅ {total} matrice(s) publiée(s) : {comptes['berlue']} Berlue, {comptes['baseline']} baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
