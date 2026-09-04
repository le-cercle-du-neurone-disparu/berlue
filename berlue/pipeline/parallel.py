"""Exécution en parallèle d'une même opération sur une liste d'éléments.

Les étages coûteux du pipeline (un appel Ollama par affirmation côté RAG, K
générations puis un passage NLI côté SelfCheck) sont indépendants les uns des
autres et bloqués sur le réseau ou sur torch, qui relâchent tous deux le GIL :
les répartir sur un pool de threads est un gain direct.
"""

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


def map_parallele[T, R](fn: Callable[[T], R], items: Sequence[T], max_workers: int, prefixe: str) -> list[R]:
    """Applique `fn` à chaque élément d'`items` en parallèle et rend les résultats
    DANS L'ORDRE D'ENTRÉE, quel que soit l'ordre d'achèvement.

    L'ordre est un contrat, pas un détail : les échantillons SelfCheck sont
    appariés à leur température par leur rang, et deux exécutions du même
    pipeline doivent produire la même liste pour rester comparables.

    Une exception levée par `fn` remonte à l'appelant — c'est celle du premier
    élément en échec dans l'ordre d'entrée, les autres tâches étant attendues
    avant de sortir. Un `RagPanne` invalide ainsi la question entière comme en
    séquentiel.

    `max_workers <= 1` exécute en séquentiel, sans créer de pool : c'est le mode
    de repli pour déboguer une exécution parallèle et ce que les tests utilisent
    pour rester déterministes.
    """
    if not items:
        return []

    workers = min(max_workers, len(items))
    if workers <= 1:
        return [fn(item) for item in items]

    logger.debug("🧵 %s : %d élément(s) sur %d thread(s)", prefixe, len(items), workers)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=prefixe) as executor:
        # `executor.map` rend un générateur paresseux : le `list()` doit rester
        # DANS le `with`, sinon la sortie du bloc attend les tâches avant que
        # le moindre résultat n'ait été lu.
        return list(executor.map(fn, items))
