"""Configuration centralisée du logging applicatif.

Point d'entrée unique (`setup_logging`), à appeler explicitement une fois par
point d'entrée du programme (CLI, API) — jamais à l'import d'un module de
bibliothèque, pour ne pas imposer de config à qui importe `berlue` ailleurs.
"""

import logging

from berlue.params import LOG_LEVEL


def setup_logging(level: str | None = None) -> None:
    """Configure le logging racine pour tout le package `berlue`.

    `level` (ERROR/WARNING/INFO/DEBUG) prend le pas sur `BERLUE_LOG_LEVEL`
    quand fourni (ex. override `--log-level` en ligne de commande).
    """
    logging.basicConfig(
        level=level or LOG_LEVEL,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
