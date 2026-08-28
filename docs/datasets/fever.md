# Dataset FEVER

Corpus de vérification de faits (Fact Extraction and VERification, Univ.
Cambridge) — base de preuves du RAG inversé (`berlue/rag/`). Partie
opérationnelle (télécharger, indexer, tester) : [`rag.md`](../pipeline/rag.md).

## Ce que le projet en utilise

Chaque exemple FEVER associe une affirmation (`claim`) à un label
(`SUPPORTS` / `REFUTES` / `NOT ENOUGH INFO`) et une preuve Wikipedia
(`evidence`). Le RAG inversé n'indexe que les exemples `SUPPORTS`/`REFUTES`
disposant d'une preuve : un exemple `NOT ENOUGH INFO` n'a rien à embed pour
la recherche par similarité.

Le label FEVER (une string) est reconverti en `Verdict` — l'enum interne du
projet (`berlue.core.schemas`) — au moment de citer un verdict RAG.
`Verdict.NOT_ENOUGH_INFO` reste possible en sortie de `verify_claim()` : ce
n'est pas un label copié depuis FEVER, c'est le verdict de repli quand
aucune preuve indexée n'est assez proche de l'affirmation testée.

## Pour aller plus loin

Exploration complète du dataset (structure détaillée, distribution des
labels, statistiques, prétraitement, expérimentation baseline) :
[`fever_explication.md`](../../historique-etude-data/fever_explication.md)
et son notebook jumeau
[`fever_explication.ipynb`](../../historique-etude-data/fever_explication.ipynb)
— matériel d'étude, pas la doc de référence de l'usage dans le repo.
