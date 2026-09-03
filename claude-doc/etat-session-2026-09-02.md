# État de session — 2 septembre 2026, fin de journée

Reprise après compactage : ce qui tourne, ce qui attend, ce qui a été décidé.

## Incident du premier lancement — corrigé

Le premier run tournait avec **`--judge-model qwen2.5:0.5b`** : `make/pipeline.mk`
imposait ce défaut, qui écrasait silencieusement le `llama3.1:8b` de `params.py`.
Or ce fichier documente l'exigence : « 7B minimum — en dessous, le juge valide
quasi systématiquement ». L'évaluation n'aurait rien mesuré.

Run arrêté après 17 questions, défaut corrigé dans `make/pipeline.mk`, relancé
avec `JUDGE_MODEL=llama3.1:8b` explicite. Les 158 réponses générées et les 17
vérifications Berlue sont conservées : elles ne dépendent pas du juge, et le
cache les réutilise.

**Leçon pour la suite : vérifier la ligne de commande effective**
(`ps -eo cmd | grep run_eval`) après chaque lancement. Les défauts du Makefile
priment sur ceux du code, et rien ne le signale.

## Ce qui tourne EN CE MOMENT

Une évaluation locale, lancée vers 21h45, **environ une heure** :

```bash
make evaluate_model_generated_all \
  DATASET=truthfulqa RATIO=0.8 MODEL_ID=llama3.2:3b JUDGE_MODEL=llama3.1:8b WARMUP=true
```

- 158 questions, mode **généré** (mode 2), rien en cache au départ
- journal : `…/scratchpad/eval_truthfulqa2.log`
- débit mesuré : **17 s par question** → ~45 min pour 158
- interruptible et reprenable — `make evaluate_model_coverage DATASET=truthfulqa RATIO=0.8 MODEL_ID=llama3.2:3b MODE=generated` dit ce qui manque

**À faire quand il aboutit :** lire la matrice et le temps réel, les rapporter,
puis attendre le feu vert avant HaluEval.

## Ce qui suit, une fois ce run validé

```bash
make evaluate_model_generated_all \
  DATASET=halueval RATIO=0.90 MODEL_ID=llama3.2:3b WARMUP=true
```

1000 questions. Au débit mesuré de 17 s/question : **~4 h 45**.

**Xavier a donné son accord** avant d'aller dormir : « je te laisse gérer la
génération locale, hésite pas à itérer si ça marche pas du premier coup ». Donc
enchaîner sans attendre, en vérifiant la ligne de commande effective.

## Tâche bonus, SI les deux évaluations aboutissent avant le matin

Passer les 25 questions de `claude-doc/questions-exemples.md` à l'API **locale**
(GCP est éteint), avec `debug: true`, analyser les traces et rédiger un rapport
sur ce qui pourrait être amélioré.

```bash
curl -s -X POST http://127.0.0.1:8000/predict -H "Content-Type: application/json" \
  -d '{"question":"…","llm":{"name":"llama3.2:3b","temperature":0.0},"debug":true}'
```

**À faire APRÈS les évaluations, jamais pendant** : l'API et le run se
disputeraient le GPU, et une saturation mémoire a déjà provoqué un
`CUDA out of memory` aujourd'hui.

L'API locale tourne sur le port 8000. Si elle est tombée :
`python -m uvicorn berlue.api.fast:app --host 127.0.0.1 --port 8000`

## Configuration décidée

```
génération des réponses   llama3.2:3b     MODEL_ID
échantillons SelfCheck    llama3.2:3b     OLLAMA_MODEL — le modèle qui a répondu,
                                          la méthode SelfCheckGPT l'exige
extraction                llama3.1:8b     EXTRACT_MODEL
RAG                       llama3.1:8b     RAG_MODEL
juge                      llama3.1:8b     JUDGE_MODEL
versions                  v2              PIPELINE / GENERATION / EVAL_VERSION
```

Que du llama, 3b en générateur et 8b partout ailleurs.

**Purge totale faite** avant le run : 6 593 lignes en local, 676 sur GCP
(Firestore + BigQuery). Motif : première version à peu près stable, donc premier
test valable. Rien à conserver des mesures antérieures.

## GCP

**Éteint** — les trois services Cloud Run supprimés, plus rien ne facture.
Recréation par `make cloudrun_deploy_all`, sans rebuild : les images restent
dans le dépôt.

## En attente d'une décision

**La description de la PR #99** décrit six commits alors qu'elle en porte quinze.
Question posée trois fois, jamais tranchée : la réécrire pour couvrir l'ensemble,
ou la laisser centrée sur les correctifs ?

**Le passage en v2 du Makefile n'est pas commité.** Il change le scope par défaut
pour toute l'équipe.

**Deux branches distantes fusionnées** traînent :
`feat-reorganize-gcp-setup-deploy-run-down-destroy` (#91) et
`feat_modif_score_fusion` (#95, branche d'un collègue — demander avant).

**La branche locale `fix-cloudrun-llm-deploy-sa`** n'a jamais eu de PR et porte
une ligne de `make/cloudrun.mk` absente de `main`. Correctif oublié, ou devenu
inutile ?

## En attente d'une information des collègues

Leurs **numéros de projet**, pour `make image_reader_grant CONSUMER_PROJECT=…`.
Ils les obtiennent par `make image_reader_request` chez eux. Les identifiants
connus : `<projet-du-collegue>` (Lionel), `<projet-du-collegue>`
(Mouhamad) — **les chiffres qu'ils contiennent ne sont PAS les numéros de
projet**, Google y ajoute un suffixe aléatoire.

Marche à suivre côté collègue : `docs/gcp/deployer-images-partagees.md`.

## Défauts connus, non corrigés VOLONTAIREMENT

Tous touchent au prompt d'extraction ou au RAG : les corriger invalide le cache
et toute comparaison en cours. **Ne pas y toucher pendant les runs.**

**L'extraction supprime les négations.** « Ryan Gosling n'a pas voyagé en
Afrique » devient « il a voyagé en Afrique ». Cause : la règle 1 du prompt ne
donne qu'un exemple affirmatif, et aucun des deux exemples complets n'a de
réponse négative. C'est le plus grave — il inverse le sens du verdict.

**L'extraction produit des affirmations qui se recouvrent.** Sur une réponse
d'une seule phrase, la règle 1 la consomme entièrement et la règle 2 en extrait
quand même un fragment. Le même fait est compté deux fois, et le coût double.

**`retrieve()` n'applique aucun seuil de distance.** Un extrait à 0,943 a été
cité comme preuve. Le test `xfail`
`test_verify_claim_ne_fabrique_pas_de_preuve_sur_une_affirmation_hors_corpus`
attend ce correctif — il doit redevenir vert sans qu'on affaiblisse l'assertion.

**Le champ `version` du greeting** est déduit du dernier segment du chemin :
`full-145k` déployé, mais `faiss` en local, ce qui ne veut rien dire.

## Ne PAS toucher

**Le dépôt Aletheia** (`/opt/wagon/src/aletheia`) : une autre session de Xavier y
travaille activement, branche `feat-bouton-debug`. Deux demandes d'interface m'y
ont été adressées par erreur aujourd'hui ; les deux fois, il a confirmé que
c'était pour l'autre session.

## Rappels de méthode

- Jamais de `git push` sans demander, sauf consigne explicite pour ce geste
- Messages de commit courts, le corps ne dit que le **pourquoi** non évident
- Attribution : `Co-Authored-By: Claude Opus 5` + ligne `Claude-Session`
- Un point à la fois, discuté puis résolu, dans l'ordre d'importance
- Les écrits de Claude vont dans `claude-doc/` ; `docs/` est pour l'équipe
