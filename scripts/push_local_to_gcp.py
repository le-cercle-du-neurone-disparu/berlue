"""Pousse les résultats/matrices d'un scope du store local vers GCP — utile
pour partager un cache déjà rempli en local avec l'équipe. Couvre les
prédictions + matrice mode 1, et les 2 matrices mode 2 (elles ont une
lecture à la fois par scope, avec `n_examples`). Ne couvre pas encore le
détail ligne à ligne des tables individuelles du mode 2 (`llm_answers`,
`judge_verdicts`, `eval_berlue_generated`, `eval_baseline_generated`) — ces
tables n'ont aujourd'hui qu'un résumé de comptage par scope
(`list_*_scopes`), pas un listing complet des lignes ; à ajouter si le
besoin se confirme.

`--push-scope matrices` (résultats individuels jamais poussés vers
Firestore) est le workflow recommandé pour le travail courant, pour ne pas
mordre sur son quota gratuit — voir `docs/evaluation/storage.md`.
Usage interne à `make evaluate_push_to_gcp`, pas destiné à un appel direct.
"""

import argparse

from berlue.evaluation.gcp_result_store import GcpResultStore
from berlue.evaluation.result_store import EvalScope, LocalResultStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--ratio", type=float, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--pipeline-version", required=True)
    parser.add_argument("--generation-version", required=True)
    parser.add_argument("--eval-version", required=True)
    parser.add_argument("--push-scope", choices=("all", "results", "matrices"), default="all")
    args = parser.parse_args()

    scope = EvalScope(
        dataset=args.dataset,
        ratio=args.ratio,
        model_id=args.model_id,
        pipeline_version=args.pipeline_version,
        generation_version=args.generation_version,
        eval_version=args.eval_version,
    )

    local = LocalResultStore()
    gcp = GcpResultStore()

    print(f"📤 Push {scope} (scope={args.push_scope}) : local -> GCP")

    if args.push_scope in ("all", "results"):
        predictions = local.list_predictions(scope)
        for p in predictions:
            gcp.put_prediction(scope, p["question"], p["answer"], p["ground_truth_label"], p["verdict"])
        print(
            f"✅ eval_predictions : {len(predictions)} ligne(s) poussée(s) "
            "(dédoublonnage automatique si déjà présentes)"
        )
    else:
        print("— eval_predictions : ignoré (push-scope=matrices)")

    if args.push_scope not in ("all", "matrices"):
        gcp.flush_registry()
        print("🎉 Push terminé.")
        return

    matrices = local.list_matrices(
        dataset=scope.dataset,
        ratio=scope.ratio,
        model_id=scope.model_id,
        pipeline_version=scope.pipeline_version,
        eval_version=scope.eval_version,
    )
    if matrices:
        gcp.put_matrix(scope, matrices[0]["matrix"], n_examples=matrices[0]["n_examples"])
        print("✅ eval_matrices : matrice poussée")
    else:
        print("— eval_matrices : rien à pousser (pas encore construite en local)")

    berlue_matrices = local.list_generated_berlue_matrices(
        dataset=scope.dataset,
        ratio=scope.ratio,
        model_id=scope.model_id,
        pipeline_version=scope.pipeline_version,
        generation_version=scope.generation_version,
        eval_version=scope.eval_version,
    )
    if berlue_matrices:
        gcp.put_generated_berlue_matrix(
            scope, berlue_matrices[0]["matrix"], n_examples=berlue_matrices[0]["n_examples"]
        )
        print("✅ eval_matrices_generated_berlue : matrice poussée")

    baseline_matrices = local.list_generated_baseline_matrices(
        dataset=scope.dataset,
        ratio=scope.ratio,
        model_id=scope.model_id,
        generation_version=scope.generation_version,
        eval_version=scope.eval_version,
    )
    if baseline_matrices:
        gcp.put_generated_baseline_matrix(
            scope.dataset,
            scope.ratio,
            scope.model_id,
            scope.generation_version,
            scope.eval_version,
            baseline_matrices[0]["matrix"],
            n_examples=baseline_matrices[0]["n_examples"],
        )
        print("✅ eval_matrices_generated_baseline : matrice poussée")

    gcp.flush_registry()
    print("🎉 Push terminé.")


if __name__ == "__main__":
    main()
