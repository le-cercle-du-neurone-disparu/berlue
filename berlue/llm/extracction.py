"""Module d'extraction des affirmations atomiques d'un texte."""

import textwrap
import uuid

from berlue.core.schemas import Claim
from berlue.llm.client import OllamaClient


def extract_claims(answer_text: str, client: OllamaClient | None = None) -> list[Claim]:
    """
    Découpe une réponse brute du LLM en une liste d'affirmations (claims)
    indépendantes et atomiques en utilisant un prompt strict.
    """
    if not answer_text or not answer_text.strip():
        return []

    client = client or OllamaClient()

    # On force le LLM à formater sa réponse de manière prédictible
    # (une liste à puces) pour la parser facilement en Python.
    prompt = textwrap.dedent(f"""\
        Tu es un expert en analyse de données factuelles. Ta tâche est de décomposer
        le texte suivant en une liste d'affirmations courtes, atomiques et indépendantes.

        Règles strictes :
        1. Chaque affirmation ne doit contenir qu'une seule idée ou un seul fait.
        2. Chaque affirmation doit avoir du sens toute seule hors contexte
           (remplace impérativement les pronoms comme 'il', 'elle', 'ce' par le sujet explicite).
        3. Ne rajoute aucun texte avant ou après ta liste.
        4. Tu dois répondre UNIQUEMENT par une liste à puces, où chaque ligne commence par '- '.

        Texte à analyser :
        {answer_text}

        Affirmations :
    """)

    # On cherche un comportement aussi déterministe que possible (temperature = 0)
    raw_response = client.generate(prompt=prompt, temperature=0.0)

    claims = []

    # Parsing artisanal
    for line in raw_response.split("\n"):
        line = line.strip()

        # On ne garde que les lignes qui ressemblent aux puces demandées
        if line.startswith("- "):
            claim_text = line[2:].strip()

            if claim_text:
                claims.append(
                    Claim(
                        id=str(uuid.uuid4()),  # Un ID unique pour tracer le claim plus tard
                        text=claim_text,
                        source_answer=answer_text,
                    )
                )

    return claims
