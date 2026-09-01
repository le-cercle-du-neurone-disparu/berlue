# Logging

Convention de logging du package `berlue` — `logging` standard, pas de
`print()` pour le diagnostic. Contexte complet de la migration :
[`claude-doc/plan-migration-logging.md`](../../claude-doc/plan-migration-logging.md).

### Deux familles de sortie, à ne pas confondre

- **Logs de diagnostic** (progression, avertissements, erreurs internes) —
  passent par `logging`, filtrables par niveau, écrits sur stderr.
- **Sortie CLI** (le résultat que la commande sert à produire — bilan
  `hurlu_berlu.py`, rapports `run_eval.py`, prédiction
  `nli_baseline/predict.py`) — reste du `print()` sur stdout. Ce n'est pas
  du diagnostic : la couper avec `LOG_LEVEL=ERROR` n'aurait aucun sens pour
  quelqu'un qui lance la commande pour voir ce résultat.

### Niveau configurable

`BERLUE_LOG_LEVEL` (`.env`, défaut `INFO`) — `ERROR` / `WARNING` / `INFO` /
`DEBUG`. Cf. `berlue/params.py`. Les scripts avec un `argparse` exposent en
plus un flag `--log-level` qui prend le pas sur la variable d'env.

### Un logger par module

```python
import logging

logger = logging.getLogger(__name__)
```

Pas de logger global unique — ça permet de filtrer par module plus tard
(`logging.getLogger("berlue.llm").setLevel(...)`) sans toucher au code.

### Setup — un seul point d'entrée par programme

```python
from berlue.logging_config import setup_logging

setup_logging()  # ou setup_logging(args.log_level) si le CLI expose --log-level
```

À appeler une fois, au tout début de chaque point d'entrée (bloc `if
__name__ == "__main__":` d'un script, `lifespan()` de l'API) — jamais à
l'import d'un module de bibliothèque, pour ne pas imposer de config à qui
importe `berlue` ailleurs (notebook, autre projet).

### Quel niveau pour quel message ?

Pas de règle mécanique sur le symbole/emoji en tête du message (deux
messages avec le même emoji peuvent avoir des sévérités opposées — cf. le
plan de migration pour des exemples concrets). Se poser plutôt ces deux
questions :

1. **Le message signale-t-il un échec ?**
   - Dans un `except` suivi d'un `raise` qui remonte → `logger.error`.
   - Géré, l'exécution continue avec un résultat dégradé (pas
     d'exception) → `logger.warning`.
2. **Sinon, jalon ou trace en boucle ?**
   - Une fois par appel/run (ex. "Index chargé", "Démarrage du pipeline")
     → `logger.info`.
   - Répété à chaque itération (une fois par claim/sample/exemple), ou dump
     verbeux d'un payload complet → `logger.debug`. À ce volume, `INFO` (le
     niveau par défaut) inonderait les logs.
