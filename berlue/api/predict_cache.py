"""Clé et règle d'usage du cache de prédiction.

Ce module ne stocke rien : il dit seulement à quoi une entrée correspond et si
elle satisfait une requête. La persistance est dans les magasins de résultats.

À ne pas confondre avec les caches d'évaluation (`eval_predictions`,
`eval_signals`…), qui identifient un modèle par son tag exact : une évaluation
compare des modèles, servir le résultat d'un autre ruinerait la mesure. Ici la
question est différente — éviter de repayer six minutes de pipeline pour une
question déjà posée — et la taille du modèle suffit.
"""

import re

CACHE_FORMAT_VERSION = 1

# Taille en milliards de paramètres, lue dans le tag Ollama : `llama3.1:8b` → 8,
# `qwen2.5:0.5b` → 0.5. Le suffixe peut être collé à autre chose (`:8b-instruct`),
# d'où l'absence d'ancrage en fin de chaîne.
_TAILLE = re.compile(r"(\d+(?:\.\d+)?)\s*b\b", re.IGNORECASE)


def normaliser_question(question: str) -> str:
    """Clé de cache d'une question : espaces de bord retirés, casse repliée.

    Volontairement grossier — ni la ponctuation ni les accents ne sont
    normalisés. « la France? » et « la France ? » restent deux entrées. Aller
    plus loin ferait converger des formulations que le modèle traiterait
    différemment ; à revoir si le taux de succès observé le justifie.
    """
    return question.strip().lower()


def taille_modele(tag: str) -> float | None:
    """Nombre de milliards de paramètres lu dans un tag Ollama, `None` si illisible.

    `phi3.5:latest` ne dit pas sa taille : rendre `None` plutôt que deviner, car
    une taille inventée servirait un résultat calculé par un modèle plus faible.
    Le numéro de version ne doit pas être pris pour une taille — dans
    `llama3.2:3b`, seul le `3b` compte, pas le `3.2`.
    """
    apres_deux_points = tag.split(":", 1)[1] if ":" in tag else tag
    trouve = _TAILLE.search(apres_deux_points)
    return float(trouve.group(1)) if trouve else None


def satisfait(demandes: tuple[str, ...], caches: tuple[str, ...]) -> bool:
    """L'entrée en cache convient-elle à une requête ?

    `demandes` et `caches` sont les tags des mêmes rôles, dans le même ordre :
    (générateur, extraction, RAG). L'entrée convient si CHAQUE modèle demandé
    est au plus aussi gros que son homologue en cache — un verdict calculé par
    un modèle plus gros vaut au moins celui d'un plus petit.

    Seule la taille compte, jamais la famille : `mistral:7b` et `gemma:7b` sont
    équivalents. Deux tags identiques conviennent toujours, y compris quand leur
    taille est illisible — c'est le cas courant, et il ne doit dépendre d'aucune
    analyse du nom. En revanche deux tags différents dont l'un au moins ne dit
    pas sa taille ne sont pas comparables : on recalcule plutôt que de servir un
    résultat peut-être produit par plus faible que soi.
    """
    if len(demandes) != len(caches):
        raise ValueError(f"❌ rôles non appariés : {len(demandes)} demandés, {len(caches)} en cache")

    for demande, cache in zip(demandes, caches, strict=True):
        if demande == cache:
            continue
        taille_demandee, taille_cachee = taille_modele(demande), taille_modele(cache)
        if taille_demandee is None or taille_cachee is None:
            return False
        if taille_demandee > taille_cachee:
            return False
    return True
