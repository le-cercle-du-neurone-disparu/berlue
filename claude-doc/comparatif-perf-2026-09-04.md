# Comparatif de performance — v2 (03/09) contre parallélisation (04/09)

**Toutes les mesures de ce document sont prises à chaud** — second appel au
minimum, jamais le premier après un déploiement. Les durées observées sur un
démarrage à froid mesurent le chargement des modèles, pas le pipeline, et n'ont
pas leur place dans un comparatif : elles sont écartées.

Les mesures sont datées et reproductibles, et classées par **solidité** : une comparaison A/B toutes choses égales par ailleurs ne vaut pas
une moyenne comparée à un point isolé, et le document le dit à chaque fois.

---

## 1. La mesure la plus solide — A/B sur la même question

Même instance Cloud Run, même GPU, même question, **quatre minutes d'écart**.
Seul le code change (séquentiel → parallèle).

Question : *« Where were The Beatles formed, and in what year? »* — 5 affirmations.

| Version | Durée | Gain cumulé |
|---|---|---|
| Séquentiel, SelfCheck sur CPU (code du 02/09) | **28,5 s** | référence |
| Parallèle, SelfCheck sur CPU | **7,9 – 10,0 s** | **2,85 – 3,6×** |
| **Parallèle, SelfCheck sur GPU (L4)** | **2,6 – 3,5 s** | **~9×** |

Tous les facteurs sont contrôlés : même image, même code, même service Ollama en
face, mêmes buckets. Seuls changent le code (séquentiel → parallèle) puis le
matériel de SelfCheck (CPU → L4).

### Le second bond : SelfCheck sur GPU

Après parallélisation, SelfCheck restait **76 % du chemin critique** — mesuré
dans les logs d'une requête à 7,9 s :

```
06:49:46/47   départ
06:49:48      les 5 affirmations RAG traitées, toutes à la même seconde (parallèle)
   ←────────── 6 secondes : SelfCheck termine ──────────→
06:49:54      POST /predict 200 OK
```

La branche RAG finit en 1-2 s **puis attend**. Attacher un L4 au service d'API
fait tomber les 25 passages DeBERTa sous la seconde.

**Aucun code ni image n'a été nécessaire.** `torch` arrive transitivement via
`sentence-transformers`/`selfcheckgpt`, et la roue PyPI par défaut est compilée
pour CUDA — ce que confirmait déjà la taille des dépendances (~6,5 Go ; un torch
CPU-only pèse ~200 Mo). `scorer.py` bascule seul :

```python
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
```

Log de confirmation au démarrage : `SelfCheck-NLI initialized to device cuda`.

⚠️ Chaque conteneur ne voit **que son propre GPU**. Le Blackwell de `berlue-llm`
est inaccessible depuis le process de l'API — il n'est joignable qu'en HTTP via
Ollama. D'où le L4 dédié à DeBERTa.

### Décomposition du séquentiel, relevée dans les logs

```
06:23:08   Cache ignoré — le pipeline démarre
   ←──────────── 23 secondes ────────────→
06:23:31   RAG affirmation 1   (0,45 s)
06:23:32   RAG affirmation 2   (0,38 s)
06:23:34   RAG affirmation 3   (0,54 s)
06:23:35   RAG affirmation 4   (0,63 s)
06:23:36   RAG affirmation 5   (0,64 s)
06:23:37   POST /predict 200 OK
```

| Étage | Durée | Part | Où |
|---|---|---|---|
| Génération + extraction + 5 échantillons (7 appels) | ~4 s | 14 % | GPU |
| **SelfCheck — 25 passages DeBERTa** | **~19 s** | **67 %** | **CPU** |
| RAG — 5 appels **en série** | ~6 s | 19 % | GPU |
| **Total** | **28,5 s** | | |

**Le GPU ne représente que 10 des 28,5 secondes.** Les deux tiers sont dans
SelfCheck, sur CPU. C'est ce que la parallélisation attaque :

- les 6 s du RAG **se fondent** dans les 19 s de SelfCheck (branches concurrentes) ;
- les 5 échantillons partent **ensemble** (~3 s → ~0,6 s) ;
- les 25 passages NLI **se répartissent** sur les 8 cœurs.

---

## 2. Effet du nombre d'affirmations

Mesuré à chaud, séquentiel, 8 vCPU :

| Affirmations | Durée |
|---|---|
| 2 | 13,3 s |
| 5 | 28,5 s |

Régression sur ces deux points : **~5,1 s par affirmation + 3,2 s de coût fixe**.
Le coût est donc dominé par le nombre d'affirmations extraites, lui-même dicté
par la longueur de la réponse générée.

⚠️ Deux points ne font pas une droite — à considérer comme un ordre de grandeur.

---

## 3. Comparaison avec hier — indicative, pas rigoureuse

| | Hier (v2) | Aujourd'hui |
|---|---|---|
| GPU | L4 24 Gio, `europe-west1` | **RTX PRO 6000 Blackwell 95 Gio**, `europe-west4` |
| CPU de l'API | 2 vCPU | **8 vCPU** (plafond Cloud Run) |
| Code | séquentiel | **parallèle** |
| Buckets | `west1`, même région | `EU` multi-région |
| Durée | **17,3 s/question**, moyenne sur 25 questions (3,68 affirmations en moyenne) | **10,0 s** sur une question à **5 affirmations** |

**Ce n'est pas une comparaison stricte** : une moyenne sur 25 questions
hétérogènes face à un point unique, et sur des densités d'affirmations
différentes. Ce qu'on peut dire honnêtement : **aujourd'hui traite plus de
travail (5 affirmations contre 3,68) en moins de temps (10 s contre 17,3 s)**.

Autres références v2, pour situer :

| Campagne | Durée par question |
|---|---|
| TruthfulQA, mode généré, 158 questions | 17,4 s |
| HaluEval, mode généré, 1000 questions | 12,4 s |
| 25 questions d'exemple via l'API | 17,3 s |

---

## 4. Le même refacto, mesuré en local la nuit précédente

Sur le poste de dev (RTX 5070 Ti Laptop 12 Gio), A/B séquentiel contre parallèle :

| Banc | Séquentiel | Parallèle | Gain |
|---|---|---|---|
| 9 questions via `/predict` | 34,2 s/q | 22,5 s/q | **1,52×** |
| 40 questions d'éval TruthfulQA | 11,17 s/q | 7,56 s/q | **1,48×** |

**Le gain local (1,48×) est très inférieur au gain sur GCP (2,85×)**, et c'est
explicable : sur les 12 Gio du portable, les deux modèles Ollama s'évinçaient
mutuellement et chaque appel concurrent était ~2× plus lent faute de VRAM. Avec
95 Gio et 8 cœurs, la parallélisation a la place de s'exprimer.

Détail par question sur le banc `/predict` local — **le gain suit le nombre
d'affirmations** :

| Affirmations | Séquentiel | Parallèle | Gain |
|---|---|---|---|
| 8 | 46,7 s | 20,2 s | **2,31×** |
| 5 | 39,0 s | 18,0 s | **2,17×** |
| 5 | 45,1 s | 22,5 s | 2,00× |
| 6 | 42,6 s | 30,2 s | 1,41× |
| 3 | 31,1 s | 21,5 s | 1,45× |
| 3 | 29,3 s | 22,7 s | 1,29× |
| 3 | 27,1 s | 21,1 s | 1,28× |
| 2 | 23,8 s | 23,4 s | 1,02× |
| 2 | 22,9 s | 22,8 s | 1,00× |

**À 2 affirmations, aucun gain** : la branche RAG n'a rien à répartir. **À 5-8
affirmations, le débit double.**

---

## 5. Démarrage à froid — hors comparatif

Le rechargement de DeBERTa (1,6 Go) et des embeddings à chaque nouvelle révision
est un coût de **déploiement**, pas de traitement d'une question. Il ne figure
dans aucun chiffre ci-dessus : **toutes les mesures de ce document sont prises à
chaud**, sur un second appel au minimum.

| Source des modèles | Durée de mise en service d'une révision |
|---|---|
| Buckets `europe-west1`, lus depuis `west4` | ~6 min |
| **Buckets `EU` multi-région** | **1 min 31** |

Le passage en `EU` l'a divisé par 4. `max-instances=1` en protège ensuite :
avec plusieurs instances autorisées, une requête concurrente peut en démarrer
une froide et payer ce chargement ; une instance unique fait patienter à la
place.

## 6. Détail des appels GPU (RTX PRO 6000)

Relevés dans les logs Ollama pendant une requête complète :

```
Préchauffage (prompts courts) :  230 – 467 ms
Appels RAG (~2000 tokens)     :  380 – 640 ms
Débit brut llama3.1:8b        :  ~90 tok/s (mesuré en local sur RTX 5070 Ti)
```

VRAM occupée : **14 Gio sur 95** (`llama3.1:8b` 8,5 + `llama3.2:3b` 5,5).

Sur le L4 de 24 Gio, ces deux modèles saturaient déjà la carte — c'est ce qui
provoquait les évictions mutuelles observées en local.

---

## 7. Ce qui reste comme levier

Le poste dominant est **SelfCheck sur CPU (67 % du temps séquentiel)**. Trois
leviers, par ordre de coût :

| Levier | Effet | État |
|---|---|---|
| ✅ **Parallélisation** | 2,85× | fait, déployé |
| ✅ **SelfCheck sur GPU (L4)** | ~2,5× de plus | fait, déployé |
| ❌ Plus de cœurs | — | impossible, Cloud Run plafonne à **8 vCPU** hors GPU |
| Baisser `SELFCHECK_K` (5 → 3) | −40 % du travail NLI | change le signal mesuré, incomparable avec la v2 |
| **Service `berlue-selfcheck` séparé** | pas de gain de latence | **gain d'architecture, à faire** |

### Pourquoi le service séparé reste à faire

Le GPU est aujourd'hui attaché à **l'API entière**. Conséquences :

- chaque instance d'API embarque sa propre carte — 3 instances = 3 GPU ;
- les requêtes servies par le cache (~0,3 s) paient un GPU inutilisé, tout
  comme `/`, `/llms` et `/evaluated-models`.

L'architecture cible sépare les deux, comme `berlue-llm` l'est déjà :

```
berlue-api          CPU seul, léger, scalable horizontalement
   ├── HTTP ──> berlue-llm         RTX PRO 6000   génération, extraction, RAG
   └── HTTP ──> berlue-selfcheck   L4             DeBERTa
```

**Ni nouvelle image ni nouvelle branche** : `BERLUE_APP_MODULE` bascule déjà
entre `berlue.api.fast:app` et `berlue.api.eval_service:app` sur la même image ;
un `berlue.api.selfcheck_service:app` s'y insère naturellement.

⚠️ Prévoir **un seul appel HTTP par question**, pas un par passage NLI :
`SelfCheckNLI.predict(sentences, sampled_passages)` accepte déjà des listes.
Sinon les allers-retours réseau mangeraient le gain.
