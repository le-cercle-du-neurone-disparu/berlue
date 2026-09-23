# Latence de `/predict` sur GCP

Temps de réponse de l'API tel que le voit Aletheia : une question posée,
une réponse vérifiée. Mesures du **23 septembre 2026**, sur l'architecture
déployée par `make cloudrun_deploy cloudrun_llm_deploy` (cf.
[`infra-gpu.md`](infra-gpu.md)).

## En bref

| Chemin | Latence |
|---|---|
| Question déjà en cache | **0,08 s** (médiane, 25 questions) |
| Question neuve, pipeline parallèle | **2,62 s** en moyenne, de 1,2 à 5,1 s |
| Question neuve, pipeline séquentiel | 4,56 s en moyenne, de 1,7 à 10,7 s |
| Premier appel après un démarrage de révision | 10 à 16 s — chargement, pas pipeline |

La durée d'une question neuve dépend surtout du **nombre d'affirmations**
extraites de la réponse, donc de la longueur de ce que répond le LLM :
1 à 3 affirmations tiennent en 1,2 à 2,5 s, 8 à 13 affirmations montent à
4-5 s.

## Architecture mesurée

| Service | Région | Matériel | Rôle |
|---|---|---|---|
| `berlue-api-test` | `europe-west4` | GPU **L4** + 8 vCPU / 32 Gi | API, SelfCheck NLI (DeBERTa) et embeddings sur le GPU |
| `berlue-llm` | `europe-west4` | GPU **RTX PRO 6000** (96 Go) + 20 vCPU / 80 Gi | Ollama : génération, extraction, échantillons, RAG |
| Firestore `(default)` | `europe-west4` | — | cache de `/predict` |
| Buckets `*-eu` | multi-région `EU` | — | code, index FAISS, poids HuggingFace |

Modèles : génération et échantillons SelfCheck `llama3.2:3b`, extraction et
RAG `llama3.1:8b`, `SELFCHECK_K=5`, corpus `full-145k`. Les deux modèles
Ollama sont préchargés (`WARM_MODELS="llama3.2:3b llama3.1:8b"`).

Pourquoi le GPU sur l'API : SelfCheck fait passer DeBERTa-large K fois par
affirmation. Sur CPU, c'est les deux tiers du temps d'une requête ; sur L4,
il passe sous la seconde pour une réponse moyenne. Le GPU de `berlue-llm`
n'est pas accessible depuis le conteneur de l'API (joignable seulement en
HTTP, via Ollama), d'où une carte dédiée.

## Pipeline séquentiel contre parallèle

Mêmes services, même instance, seul le code change (`CODE_VERSION`
différente dans le bucket de code, cf. [`code-en-bucket.md`](code-en-bucket.md)).
Le parallèle lance les branches RAG et SelfCheck en même temps, et répartit
chacune sur son pool de threads (`BERLUE_RAG_WORKERS`,
`BERLUE_SELFCHECK_SAMPLE_WORKERS`, `BERLUE_SELFCHECK_SCORE_WORKERS`, cf.
`berlue/params.py`).

25 questions de [`questions-exemples.md`](../../claude-doc/questions-exemples.md),
hors cache :

| | Séquentiel | Parallèle | Gain |
|---|---|---|---|
| Moyenne par question | 4,56 s | **2,62 s** | 1,74× |
| Médiane | 4,06 s | 2,37 s | |
| Par affirmation | 1,18 s | 0,70 s | |
| Question Beatles (4-5 affirmations), 3 appels | 4,6 – 4,8 s | **2,8 – 3,4 s** | |
| Question du Nil (11-13 affirmations) | 10,7 s | 4,5 s | 2,4× |

Le gain croît avec le nombre d'affirmations : à 1 ou 2 affirmations, la
branche RAG n'a presque rien à répartir.

Pour situer, avec SelfCheck **sur CPU** (8 vCPU), la question Beatles
prenait 28,5 s en séquentiel et 7,9 à 10,0 s en parallèle
(`claude-doc/comparatif-perf-2026-09-04.md`, mesures du 4 septembre : même
`berlue-llm`, API sans GPU). Le GPU de l'API est le premier levier, le parallélisme
le second.

## Décomposition d'une requête

Lue dans l'horodatage des logs DEBUG de l'API (`scripts/predict_stages.py`),
pipeline parallèle, `BERLUE_SELFCHECK_SCORE_WORKERS=2` (défaut). Temps côté
serveur, en secondes :

| Question | Aff. | Total | Avant les branches | Échantillons | NLI | Branche SelfCheck | Branche RAG | Fusion + cache |
|---|---|---|---|---|---|---|---|---|
| Beatles | 5 | 2,61 | 0,67 | 0,50 | 1,21 | 1,71 | **1,86** | 0,08 |
| Lune rouge | 5 | 3,66 | 0,81 | 1,53 | 1,23 | **2,76** | 1,96 | 0,09 |
| Nil | 11 | 4,57 | 0,84 | 0,95 | 2,73 | **3,68** | 2,34 | 0,05 |

- **Avant les branches** (0,6 – 0,9 s) : génération de la réponse
  (`llama3.2:3b`), extraction des affirmations (`llama3.1:8b`), jeton
  d'identité vers `berlue-llm`.
- **Les deux branches tournent en même temps** ; la plus longue fixe la
  durée (en gras). Sur les réponses courtes, c'est le RAG ; dès que la
  réponse s'allonge, c'est SelfCheck.
- **NLI** : ~0,25 s par affirmation sur 2 threads, linéaire — c'est le poste
  qui grossit le plus avec le nombre d'affirmations.
- **Échantillons** : les 5 tirages partent ensemble ; leur durée dépend de la
  longueur de ce que génère le 3B (0,3 s sur une question fermée, 1,5 s sur
  une question en « pourquoi »).
- **RAG** : 0,5 à 2,1 s par appel `llama3.1:8b` (prompt de ~2000 tokens), 4
  appels à la fois.
- **Fusion et écriture du cache Firestore** : < 0,1 s.

### Plus de threads NLI n'aide pas

Même mesure avec `BERLUE_SELFCHECK_SCORE_WORKERS=4` :

| Question | Aff. | NLI à 2 threads | NLI à 4 threads |
|---|---|---|---|
| Beatles / lune rouge | 5 | 1,21 – 1,23 s | 1,54 – 1,55 s |
| Nil | 11 → 12 | 2,73 s | 3,96 s |

Les passages DeBERTa se disputent le même GPU : au-delà de 2, ils
s'attendent au lieu de s'additionner. **Garder le défaut de 2.** Une mesure
par configuration — le sens de l'écart est net, son ampleur est à confirmer.

## Chemin en cache

25 questions déjà calculées, sans `ignore_cache` : 25/25 servies depuis
Firestore, **médiane 0,078 s**, de 0,06 à 0,19 s, depuis un poste en France.
Firestore est dans la même région que l'API : aucune lecture ne traverse de
région.

## Démarrages

| Opération | Durée |
|---|---|
| `make gcp_up WARM_MODELS="llama3.2:3b llama3.1:8b"` (les deux modèles tirés et chargés) | 5 min 35 |
| Nouvelle révision de l'API (`code_reload`, changement de variable) | ~2 min |
| Premier `/predict` d'une révision fraîche | 9,7 – 15,9 s |

Mesurer toujours à partir du second appel.

## Leviers restants

| Levier | Effet attendu | État |
|---|---|---|
| Passer les affirmations au NLI en un seul lot plutôt qu'en threads | réduire le poste NLI sur les réponses longues | non mesuré |
| `SELFCHECK_K` de 5 à 3 | −40 % de passages NLI et d'échantillons | change le signal mesuré : incomparable avec les évaluations existantes |
| Borner la longueur des échantillons | réduit la variance de la branche SelfCheck | non mesuré |
| Service `berlue-selfcheck` séparé | aucun gain de latence ; les réponses en cache ne paient plus un GPU | architecture cible, cf. `claude-doc/comparatif-perf-2026-09-04.md` §7 |

## Coût

Les deux GPU allumés : ~7 à 8 $/h (estimation, pas une facture — L4 ~0,67
$/h, RTX PRO 6000 ~5,7 à 7,1 $/h). `make gcp_down` supprime les deux services
et arrête toute facturation.

## Reproduire

```bash
# depuis le repo berlue
make cloudrun_llm_deploy
make cloudrun_deploy
make gcp_up WARM_MODELS="llama3.2:3b llama3.1:8b"
make cloudrun_url                         # URL de berlue-api-test
python scripts/predict_latency_bench.py <url> bench.json

# décomposition par étape : logs DEBUG le temps de la mesure
gcloud run services update berlue-api-test --region europe-west4 \
  --update-env-vars=BERLUE_LOG_LEVEL=DEBUG
# ... quelques appels hors cache, puis :
gcloud logging read 'resource.type="cloud_run_revision" AND
  resource.labels.service_name="berlue-api-test" AND timestamp>="<début>"' \
  --order asc --limit 3000 --format=json > logs.json
python scripts/predict_stages.py logs.json

make gcp_down
```

Séquentiel contre parallèle sans rebuild : publier chaque version sous sa
propre `CODE_VERSION` (`make code_push CODE_VERSION=seq`, depuis chaque
branche), puis basculer avec `make code_reload CODE_VERSION=<version>`.
