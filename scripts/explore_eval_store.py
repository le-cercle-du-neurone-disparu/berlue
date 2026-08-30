"""Affiche un résumé de ce qui existe dans le store d'éval (résultats
individuels ou matrices) — local ou GCP selon `EVAL_STORE_TARGET`/
`BERLUE_EVAL_STORE_TARGET`. Usage interne à `make evaluate_explore_results`/
`evaluate_explore_matrices`, pas destiné à un appel direct.
"""

import argparse
import json

from berlue.evaluation.result_store import get_result_store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", required=True, choices=["results", "matrices"])
    args = parser.parse_args()

    store = get_result_store()
    print(f"📦 Store : {type(store).__name__}\n")

    if args.kind == "results":
        tables = [
            ("eval_predictions (mode 1)", store.list_prediction_scopes),
            ("llm_answers (mode 2)", store.list_generated_answer_scopes),
            ("judge_verdicts (mode 2)", store.list_judge_verdict_scopes),
            ("eval_berlue_generated (mode 2)", store.list_generated_berlue_verdict_scopes),
            ("eval_baseline_generated (mode 2)", store.list_generated_baseline_verdict_scopes),
        ]
    else:
        tables = [
            ("eval_matrices (mode 1)", store.list_matrices),
            ("eval_matrices_generated_berlue (mode 2)", store.list_generated_berlue_matrices),
            ("eval_matrices_generated_baseline (mode 2)", store.list_generated_baseline_matrices),
        ]

    for label, list_fn in tables:
        entries = list_fn()
        print(f"=== {label} — {len(entries)} scope(s) ===")
        for entry in entries:
            print(json.dumps(entry, default=str, ensure_ascii=False))
        print()


if __name__ == "__main__":
    main()
