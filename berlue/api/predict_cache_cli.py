"""Lignes de commande du cache de prédiction — listage et purge.

Un module d'entrée plutôt que du Python inline dans le Makefile : les règles
make ne doivent pas contenir de logique, et une commande testable vaut mieux
qu'une ligne shell.
"""

import argparse
import sys

from berlue.api.predict_cache import normaliser_question, satisfait
from berlue.evaluation.result_store import get_result_store


def _lister() -> int:
    entrees = get_result_store().list_predict_cache()
    if not entrees:
        print("📭 Cache de prédiction vide.")
        return 0
    print(f"📦 {len(entrees)} entrée(s) dans le cache de prédiction :")
    for e in entrees:
        print(f"  {e['computed_at'][:19]}  t={e['temperature']:<4} {e['generator_model']:<14} {e['question'][:60]}")
        print(f"     extraction {e['extract_model']}, RAG {e['rag_model']}")
    return 0


def _purger(args) -> int:
    supprimees = get_result_store().purge_predict_cache(
        question=args.question,
        temperature=args.temperature,
        generator_model=args.model,
    )
    filtres = [f for f in (args.question, args.temperature, args.model) if f is not None]
    portee = "filtré" if filtres else "intégral"
    print(f"🧹 Purge {portee} du cache de prédiction : {supprimees} entrée(s) supprimée(s).")
    return 0


def _publier(args) -> int:
    """Copie le cache local vers le magasin GCP.

    Sens unique : rapatrier la production sur un poste de développement n'a pas
    d'usage, et l'ajouter doublerait la surface d'erreur d'une commande qui
    écrit dans une base partagée.
    """
    local = get_result_store(target="local")
    try:
        distant = get_result_store(target="gcp")
    except Exception as e:
        print(f"❌ Magasin GCP inaccessible : {e}")
        print("   👉 Vérifiez vos identifiants et vos droits Firestore.")
        return 1

    entrees = local.list_predict_cache()
    if args.question is not None:
        cle = normaliser_question(args.question)
        entrees = [e for e in entrees if normaliser_question(e["question"]) == cle]

    if not entrees:
        print("📭 Rien à publier.")
        return 0

    pousses = remplaces = ignores = 0
    for resume in entrees:
        entree = local.get_predict_cache(resume["question"], resume["temperature"])
        if entree is None:
            continue
        modeles = (entree["generator_model"], entree["extract_model"], entree["rag_model"])

        existante = distant.get_predict_cache(resume["question"], resume["temperature"])
        if existante is not None and not args.force:
            distants = (
                existante["generator_model"],
                existante["extract_model"],
                existante["rag_model"],
            )
            # L'entrée distante est conservée si elle vaut au moins la locale.
            # Un poste de développement travaille souvent avec de petits
            # modèles, faute de GPU : écraser sans condition dégraderait le
            # cache de production.
            if satisfait(modeles, distants):
                ignores += 1
                continue

        distant.put_predict_cache(
            entree["question"],
            resume["temperature"],
            *modeles,
            entree["payload"],
        )
        if existante is None:
            pousses += 1
        else:
            remplaces += 1

    forcee = " (--force)" if args.force else ""
    print(f"☁️  Publication vers GCP{forcee} : {pousses} ajoutée(s), {remplaces} remplacée(s), {ignores} ignorée(s).")
    if ignores:
        print("   Les entrées ignorées sont déjà en cache côté GCP avec des modèles au moins aussi gros.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cache des prédictions de /predict.")
    sous = parser.add_subparsers(dest="commande", required=True)

    sous.add_parser("list", help="Affiche le contenu du cache.")

    purge = sous.add_parser("purge", help="Vide le cache, éventuellement filtré.")
    purge.add_argument("--question", default=None, help="Ne purger que cette question (casse et espaces indifférents).")
    purge.add_argument("--temperature", type=float, default=None, help="Ne purger que cette température.")
    purge.add_argument("--model", default=None, help="Ne purger que les entrées produites par ce générateur.")

    publier = sous.add_parser("push", help="Publie le cache local vers le magasin GCP.")
    publier.add_argument("--question", default=None, help="Ne publier que cette question.")
    publier.add_argument(
        "--force",
        action="store_true",
        help="Remplacer même quand l'entrée distante vient de modèles plus gros.",
    )

    args = parser.parse_args(argv)
    if args.commande == "list":
        return _lister()
    if args.commande == "push":
        return _publier(args)
    return _purger(args)


if __name__ == "__main__":
    sys.exit(main())
