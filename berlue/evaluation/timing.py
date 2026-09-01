"""Marqueurs de temps horodatés pour diagnostiquer où passe le temps sur une
exécution (utile en particulier sur GCP, où la latence infra domine très
largement le calcul lui-même — cf. `docs/evaluation/execution-benchmark.md`).

Chaque `mark()` s'affiche immédiatement (`flush=True` — pas de résumé
bufferisé en fin de run, pour rester exploitable même sur un process tué en
cours de route) avec un timestamp epoch UTC, directement comparable aux
`lastTransitionTime` des conditions d'exécution Cloud Run Jobs (mêmes
horodatages, lisibles via `gcloud logging read` sur les logs
`cloudaudit.googleapis.com%2Fsystem_event`).

Volontairement en `print()`, pas `logging` (cf. docs/dev/logging.md) : les
tout premiers appels (`run_eval.py` mesure jusqu'au coût de ses propres
imports) ont lieu avant que `setup_logging()` ait pu tourner — sans handler
configuré, `logger.info()` serait silencieusement avalé à ce stade.
"""

import time

_first: float | None = None
_last: float | None = None


def mark(label: str) -> None:
    """Affiche `label` avec l'horodatage courant, le delta depuis le
    marqueur précédent et le delta depuis le tout premier marqueur du
    process."""
    global _first, _last
    now = time.time()
    if _first is None:
        _first = now
        _last = now
    since_prev = now - _last
    since_start = now - _first
    _last = now
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now % 1 * 1e6):06d}Z"
    print(f"⏱[TIMING] {label} : {ts} (+{since_prev:.3f}s, total +{since_start:.3f}s)", flush=True)
