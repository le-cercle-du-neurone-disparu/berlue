"""Latence de /predict hors cache, mesurée côté client comme Aletheia l'appelle.

Envoie les questions de `claude-doc/questions-exemples.md` avec
`ignore_cache=true`, précédées d'un appel de chauffe écarté des moyennes (le
premier appel après une révision mesure le chargement, pas le pipeline), puis
trois fois la question Beatles, point de comparaison de
`docs/gcp/latence-predict.md`.

    python scripts/predict_latency_bench.py <api_url> <sortie.json>
"""

import json
import re
import sys
import time
from pathlib import Path

import requests

QUESTIONS_FILE = Path(__file__).resolve().parent.parent / "claude-doc" / "questions-exemples.md"
BEATLES = "Where were The Beatles formed, and in what year?"
# Même charge que la requête d'Aletheia : modèle de génération par défaut, température 0.
LLM = {"name": "llama3.2:3b", "temperature": 0.0}


def questions():
    # `**1. Question ?**` (parties A et C) ou `**11.** *(ligne 0)* **Question ?**` (partie B)
    motif = r"^\*\*(\d+)\.(?:\*\* \*\([^)]*\)\* \*\*| )(.+?)\*\*\s*$"
    return [(int(m.group(1)), m.group(2).strip()) for m in re.finditer(motif, QUESTIONS_FILE.read_text(), re.M)]


def appel(api, question):
    payload = {"question": question, "llm": LLM, "ignore_cache": True}
    debut = time.perf_counter()
    reponse = requests.post(f"{api}/predict", json=payload, timeout=600)
    duree = time.perf_counter() - debut
    reponse.raise_for_status()
    return duree, len(reponse.json().get("claims", []))


def main(api, sortie):
    resultats = {"api": api, "chauffe": None, "beatles": [], "questions": []}
    duree, n = appel(api, BEATLES)
    resultats["chauffe"] = {"s": duree, "affirmations": n}
    print(f"chauffe : {duree:.2f} s ({n} aff.) — écartée", flush=True)
    for _ in range(3):
        duree, n = appel(api, BEATLES)
        resultats["beatles"].append({"s": duree, "affirmations": n})
        print(f"Beatles : {duree:.2f} s ({n} aff.)", flush=True)
    for num, question in questions():
        duree, n = appel(api, question)
        resultats["questions"].append({"num": num, "question": question, "s": duree, "affirmations": n})
        print(f"#{num:2d} {duree:6.2f} s  {n:2d} aff.  {question[:60]}", flush=True)
        sortie.write_text(json.dumps(resultats, indent=2, ensure_ascii=False))

    total_s = sum(r["s"] for r in resultats["questions"])
    total_aff = sum(r["affirmations"] for r in resultats["questions"])
    nb = len(resultats["questions"])
    print(
        f"moyenne {total_s / nb:.2f} s/question, {total_aff / nb:.2f} aff./question, "
        f"{total_s / max(total_aff, 1):.2f} s/affirmation sur {nb} questions"
    )


if __name__ == "__main__":
    main(sys.argv[1].rstrip("/"), Path(sys.argv[2]))
