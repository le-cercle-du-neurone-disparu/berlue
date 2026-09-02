import json
import logging
import re
import uuid

from berlue.core.schemas import Claim
from berlue.llm.client import OllamaClient
from berlue.params import EXTRACT_SYSTEM_PROMPT, NUM_PREDICT_EXTRACTION

logger = logging.getLogger(__name__)


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
    for element in extracted_strings:
        # Le prompt demande un tableau de chaînes, mais rien ne l'y contraint : un
        # `[{"claim": "..."}]` faisait lever un AttributeError non attrapé, qui
        # arrêtait tout le run d'évaluation. On ignore l'élément et on continue.
        if not isinstance(element, str):
            logger.warning("⚠️ Élément d'extraction ignoré, ce n'est pas une chaîne : %r", element)
            continue
        claim_text = element.strip()
        if claim_text:  # Sécurité contre les chaînes vides
            claims.append(Claim(id=str(uuid.uuid4()), text=claim_text, source_answer=answer_text))

    return claims
