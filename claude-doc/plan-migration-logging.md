# Plan — migration des `print()` vers `logging` (LOG_LEVEL configurable)

> **Statut : plan seulement, aucun code touché.** Prépare la bascule de
> `print()` vers le module `logging` standard, avec un niveau configurable
> (ERROR/WARNING/INFO/DEBUG). Ce plan précède
> [`plan-parallelisation-pipeline.md`](plan-parallelisation-pipeline.md), qui
> reste repoussé à plus tard.

## Objectif

Remplacer les `print()` de diagnostic par des appels `logging` filtrables par
niveau, sans casser les deux choses qui dépendent aujourd'hui du
comportement actuel :

- la **sortie produit** des CLI (`hurlu_berlu.py`, `run_eval.py`,
  `nli_baseline/predict.py`) — ce que ces commandes existent pour afficher,
  pas un log de diagnostic ;
- les **tests qui capturent du texte sur stdout** (`capsys`), notamment
  `tests/test_run_eval.py::test_evaluate_model_generated_prints_detailed_timer_summary`
  et son pendant baseline, qui asserte sur le texte exact produit par
  `evaluate_model_generated`/`evaluate_baseline_generated`.

## État des lieux

`print()` apparaît **139 fois** dans `berlue/`, 0 usage de `logging`
actuellement (`import logging` : aucune occurrence). Répartition :

| Fichier | # print | Nature dominante |
|---|---:|---|
| `pipeline/hurlu_berlu.py` | 26 | mix diagnostic + **sortie CLI** (`main()`) |
| `evaluation/run_eval.py` | 23 | mix diagnostic + **sortie CLI** (rapports, résumés) |
| `llm/client.py` | 19 | diagnostic (requêtes/réponses Ollama, erreurs) |
| `ml_logic/registry.py` | 13 | diagnostic (save/load modèle, MLflow) |
| `interface/main.py` | 8 | diagnostic (essentiellement commenté / mort) |
| `ml_logic/data.py` | 7 | diagnostic |
| `evaluation/data.py` | 7 | diagnostic (téléchargement/chargement datasets) |
| `rag/retriever.py` | 6 | diagnostic + erreurs de parsing |
| `rag/indexer.py` | 6 | diagnostic (construction index FAISS) |
| `nli_baseline/train.py` | 3 | diagnostic |
| `api/fast.py` | 3 | diagnostic (lifespan FastAPI) |
| `selfcheck/scorer.py` | 2 | diagnostic + 1 print de debug brut (`divergence = ...`) |
| `pipeline/extraction.py` | 2 | erreurs de parsing JSON |
| `interface/workflow.py` | 2 | diagnostic (mort, dépend de `main.py` non implémenté) |
| `pipeline/fusion.py` | 1 | diagnostic |
| `nli_baseline/predict.py` | 1 | **sortie CLI** (le résultat de la prédiction) |
| `evaluation/timing.py` | 1 | diagnostic (timing, `flush=True`) |
| `scripts/*.py` (3 fichiers) | 28 | scripts dev ponctuels, hors package `berlue` |

Les préfixes emoji suggèrent une intuition de niveau, mais **pas de façon
fiable** — le même emoji sert à des sévérités différentes selon le contexte
(cf. section 4 ci-dessous, corrigée après une première version qui mappait
mécaniquement par emoji). Le classement retenu se fait par contexte du
`print()`, pas par son symbole.

## Distinction clé : log de diagnostic vs sortie CLI

Deux familles de `print()` très différentes, à ne pas traiter pareil :

1. **Logs de diagnostic** — progression, avertissements, erreurs internes
   (`"🔍 Recherche du serveur Ollama..."`, `"❌ Erreur API Ollama : ..."`,
   `"✅ Index chargé : ..."`). Ce sont eux qui migrent vers `logging`, pour
   pouvoir les couper/filtrer par niveau sans toucher au code appelant.
2. **Sortie CLI** — le résultat que l'utilisateur a lancé la commande pour
   obtenir : le bilan affiché par `hurlu_berlu.py main()`, les rapports
   `run_eval.py` (`--report`, résumé de matrice, timers détaillés couverts
   par les tests `capsys` cités plus haut), la prédiction de
   `nli_baseline/predict.py`. Ça reste du `print()` sur stdout — c'est le
   produit de la commande, pas un log, et le couper avec `LOG_LEVEL=ERROR`
   n'aurait aucun sens pour l'utilisateur qui lance `python -m
   berlue.evaluation.run_eval`.

Convention Unix standard réutilisée : stdout = résultat de la commande,
stderr (où `logging` écrit par défaut) = diagnostic. Chaque `print()` sera
classé explicitement dans l'une des deux catégories pendant la migration
(colonne à ajouter au tableau de suivi, voir Phase 2).

## Design proposé

### 1. Niveau configurable — `BERLUE_LOG_LEVEL`

Nouvelle variable dans `berlue/params.py`, même convention que les autres
(`BERLUE_*`, défaut si absent) :

```python
LOG_LEVEL = os.environ.get("BERLUE_LOG_LEVEL", "INFO")
assert LOG_LEVEL in ("ERROR", "WARNING", "INFO", "DEBUG"), (
    f"❌ LOG_LEVEL invalide : {LOG_LEVEL!r} (doit être ERROR, WARNING, INFO ou DEBUG)"
)
```

### 2. Setup centralisé — `berlue/logging_config.py`

Un seul point d'entrée, appelé **une fois** par chaque point d'entrée du
programme (jamais à l'import d'un module de bibliothèque) :

```python
import logging

from berlue.params import LOG_LEVEL

def setup_logging(level: str | None = None) -> None:
    logging.basicConfig(
        level=level or LOG_LEVEL,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
```

Appelé depuis :
- `hurlu_berlu.py` et `run_eval.py`, dans le bloc `if __name__ ==
  "__main__":`, avant `parser.parse_args()` ne serait-ce que pour permettre
  un override en ligne de commande (point 4) ;
- `api/fast.py`, en tout début de `lifespan()` (ou au chargement du module,
  avant que `uvicorn` ne configure son propre logging — voir point 5) ;
- les scripts sous `scripts/` s'ils sont migrés (Phase 3, à trancher).

### 3. Un logger par module

Convention standard, un logger nommé par module en haut de chaque fichier
touché :

```python
import logging

logger = logging.getLogger(__name__)
```

`%(name)s` dans le format ci-dessus donne alors des lignes du style
`14:32:01 INFO     berlue.rag.retriever: Index chargé : 12450 vecteurs`,
filtrables aussi par logger (`logging.getLogger("berlue.llm").setLevel(...)`)
si besoin plus tard sans y toucher.

### 4. Classement par contexte, pas par emoji

Une première version de ce plan proposait un mapping mécanique *emoji →
niveau* (`❌`→error, `⚠️`→warning, tout le reste→info). Relu de plus près,
il ne tient pas : le même emoji recouvre des sévérités opposées selon le
`print()`, et un mapping par symbole les confondrait silencieusement lors
de la migration. Deux exemples concrets qui ont fait abandonner l'approche :

- `client.py:106`, dans un `except TimeoutException:` juste avant un
  `raise TimeoutError` : `print("⏳ Timeout : Ollama n'a pas répondu...")`.
  Le `⏳` (utilisé ailleurs pour une simple progression, ex.
  `nli_baseline/train.py:25` `"⏳ Chargement et découpage des données..."`)
  décrit ici un **échec**, pas un statut normal — mappé "info" par emoji,
  il faudrait `logger.error` (l'exception qui suit le confirme).
- `client.py:98` et `:125` (`📤`/`📥`, dump du prompt/réponse complets,
  déjà protégés par `if self.verbose:`) — l'ancienne table les rangeait à
  la fois dans le seau "info" (via l'emoji) et dans l'exemple "debug" (via
  la description). Ce sont des dumps verbeux protégés par un flag verbose
  existant : `logger.debug`, pas `logger.info`.

Le critère retenu est donc, par `print()`, à décider au moment de la
migration (Phases 1-2) en répondant à deux questions :

1. **Signale-t-il un échec ?** (dans un `except`, ou juste avant un
   `raise`/`return None` en sortie anormale) → `error` s'il précède/accompagne
   une exception qui remonte, `warning` s'il est géré et l'exécution continue
   normalement avec un résultat dégradé.
2. **Sinon, est-ce un jalon (une fois par appel/run) ou une trace fine
   répétée en boucle (une fois par claim/sample/exemple) ?** → `info` pour
   un jalon, `debug` pour une trace en boucle — sinon `LOG_LEVEL=INFO` (le
   défaut) inonderait les logs à chaque itération.

| Type | Niveau | Exemples (reclassés) |
|---|---|---|
| Échec qui remonte (`except` → `raise`) | `logger.error` | `client.py:106` (`⏳ Timeout...`, malgré l'emoji), `client.py:110/114` (`❌ Erreur API Ollama...`) |
| Échec géré, exécution continue dégradée | `logger.warning` | `retriever.py:127/131` (erreur de parsing JSON sur une affirmation, la boucle continue), `registry.py:96` (`❌ Aucun modèle local trouvé` → `return None` propre, pas d'exception — à confirmer selon l'usage réel en aval, cf. Décisions ouvertes) |
| Jalon, une fois par appel/run | `logger.info` | `"✅ Index chargé : ..."` (`retriever.py:44`), `"🚀 Démarrage du pipeline..."` (`hurlu_berlu.py:120`), `evaluation/data.py` (téléchargement/chargement dataset) |
| Trace fine répétée en boucle, ou dump verbeux déjà `if verbose` | `logger.debug` | `client.py:98/125` (prompt/réponse complets), `client.py:160-165` (`generate_many`, une fois par température — `"🔄 Génération en cours..."` + réponse + séparateur), `retriever.py:138` (`"Vérification RAG de l'affirmation {i}/{len(claims)}..."`, une fois par claim), `scorer.py:48` (`divergence = ...` brut) |

L'emoji reste dans le message (`logger.info("✅ Index chargé : %s
vecteurs", n)`) — il survit tel quel dans les logs, seul le niveau qui le
porte est décidé au cas par cas, plus jamais déduit automatiquement du
symbole.

### 5. Override ligne de commande sur les CLI

`hurlu_berlu.py` et `run_eval.py` ont déjà un `argparse.ArgumentParser` —
ajouter un flag commun :

```python
parser.add_argument(
    "--log-level",
    choices=["ERROR", "WARNING", "INFO", "DEBUG"],
    default=None,
    help="Niveau de log (défaut : BERLUE_LOG_LEVEL, ou INFO).",
)
```

puis `setup_logging(args.log_level)` juste après le parsing — override
explicite prioritaire sur la variable d'env, cohérent avec le pattern déjà
utilisé pour `MODEL_TARGET` (env par défaut, CLI pour forcer ponctuellement).

### 6. `api/fast.py` / `uvicorn`

`uvicorn` configure son propre logging au démarrage (accès + erreurs
serveur), indépendant du `logging` applicatif. Appeler `setup_logging()`
avant que `uvicorn.run`/`Config` ne s'exécute évite qu'il écrase la config
applicative ; pas besoin d'unifier les deux formats dans un premier temps,
juste s'assurer que `logger.info(...)` dans `lifespan()` produit bien une
ligne (test manuel prévu en Phase 2). Fait aussi le lien avec
`BERLUE_LOG_LEVEL` côté Cloud Run — actuellement pas branché sur
`uvicorn --log-level`, à traiter si besoin dans un plan de déploiement
séparé, pas ici.

### 7. `colorama` (déjà une dépendance)

Utilisé aujourd'hui de façon éparse (`Fore.BLUE`, `Fore.MAGENTA`, surtout
dans du code commenté/mort de `registry.py`/`interface/main.py`). Pas de
formatter coloré par niveau dans ce plan — complexité pas justifiée tant
que la bascule de base n'est pas faite. Question ouverte en fin de doc.

## Plan de migration par phases

**Phase 0 — Fondations** (petit, isolé, testable seul)
- `BERLUE_LOG_LEVEL` dans `params.py` + assert.
- `berlue/logging_config.py` avec `setup_logging()`.
- Mise à jour `.env.sample` (documentation de la variable).
- `docs/dev/logging.md` : convention (logger par module, niveaux, print vs
  log), à créer aux côtés de `docs/dev/linting.md`/`tests.md` déjà existants.

**Phase 1 — Modules diagnostic purs** (pas de sortie CLI à préserver, risque
le plus faible, sert de gabarit pour la suite)
- `rag/indexer.py` (6), `rag/retriever.py` (6), `selfcheck/scorer.py` (2),
  `pipeline/extraction.py` (2), `pipeline/fusion.py` (1),
  `nli_baseline/train.py` (3), `evaluation/data.py` (7),
  `evaluation/timing.py` (1 — attention au `flush=True`, `logging` flush
  différemment selon le handler, à vérifier que ça reste utilisable pour du
  suivi temps réel), `api/fast.py` (3), `ml_logic/registry.py` (13),
  `ml_logic/data.py` (7).

**Phase 2 — Modules mixtes (diagnostic + sortie CLI)** — le plus délicat,
à faire fichier par fichier avec une colonne "log" vs "sortie" explicite
par `print()` avant de toucher au code :
- `llm/client.py` (19 — presque tout diagnostic, mais le bloc `if __name__
  == "__main__":` en bas est un mini-CLI de test manuel, à trancher au cas
  par cas) ;
- `pipeline/hurlu_berlu.py` (26 — les fonctions internes type
  `evaluate_claims` sont diagnostic, `main()` est très majoritairement
  sortie CLI à préserver telle quelle) ;
- `evaluation/run_eval.py` (23 — le plus gros et le plus sensible : contient
  le résumé de timers couvert par les deux tests `capsys` cités plus haut.
  **Ces prints-là ne bougent pas** sans mettre à jour les tests en
  conséquence — décision explicite à prendre par print, pas un renommage en
  masse) ;
- `nli_baseline/predict.py` (1 — reste `print(result)`, c'est la sortie).

**Phase 3 — `scripts/`** (hors package `berlue`, priorité plus basse —
outils dev ponctuels lancés à la main, pas de consommateur de logs
filtrés) : `push_local_to_gcp.py`, `explore_eval_store.py`,
`ollama_load_test.py`. Décision ouverte : migrer aussi ou laisser en
`print()` (voir Décisions ouvertes).

**Phase 4 — Nettoyage** : `interface/main.py`/`interface/workflow.py`
contiennent surtout du code mort/commenté (`train`/`evaluate` non
implémentés) — pas de vrai `print()` actif à migrer, juste vérifier qu'on
ne réactive pas des `print()` commentés lors d'un futur remplissage de ces
fonctions.

## Points d'attention

- **Tests `capsys`** (`tests/test_run_eval.py`, lignes ~761 et ~784) :
  ils asserte sur le texte produit par `evaluate_model_generated`/
  `evaluate_baseline_generated`. Tant que ces prints restent classés
  "sortie CLI" (Phase 2), les tests ne bougent pas. S'il s'avère qu'un de
  ces prints est en fait un diagnostic à migrer, il faudra adapter le test
  vers `caplog` en même temps — jamais un changement silencieux qui casse
  le test sans qu'on l'ait décidé.
- **`registry.py` warmup** (`llm/client.py` non, `run_eval.py:467-468`) :
  motif `print(..., end="")` suivi d'un `print(...)` pour composer une
  seule ligne en deux temps — `logging` n'a pas d'équivalent direct à
  `end=""` (chaque appel = une ligne). À fusionner en un seul
  `logger.info(...)` avec les deux valeurs, pas à reproduire tel quel.
- **`flush=True`** (`evaluation/timing.py`) : utilisé pour un affichage
  temps réel pendant un run long. Un `StreamHandler` standard flush par
  défaut sur chaque `emit()` en pratique suffisamment tôt, mais à vérifier
  concrètement sur ce cas précis avant de considérer la migration
  terminée.
- **`interface/workflow.py`** dépend de `interface/main.py` dont
  `train`/`evaluate` sont des stubs (`pass`) — les 2 `print()` de
  `workflow.py` sont probablement jamais exécutés en pratique aujourd'hui ;
  à confirmer plutôt que d'y passer du temps de migration.

## Décisions tranchées

- **Nom de la variable** : `BERLUE_LOG_LEVEL` (cohérent avec les autres
  `BERLUE_*` de `params.py`), défaut `"INFO"`.
- **Setup** : `logging.basicConfig` centralisé dans
  `berlue/logging_config.py`, appelé explicitement par chaque point
  d'entrée — pas de config implicite à l'import d'un sous-module.
- **stdout vs stderr** : la sortie CLI (résultat produit par la commande)
  reste `print()` sur stdout ; tout le reste bascule vers `logging` (stderr
  par défaut). Pas de handler custom qui redirigerait `logging` vers stdout.
- **Un logger par module** (`logging.getLogger(__name__)`), pas un logger
  unique global.
- **Classement des niveaux par contexte, pas par emoji** (section 4) —
  chaque `print()` migré est classé individuellement au moment de la
  migration selon les deux questions de la section 4, jamais par un mapping
  automatique sur le symbole en tête du message.

## Décisions ouvertes

- **`registry.py:96`** (`"❌ Aucun modèle local trouvé"` avant `return
  None`) : `warning` (cas géré, pas d'exception) ou `error` (bloque quand
  même `load_model` pour l'appelant) ? Dépend de si c'est un cas attendu
  (premier lancement avant tout entraînement) ou pas — à trancher en
  Phase 1 en regardant qui appelle `load_model` et comment le `None` est
  géré en aval.
- **`scripts/` (Phase 3)** : migrer aussi vers `logging`, ou laisser en
  `print()` puisque ce sont des outils dev lancés à la main sans besoin de
  filtrage par niveau ?
- **Formatter coloré (`colorama`)** : garder `colorama` pour un formatter
  `logging` qui colore par niveau (ERROR rouge, WARNING jaune...), ou
  abandonner l'usage de `colorama` maintenant que son rôle est repris par
  `logging` ?
- **`llm/client.py` bloc `__main__`** (mini-CLI de test manuel en bas du
  fichier) : sortie CLI à préserver, ou diagnostic à migrer comme le reste
  du fichier ?
- **Format des logs** : `%(asctime)s %(levelname)-8s %(name)s: %(message)s`
  proposé ci-dessus — à valider, notamment si un format plus court est
  préférable en local (le `%(name)s` répète `berlue.` sur chaque ligne).

## Prochaine étape

Une fois ce plan validé (notamment les 4 décisions ouvertes ci-dessus),
Phase 0 peut démarrer sans dépendre du reste — c'est un ajout pur (nouveau
fichier + nouvelle variable), aucun `print()` existant n'est touché avant
Phase 1.
