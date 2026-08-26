# Structure du projet

Organisation interne du répertoire `berlue/` (le package Python), module par
module.

## `berlue/params.py`
Configuration centrale — variables lues depuis `.env` (`BERLUE_*`, `GCP_*`...)
et constantes fixes.

## `berlue/core/`
Contrat interne entre les modules du pipeline — distinct des schémas HTTP.
- **`schemas.py`** : définit les structures de données échangées entre les
  modules du pipeline (affirmation extraite, preuve, verdicts intermédiaires et
  final).

## `berlue/api/`
API HTTP (FastAPI).
- **`fast.py`** : expose l'API — endpoints techniques et endpoints métier
  (liste des LLM, prédiction, évaluation). Charge le pipeline mock ou réel
  selon la config.
- **`schemas.py`** : définit le format des requêtes/réponses HTTP de l'API.

## `berlue/llm/`
- **`client.py`** : encapsule la communication avec le LLM local (génération
  d'une réponse, échantillonnage de plusieurs réponses).

## `berlue/rag/`
RAG inversé sur le corpus FEVER (vérifie une affirmation en cherchant des
preuves).
- **`indexer.py`** : construit l'index vectoriel du corpus FEVER.
- **`retriever.py`** : charge cet index et vérifie une affirmation par
  recherche de preuves.

## `berlue/selfcheck/`
SelfCheckGPT (détection de divergence, zero-resource).
- **`sampler.py`** : génère plusieurs réponses indépendantes à une même
  question, à des températures variées.
- **`scorer.py`** : mesure la divergence d'une affirmation par rapport à ces
  échantillons.

## `berlue/fusion.py`
Combine le verdict du RAG et le score SelfCheckGPT en un verdict final.

## `berlue/nli_baseline/`
Classifieur NLI léger (TF-IDF + régression logistique) — baseline de
comparaison pour l'évaluation offline, sans RAG (prédit directement depuis le
texte question+réponse).
- **`train.py`** : entraîne ce classifieur sur une partie des jeux de données
  labellisés.
- **`predict.py`** : charge le modèle entraîné et prédit un verdict.

## `berlue/evaluation/`
Évaluation offline du pipeline Berlue complet vs baseline NLI.
- **`data.py`** : charge les jeux de données labellisés et les sépare en
  train/test.
- **`metrics.py`** : construit les matrices de confusion à partir des verdicts
  prédits et des labels vérité-terrain.
- **`run_eval.py`** : point d'entrée pour lancer l'évaluation (baseline seule
  par défaut, ou baseline + pipeline complet une fois ce dernier disponible).

## `berlue/mocks/`
- **`mock_pipeline.py`** : simule le pipeline complet pour développer le front
  sans dépendre du vrai modèle.

## `berlue/ml_logic/`, `berlue/interface/`
Squelette issu du template MLOps de départ (BigQuery, MLflow, Prefect) — à
réutiliser quand le projet en aura besoin : suivi des expériences/métriques
d'évaluation via MLflow, stockage BigQuery, ré-entraînement périodique
orchestré via Prefect (`interface/workflow.py`).
