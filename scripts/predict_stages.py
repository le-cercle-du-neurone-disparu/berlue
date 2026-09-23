"""Décompose chaque /predict hors cache en étapes, à partir des logs DEBUG de l'API.

Le pipeline ne chronomètre pas ses étapes : on les lit dans l'horodatage des
logs, qui ne sont assez détaillés qu'avec `BERLUE_LOG_LEVEL=DEBUG` sur le
service. Logs à extraire au préalable, par exemple :

    gcloud logging read 'resource.type="cloud_run_revision" AND
      resource.labels.service_name="berlue-api-test" AND timestamp>="<début>"' \\
      --order asc --limit 3000 --format=json > logs.json
    python scripts/predict_stages.py logs.json

Colonnes (secondes) :
  avant   génération de la réponse, extraction des affirmations, embedding
  échant  les K échantillons SelfCheck
  NLI     les passages DeBERTa de SelfCheck
  SC      branche SelfCheck entière (échant + NLI)
  RAG     branche RAG entière — elle tourne en même temps que SelfCheck
  fin     fusion et écriture dans le cache Firestore
"""

import datetime
import json
import sys


def horodatage(entree):
    return datetime.datetime.fromisoformat(entree["timestamp"].replace("Z", "+00:00"))


def requetes(entrees):
    courante = None
    for entree in entrees:
        lignes = (entree.get("textPayload") or "").splitlines()
        ligne = lignes[0] if lignes else ""
        if "Cache ignoré" in ligne:
            courante = {"debut": horodatage(entree)}
        elif courante is None:
            continue
        elif "Calcul des verdicts du RAG" in ligne:
            courante["branches"] = horodatage(entree)
            courante["affirmations"] = int(ligne.split(" sur ")[1].split()[0])
        elif "RAG · affirmation" in ligne:
            courante["fin_rag"] = horodatage(entree)
        elif "selfcheck-nli" in ligne:
            courante["debut_nli"] = horodatage(entree)
        elif "SelfCheck GLOBAL" in ligne:
            courante["fin_selfcheck"] = horodatage(entree)
        elif "Fusion] Synthèse" in ligne:
            courante["fusion"] = horodatage(entree)
        elif "POST /predict" in ligne:
            courante["fin"] = horodatage(entree)
            yield courante
            courante = None


def main(chemin):
    def s(a, b):
        return (b - a).total_seconds()

    print(f"{'aff':>3} {'total':>6} {'avant':>6} {'échant':>6} {'NLI':>6} {'SC':>6} {'RAG':>6} {'fin':>5}")
    with open(chemin) as f:
        for r in requetes(json.load(f)):
            print(
                f"{r['affirmations']:>3} {s(r['debut'], r['fin']):6.2f} {s(r['debut'], r['branches']):6.2f} "
                f"{s(r['branches'], r['debut_nli']):6.2f} {s(r['debut_nli'], r['fin_selfcheck']):6.2f} "
                f"{s(r['branches'], r['fin_selfcheck']):6.2f} {s(r['branches'], r['fin_rag']):6.2f} "
                f"{s(r['fusion'], r['fin']):5.2f}"
            )


if __name__ == "__main__":
    main(sys.argv[1])
