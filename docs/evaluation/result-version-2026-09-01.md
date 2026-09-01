# Résultats d'évaluation — 1ᵉʳ septembre 2026

Première série d'évaluations du **vrai** pipeline Berlue, en local et sur GCP.
Toutes les mesures GCP antérieures à cette date utilisaient le pipeline mocké
(cf. [`execution-benchmark.md`](execution-benchmark.md), ligne
`Berlue (mock) | 0,000 s`) : ce document est donc la première mesure du
comportement réel du pipeline sur l'infrastructure.

## Protocole

**Mode dataset** (`evaluate_model`, cf. [`modes.md`](modes.md)) : Berlue vérifie
les réponses du dataset, dont la vérité-terrain est connue — pas de LLM-juge, pas
de génération. C'est le mode qui mesure Berlue seul, la variable qu'on cherche à
améliorer.

| paramètre | valeur |
|---|---|
| dataset | `halueval` |
| corpus RAG | `full-145k` — 109 810 vecteurs, identique octet pour octet en local et sur GCS |
| `SELFCHECK_K` | 5 |
| parallélisme | **aucun** — `evaluate_model` est une boucle séquentielle, `--concurrency` n'existe qu'en mode généré |

Trois modèles interviennent, à ne pas confondre avec `MODEL_ID` qui n'est qu'une
**étiquette de scope** en mode dataset (aucune génération n'a lieu) :

| variable | rôle | appels par ligne |
|---|---|---|
| `BERLUE_OLLAMA_MODEL` | échantillons SelfCheck | **5** |
| `RAG_MODEL` | RAG inversé | **N affirmations** (~1,5) |
| `EXTRACT_MODEL` | extraction des affirmations | 1 |

**Métrique retenue : la séparation** — écart entre le taux de `contradicted` sur
les réponses fausses et sur les réponses vraies. La justesse brute est trompeuse
ici : les deux versions testées restent sous les 50 % qu'obtiendrait un
classifieur répondant toujours `contradicted`.

## Bruit de reproductibilité

Mesuré en rejouant **la même configuration, le même code et le même corpus** sur
les 100 mêmes lignes, en local puis sur GCP — seule l'infrastructure diffère :

| niveau | bruit |
|---|---|
| verdict individuel | **13 %** de bascules (87/100 identiques) |
| séparation (agrégée) | **±2 points** |

Origine : les échantillons SelfCheck sont tirés entre `SELFCHECK_TEMPERATURE_MIN`
(0.3) et `MAX` (1.0), sans seed, et ne sont pas mis en cache.

**Conséquences opérationnelles** : ne jamais comparer deux versions ligne à ligne ;
un écart de séparation inférieur à ~4-5 points n'est pas concluant sans répétition
ou seed fixé.

## Référence locale

Machine : RTX 5070 Ti Laptop (12 Go), Ollama local.

| scope | `ratio` | n | s/ligne | durée |
|---|---|---|---|---|
| pré-refonte de la fusion | 0.95 | 1000 | 2,149 | 35,8 min |
| `v2-sc1b-ext7b-rag7b` | 0.985 | 300 | 2,434 | 12,3 min |

Les jeux de test étant emboîtés (`split_train_test` fixe `random_state=0` et
sklearn prend le test en tête de permutation), la comparaison ci-dessous porte sur
les **300 mêmes lignes** :

| | pré-refonte | post-refonte |
|---|---|---|
| GT vrai — sup/und/con | 3 / 104 / 43 | 22 / 26 / **102** |
| GT faux — sup/und/con | 0 / 18 / 132 | **22** / 13 / 115 |
| justesse | 45,0 % | 45,7 % |
| **séparation** | **+59,3 pts** | **+8,7 pts** |

**La refonte de la fusion a fait chuter la capacité de discrimination de 59 à 9
points**, pour une justesse brute inchangée. Le pipeline contredit désormais 68 %
des réponses **vraies** (contre 28,7 % avant). Écart de 50 points contre un bruit
de 2 : sans ambiguïté.

Trois variables ont changé simultanément (logique de fusion, corpus FEVER réduit →
complet, modèles). L'attribution à la fusion est la plus probable au vu du
mécanisme, mais n'est pas isolée — un run de contrôle en config identique sur le
code pré-refonte trancherait.

## Résultats GCP

`berlue-llm` : GPU L4 (24 Go), 8 vCPU / 32 Gi, `OLLAMA_NUM_PARALLEL=4`, contexte
par défaut (4096). `berlue-eval` : 8 vCPU / 8 Gi, **sans GPU**.
`ratio=0.995` (100 lignes).

| # | échantillons | extraction + RAG | n | s/ligne | justesse | con/faux | con/vrai | **séparation** |
|---|---|---|---|---|---|---|---|---|
| 1 | `llama3.2:1b` | `qwen2.5:7b` | 100 | 7,96 | 46,0 % | 80,0 % | 70,0 % | **+10,0** |
| 2 | `llama3.2:1b` | `qwen2.5:14b` | 100 | 12,92 | 42,0 % | 74,0 % | 66,0 % | **+8,0** |
| 3 | `llama3.2:3b` | `qwen2.5:14b` | 97 | n/a | 50,5 % | 78,7 % | **54,0 %** | **+24,7** |

Matrices détaillées (supported / undecided / contradicted) :

```
run 1   GT vrai (50) :  6 /  9 / 35        GT faux (50) :  7 /  3 / 40
run 2   GT vrai (50) :  5 / 12 / 33        GT faux (50) :  4 /  9 / 37
run 3   GT vrai (50) : 12 / 11 / 27        GT faux (47) :  4 /  6 / 37
```

### Grossir le modèle RAG ne sert à rien

Runs 1 → 2 : seuls extraction et RAG changent (7B → 14B). La séparation passe de
10 à 8 points, **dans le bruit**, pour 1,6× le temps de calcul.

L'explication est dans le code : le RAG répond `unknown` dans **87 %** des cas
(observé sur 30 affirmations : 26 `unknown`, 2 `proven_true`, 1 `likely_true`,
1 `likely_false`). La garde `used_idx is None` de
[`retriever.py`](../../berlue/rag/retriever.py) réécrit les verdicts
`LIKELY_TRUE`/`LIKELY_FALSE`/`I_DONT_KNOW` en `NOT ENOUGH INFO` avant la fusion,
alors que le prompt **impose** `used_evidence_index: null` pour ces trois verdicts.
Un modèle plus capable produit de meilleurs jugements, que le code jette de la même
façon.

**La taille du modèle RAG est un levier mort tant que ce point n'est pas corrigé.**

### Le modèle d'échantillonnage SelfCheck est le levier dominant

Runs 2 → 3 : seul `BERLUE_OLLAMA_MODEL` change (1b → 3b). La séparation passe de
**+8 à +24,7 points**, soit **+16,7**, très au-dessus du bruit de ±2.

Le gain vient entièrement des fausses alertes : `contradicted` sur les réponses
vraies tombe de **66 % à 54 %**. Un modèle d'échantillonnage plus capable produit
des échantillons qui s'accordent davantage avec une réponse vraie.

C'est la confirmation expérimentale du diagnostic sur la fusion : depuis la
refonte, la cohérence SelfCheck pèse 50 % du score, **c'est donc elle qui pilote le
verdict**, pas le RAG. La variable la plus déterminante était celle qu'on avait
choisie la plus petite.

Réserve : run 3 est à n=97 et non 100 (voir incidents), la comparaison n'est donc
pas parfaitement appariée. Et +24,7 reste loin des +59,3 du code pré-refonte.

### Performance : GCP est 3,3× plus lent que le local

7,96 s/ligne contre 2,434 en configuration identique. Trois contributions, non
démêlées ici :

- `berlue-eval` **n'a pas de GPU** : SelfCheckNLI (DeBERTa-large, 435 M
  paramètres, 5 passes par affirmation), l'embedding et la recherche FAISS
  exhaustive tournent sur CPU, alors qu'ils bénéficiaient du GPU en local ;
- latence réseau entre les deux services Cloud Run, à chaque appel LLM ;
- L4 contre RTX 5070 Ti (~1,9× d'après [`execution-benchmark.md`](execution-benchmark.md)).

## Incidents

Aucun run de 100 lignes n'est allé au bout sans interruption. Le cache Firestore a
rendu chaque reprise incrémentale, sans perte de travail.

| run | symptôme | cause |
|---|---|---|
| 2 | `model runner has unexpectedly stopped` | `LLM_MEMORY=16Gi` avec `qwen2.5:14b` qui occupe 12 Go — erreur de configuration, corrigée en 32 Gi |
| 2 | `401 Unauthorized` sur Firestore après 90 lignes | jeton expiré, voir ci-dessous |
| 3 | `TimeoutError` Ollama, bloqué à 97/100 | `num_predict` jamais fixé, voir ci-dessous |

### Jeton Firestore

`_FirestoreRest._headers()` ([`gcp_result_store.py`](../../berlue/evaluation/gcp_result_store.py))
renouvelle son jeton au bout de 50 minutes, en supposant une durée de vie de 60.
Or sur Cloud Run le serveur de métadonnées sert un jeton **mutualisé et déjà
partiellement consommé** : un `refresh()` peut rendre un jeton auquel il ne reste
que quelques minutes. Aucun retry sur 401 — une écriture qui échoue interrompt tout
l'appel.

Correctif : lire `credentials.expiry` renvoyé par google-auth plutôt qu'une fenêtre
codée en dur, et retenter une fois sur 401 après rafraîchissement forcé.
Contournement utilisé : forcer une nouvelle révision Cloud Run pour repartir sur un
conteneur neuf.

### `num_predict` absent

Aucun appel du pipeline ne borne la longueur générée, alors que la docstring de
`OllamaClient.generate` ([`client.py`](../../berlue/llm/client.py)) documente
précisément le risque : un modèle qui ignore la consigne de longueur sature
`n_ctx_slot` puis enchaîne les *context shifts*, et un seul appel dépasse
largement le timeout client de 120 s. Le passage des échantillons de `1b` à `3b`
a suffi à déclencher ce que le 1B ne déclenchait pas, sur 3 lignes de façon
reproductible.

Ce défaut empêche de **terminer** un run : il n'est pas un simple point de
robustesse.

### Piège vérifié : contexte Ollama

Ne pas déployer `berlue-llm` avec `LLM_CONTEXT_LENGTH=1024`, valeur pourtant
utilisée dans tout `execution-benchmark.md` : le prompt RAG complet fait
**~1218 tokens** (few-shot à 5 exemples + 3 extraits en JSON) et serait
silencieusement tronqué. Le benchmark pouvait s'en contenter parce qu'il ne
mesurait que la génération et le juge, Berlue étant mocké.

## Conclusions

1. **La refonte de la fusion est une régression** : −50 points de séparation,
   très au-delà du bruit. À traiter en priorité.
2. **La pondération de la cohérence SelfCheck à 50 % est le mécanisme en cause**,
   confirmé expérimentalement par l'effet du modèle d'échantillonnage (+16,7 points
   à lui seul).
3. **Grossir extraction et RAG est inutile** tant que la garde `used_idx is None`
   écrase les verdicts du RAG.
4. **`num_predict` est bloquant**, pas cosmétique.
5. Le mode dataset étant séquentiel, la parallélisation de `evaluate_model` reste
   le principal levier de temps disponible (gain observé en mode généré : ~3,8×).

## Reproduire

Référence locale :

```bash
export BERLUE_OLLAMA_MODEL=llama3.2:3b   # levier dominant, cf. run 3
export EXTRACT_MODEL=qwen2.5:7b
export RAG_MODEL=qwen2.5:7b
make evaluate_model_all DATASET=halueval RATIO=0.985 \
  MODEL_ID=llama3.2:3b PIPELINE_VERSION=<config-et-version>
```

`PIPELINE_VERSION` est une clé de cache : le changer à chaque version, et y encoder
la configuration des modèles — `MODEL_ID` ne décrit rien en mode dataset.
Conserver `RATIO=0.985` pour rester comparable (le cache Berlue est indexé sur
`ratio`, changer de palier recalcule tout).
