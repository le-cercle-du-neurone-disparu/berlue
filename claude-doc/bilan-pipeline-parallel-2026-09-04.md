# Bilan — parallélisation du pipeline HurluBerlu

**Branche** `feat-pipeline-parallel` · 2 commits (`ceba065`, `8e7d1f3`) · non poussée
**État** : terminé, 296 tests au vert, lint et format clean, vérifié en local de bout en bout.

---

## Ce qui a été demandé, ce qui a été fait

| Demande | État |
|---|---|
| Branche `feat-pipeline-parallel` | ✅ créée, 2 commits |
| RAG et SelfCheck dans deux threads distincts | ✅ |
| Dans SelfCheck, les appels dans des threads distincts | ✅ sur les **deux** étages (K échantillons, puis scoring NLI par affirmation) |
| Gros refacto de la structure séquentielle | ✅ `PipelineResult` figé, assemblé en une fois |
| Tourner en local avec des 0.5b partout | ✅ `qwen2.5:0.5b` en génération, extraction et RAG |

Un `claude-doc/plan-parallelisation-pipeline.md` existait déjà. **Je m'en suis
écarté sur deux points**, avec ton accord en cours de route (« le gros refacto
est acceptable ») :

1. Le plan gardait `PipelineResult` mutable et partagé entre les deux branches,
   au motif qu'elles écrivent des attributs disjoints. J'ai figé la dataclass et
   assemblé le résultat en une seule construction. Le raisonnement du plan était
   correct mais fragile : il tient uniquement tant que personne n'ajoute une
   écriture croisée, et rien dans le type ne l'empêchait.
2. Le plan mettait la parallélisation **par affirmation** hors scope (RAG et
   scoring NLI restaient des boucles). Je l'ai faite : sans elle, la « branche
   RAG » reste une boucle série et le gain plafonne très vite.

---

## Le vrai obstacle : trois états partagés, pas un

Le plan en identifiait un. Il y en avait trois, et **le plus dangereux n'était
pas dans `PipelineResult`** :

### 1. `OllamaClient.derniere_generation` — le piège

```python
# AVANT, dans OllamaClient.__init__ :
self.derniere_generation: dict = {}   # écrit par generate(), lu après coup
# et son commentaire :
#   « Le pipeline étant séquentiel, il n'y a pas d'entrelacement à craindre. »
```

`retriever.verify_claim` lisait cet attribut **après** son appel à `generate()`
pour construire sa trace. Dès que deux vérifications tournent en parallèle sur
le même client, la seconde écrase les métadonnées de la première : chaque trace
avait une chance sur deux de porter le modèle, la durée et le nombre de tokens
**d'une autre affirmation**.

À noter : `run_eval.py` appelle déjà le pipeline dans un `ThreadPoolExecutor`, et
`BerluePipeline` partage un seul client RAG entre toutes les questions — **le bug
était donc déjà atteignable aujourd'hui** dès `concurrency > 1`, avant tout
refacto. Il ne corrompait que les traces de debug, pas les verdicts.

**Corrigé** : `generate_detail()` rend un `Generation` (texte + métadonnées) ;
`generate()` reste un raccourci sur `.text`. Plus aucun état conservé sur le
client entre deux appels. Test dédié :
`test_les_metadonnees_de_generation_ne_se_croisent_pas_entre_threads`.

### 2. `PipelineResult` rempli par mutations successives

C'est ce que tu avais signalé. Chaque étape recevait l'objet, lui ajoutait un
attribut, le renvoyait. Désormais **figé** (`@dataclass(frozen=True)`), construit
une seule fois quand les deux branches ont fini. `do_fusion` rend un nouvel objet
via `dataclasses.replace` au lieu d'affecter. Un test vérifie que la mutation
lève bien `FrozenInstanceError`.

### 3. `verify_claim(claim, traces=result.rag_traces)` — la liste partagée

La trace était poussée dans une liste fournie par l'appelant. En parallèle,
l'ordre des traces ne correspond plus à celui des affirmations. Désormais
`verify_claim_detail` **rend** un `RagCheck(verdict, trace)`, et `verify_claims`
réassemble dans l'ordre d'entrée.

Bonus corrigé au passage : la propriété `OllamaClient.client` fabriquait son
client HTTP paresseusement, avec un chemin de rafraîchissement de jeton OIDC qui
faisait `self._client = None` puis reconstruisait. Deux threads pouvaient s'y
croiser et récupérer un client au jeton périmé. Un `threading.Lock` protège
maintenant cette fabrication.

---

## Architecture obtenue

```
generate_answer ─> extract_claims ─┬─> branche RAG ──────────────┐
                                   └─> branche SelfCheck ────────┴─> fusion
```

Deux threads pour les branches, puis **chaque branche répartit ses propres
appels** :

| Étage | Variable | Défaut | Ce qui part en parallèle |
|---|---|---|---|
| RAG | `BERLUE_RAG_WORKERS` | 4 | un appel Ollama par affirmation |
| SelfCheck, étage 1 | `BERLUE_SELFCHECK_SAMPLE_WORKERS` | 4 | les K générations d'échantillons |
| SelfCheck, étage 2 | `BERLUE_SELFCHECK_SCORE_WORKERS` | 2 | les passages NLI, un par affirmation |

`1` rend l'étage strictement séquentiel **sans créer de pool** — mode de repli
pour déboguer, et ce que les tests utilisent pour rester déterministes.

Plafonds séparés volontairement : un pool commun ferait dépendre le débit d'un
étage du nombre de tâches d'un autre. `SCORE_WORKERS` est bas par défaut parce
que, contrairement aux appels Ollama (bloqués sur le réseau), les passages NLI
tiennent une place mémoire sur l'appareil de torch, GPU compris.

### Nouveaux fichiers

- `berlue/pipeline/parallel.py` — `map_parallele(fn, items, workers, prefixe)`.
  Ordre d'entrée garanti en sortie, exceptions propagées, repli séquentiel à 1.
- `berlue/selfcheck/branch.py` — `run_selfcheck()`, la branche complète.

### API changée

| Avant | Après |
|---|---|
| `generate_response(question) -> PipelineResult` | `generate_answer(question) -> str` |
| `extract_claims(result) -> PipelineResult` | `extract_claims(question, answer) -> list[Claim]` |
| `generate_samples` + `evaluate_selfcheck` | `run_selfcheck(...) -> SelfCheckOutcome` |
| `evaluate_rag(result) -> PipelineResult` | `retriever.verify_claims(claims) -> RagOutcome` |
| `fuse_results(result)` | `fuse(result)` |
| — | `compute_signals(question, answer)`, `run(question, answer)` |

`verify_claim(claim) -> RagVerdict` **est conservé à l'identique** (contrat testé).
Le contrat HTTP `/predict` (`api/schemas.py`) est **inchangé** : rien à faire
côté front, comme le demandait le plan.

---

## Vérification en local (0.5b partout)

`BERLUE_OLLAMA_MODEL` / `EXTRACT_MODEL` / `RAG_MODEL` = `qwen2.5:0.5b`.
Le modèle d'embedding RAG (`all-mpnet-base-v2`) et le NLI (DeBERTa) ne sont pas
des modèles Ollama, ils sont restés inchangés.

Pipeline complet, question `"Has Ryan Gosling visited Africa ?"` — **9,7 s** au
total, chargement de l'index FAISS (110 k vecteurs) et du NLI compris :

```
   1. No, Ryan Gosling has not visited Africa.
      ↳ 🧠 [SelfCheck] : 🔴 HALLUCINATION | Divergence : 0.60
      ↳ 📚 [RAG]       : 🔴 PROUVÉ FAUX (FEVER) | Confiance : 0.99
          (Preuve: "Ryan Gosling has been to Uganda.")
      ↳ ✨ [FUSION]    : 🔴 REJETÉ | Confiance globale : 0.99
```

Également vérifiés : l'adaptateur d'évaluation (`BerluePipeline.predict`), et
les deux nouvelles cibles `make pipeline_selfcheck` / `make pipeline_rag`.

---

## Mesures — et pourquoi le gain est modeste

### Sur ton Ollama système : 1,23×

```
question                                    claims  séquentiel  parallèle    gain
Has Ryan Gosling visited Africa ?                1       0.95s      0.44s   2.13x
Where was Barack Obama born and what did he     2       0.88s      0.81s   1.08x
What is the Eiffel Tower and when was it bu     1       0.70s      0.80s   0.88x
TOTAL                                                    2.52s      2.06s   1.23x
```

**Cause identifiée** : ton serveur Ollama tourne avec **`-np 1`** (vérifié dans
la ligne de commande de `llama-server`) — un seul slot par modèle. Les requêtes
concurrentes vers le *même* modèle font donc la queue **côté serveur**, et le
parallélisme client n'y peut rien. Le gain observé ne vient que du recouvrement
des deux branches (appel LLM du RAG pendant le passage NLI sur GPU).

### Avec un serveur à `OLLAMA_NUM_PARALLEL=4` : 1,41×

Instance Ollama jetable sur le port 11500, après préchauffage concurrent et
moyenne sur 3 répétitions :

```
question                                    claims  séquentiel  parallèle    gain
Has Ryan Gosling visited Africa ?                1       0.48s      0.36s   1.32x
Where was Barack Obama born and what did he     2       0.92s      0.63s   1.45x
What is the Eiffel Tower and when was it bu     1       0.70s      0.49s   1.43x
TOTAL                                                    2.09s      1.48s   1.41x
```

### Montée en charge de l'échantillonnage, selon K

```
  K  séquentiel  parallèle    gain
  2       0.19s      0.14s   1.33x
  4       0.30s      0.19s   1.61x
  8       0.70s      0.29s   2.45x
 16       0.98s      0.61s   1.61x
```

Le gain culmine à **2,45× (K=8)** puis **retombe à K=16** : le serveur n'a que
4 slots, au-delà les requêtes s'empilent. **Le plafond est `OLLAMA_NUM_PARALLEL`,
pas le code.**

> ⚠️ Ces chiffres sont mesurés avec un 0.5b, où chaque appel dure 50–200 ms —
> l'overhead threads/HTTP y pèse proportionnellement lourd. Avec les modèles 8B
> de production (appels de plusieurs secondes) et davantage d'affirmations par
> réponse, le gain devrait être nettement supérieur. **Non mesuré** : ça
> demandait un serveur multi-slot chargé avec un 8B, hors de ce que tu as
> demandé pour cette session.

---

## À décider / points d'attention

### 1. Chemin de panne RAG mort — antérieur au refacto ⚠️

En écrivant les tests, j'ai constaté que `except json.JSONDecodeError -> RagPanne`
dans `verify_claim_detail` **est inatteignable** :

```python
_premier_objet_json('ceci n est pas du JSON')  -> {}    # pas de '{' : sortie immédiate, sans lever
_premier_objet_json('{"verdict": ')            -> {}    # réparé par _reparer_objet_tronque
_premier_objet_json('{')                       -> {}
```

`_reparer_objet_tronque` raccourcit depuis la fin jusqu'à obtenir un objet
décodable — pour tout texte contenant `{`, il finit toujours par retomber sur
`{}`, qui est valide. Une réponse RAG illisible **dégénère donc silencieusement
en `I_DONT_KNOWN`** au lieu de lever une panne : exactement la confusion
« panne vs ignorance » que la docstring de `RagPanne` dit avoir corrigée.

**Non corrigé volontairement** : c'est un bug antérieur, sans rapport avec le
parallélisme, et le réparer changerait les résultats d'évaluation (davantage de
questions invalidées). J'ai adapté mes tests pour exercer le chemin de panne
réellement atteignable (exception levée par le client Ollama). À trancher
séparément.

### 2. Facteur multiplicatif avec `run_eval`

Le pic de requêtes Ollama simultanées vaut maintenant
`concurrency × (K + RAG_WORKERS)` au lieu de `concurrency × 1`.
Avec les défauts : `concurrency × 9`. `concurrency` vaut 1 par défaut, donc rien
ne change tant que tu ne le montes pas — mais à caler sur le `N_max` du modèle
(`docs/gcp/ollama-gpu-parallelism.md`) avant de le faire.

### 3. `make pipeline_samples` a été supprimé

Il lançait `--until samples`, une étape qui n'existe plus : échantillonnage et
scoring ne sont plus deux étapes successives mais un seul étage de la branche
SelfCheck. `make pipeline_selfcheck` couvre les deux et affiche les échantillons.

### 4. 380 Mo à nettoyer chez toi

J'ai tiré une copie de `qwen2.5:0.5b` dans `~/.ollama` pour l'instance de
benchmark (ton Ollama système vit dans `/usr/share/ollama`, illisible depuis mon
compte). La suppression a été bloquée par le garde-fou, à faire toi-même :

```bash
rm -rf ~/.ollama/models ~/.ollama/cache
```

⚠️ Ne touche pas à `~/.ollama/config.json` ni aux `id_ed25519*` à côté, ils sont
antérieurs. L'instance sur le port 11500 est arrêtée, ton Ollama système est
intact.

### 5. Rien n'est poussé

Deux commits locaux sur `feat-pipeline-parallel`. Aucun `git push` — dis-moi
quand tu veux.

---

## Tests

**296 passés, 1 xpassed** (le `xfail` connu du seuil de distance RAG, `strict=False`,
antérieur). Trois fichiers modifiés, un nouveau (`tests/test_parallel.py`).

Les tests qui portent réellement le refacto :

- `test_les_deux_branches_tournent_bien_en_parallele` — compte les branches en
  vol simultanément (doit valoir 2) **et** vérifie que la durée totale ne
  correspond pas à un enchaînement.
- `test_les_metadonnees_de_generation_ne_se_croisent_pas_entre_threads` — le
  test anti-régression du bug `derniere_generation`.
- `test_generate_many_rend_les_reponses_ordonnees_par_temperature` — le stub dort
  **plus longtemps sur les températures basses**, donc l'ordre d'achèvement est
  l'inverse de l'ordre attendu : un `append` au fil de l'eau échouerait.
- `test_verify_claims_rend_verdicts_et_traces_dans_l_ordre_des_affirmations` —
  même principe côté RAG.
- `test_le_resultat_du_pipeline_est_fige` — `FrozenInstanceError` attendue.
- `test_map_parallele_a_un_seul_worker_reste_sequentiel` — garantit que le mode
  de repli n'ouvre aucun thread.
