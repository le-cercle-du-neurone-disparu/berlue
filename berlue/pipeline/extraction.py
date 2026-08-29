import json
import re
import uuid

from berlue.core.schemas import Claim
from berlue.llm.client import OllamaClient
from berlue.params import EXTRACT_SYSTEM_PROMPT


def do_extraction(llm_extract: OllamaClient, answer_text: str) -> list[Claim]:
    """Découpe une réponse en affirmations atomiques, indépendantes et résolues."""
    if not answer_text or not answer_text.strip():
        return []

    prompt = EXTRACT_SYSTEM_PROMPT.format(answer_text=answer_text)

    raw_response = llm_extract.generate(prompt=prompt, temperature=0.0)

    # 1. Extraction robuste du tableau JSON
    # On cherche tout ce qui est entre crochets [ ... ]
    match = re.search(r"\[.*\]", raw_response, re.DOTALL)

    if not match:
        print(f"⚠️ Erreur LLM : Impossible de trouver un tableau JSON dans l'extraction. Réponse brute : {raw_response}")
        return []

    clean_json_str = match.group(0)

    # 2. Parsing du JSON
    try:
        extracted_strings = json.loads(clean_json_str)
    except json.JSONDecodeError as e:
        print(f"⚠️ Erreur LLM : JSON d'extraction mal formé : {e}\nTexte : {clean_json_str}")
        return []

    # 3. Création des objets Claim
    claims = []
    for claim_text in extracted_strings:
        claim_text = claim_text.strip()
        if claim_text:  # Sécurité contre les chaînes vides
            claims.append(Claim(id=str(uuid.uuid4()), text=claim_text, source_answer=answer_text))

    return claims
