import hashlib
import json
import logging
import re

from berlue.core.schemas import Claim
from berlue.llm.client import OllamaClient
from berlue.params import EXTRACT_SYSTEM_PROMPT, NUM_PREDICT_EXTRACTION

logger = logging.getLogger(__name__)


def _claim_id(answer_text: str, rank: int, text: str) -> str:
    """Identifiant reproductible d'une affirmation.

    Un `uuid4()` rendait un cas impossible à rejouer : les identifiants changeaient à
    chaque exécution, alors qu'ils servent de clé d'appariement entre l'extraction, le
    RAG, SelfCheck et la fusion — et qu'ils sont journalisés. Dérivé du texte de la
    réponse, du rang et du texte de l'affirmation, il est stable d'un run à l'autre et
    reste distinct pour deux affirmations identiques extraites de réponses différentes.
    """
    empreinte = hashlib.sha256(f"{answer_text}\x00{rank}\x00{text}".encode()).hexdigest()
    return empreinte[:16]


def do_extraction(llm_extract: OllamaClient, question: str, answer_text: str) -> list[Claim]:
    """Découpe une réponse en affirmations atomiques, indépendantes et dont les pronoms sont résolus."""
    if not answer_text or not answer_text.strip():
        return []

    # On injecte maintenant la question ET la réponse dans le prompt
    prompt = EXTRACT_SYSTEM_PROMPT.format(question=question, answer_text=answer_text)

    raw_response = llm_extract.generate(prompt=prompt, temperature=0.0, num_predict=NUM_PREDICT_EXTRACTION)

    # 1. Extraction du tableau JSON. Non gourmand : `\[.*\]` en DOTALL allait du
    # premier `[` au dernier `]` de la réponse, avalant tout ce qu'il y avait entre.
    match = re.search(r"\[.*?\]", raw_response, re.DOTALL)

    if not match:
        logger.warning(
            "⚠️ Erreur LLM : Impossible de trouver un tableau JSON dans l'extraction. Réponse brute : %s",
            raw_response,
        )
        return []

    clean_json_str = match.group(0)

    # 2. Parsing du JSON
    try:
        extracted_strings = json.loads(clean_json_str)
    except json.JSONDecodeError as e:
        logger.warning("⚠️ Erreur LLM : JSON d'extraction mal formé : %s\nTexte : %s", e, clean_json_str)
        return []

    # 3. Création des objets Claim
    if not isinstance(extracted_strings, list):
        logger.warning("⚠️ Erreur LLM : l'extraction n'a pas rendu un tableau : %r", extracted_strings)
        return []

    claims = []
    for rang, element in enumerate(extracted_strings):
        # Le prompt demande un tableau de chaînes, mais rien ne l'y contraint : un
        # `[{"claim": "..."}]` faisait lever un AttributeError non attrapé, qui
        # arrêtait tout le run d'évaluation. On ignore l'élément et on continue.
        if not isinstance(element, str):
            logger.warning("⚠️ Élément d'extraction ignoré, ce n'est pas une chaîne : %r", element)
            continue
        claim_text = element.strip()
        if claim_text:  # Sécurité contre les chaînes vides
            claims.append(
                Claim(id=_claim_id(answer_text, rang, claim_text), text=claim_text, source_answer=answer_text)
            )

    return claims
