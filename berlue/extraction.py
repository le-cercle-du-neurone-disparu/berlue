import textwrap
import uuid

from berlue.core.schemas import Claim
from berlue.llm.client import OllamaClient


def do_extraction(llm_extract: OllamaClient, answer_text: str) -> list[Claim]:
    """Découpe une réponse en affirmations atomiques."""
    if not answer_text or not answer_text.strip():
        return []

    prompt = textwrap.dedent(f"""\
            Tu es un expert en analyse de données factuelles. Ta tâche est de décomposer
            le texte suivant en une liste d'assertions courtes, atomiques et indépendantes.

            Règles strictes :
            1. Chaque assertion ne doit contenir qu'une seule idée ou un fait.
            2. Chaque assertion doit avoir du sens toute seule hors contexte
               (remplace les pronoms comme 'il', 'elle', 'ce' par le sujet explicite).
            3. Ne rajoute aucun texte avant ou après ta liste.
            4. Tu dois répondre UNIQUEMENT par une liste à puces (commençant par '- ').

            Ne te sens pas obligé de produire pluisuers assertions s'il n'y en a qu'une dans le texte à analyser.

            Texte à analyser :
            {answer_text}

            Affirmations :
        """)

    raw_response = llm_extract.generate(prompt=prompt, temperature=0.0)

    claims = []
    for line in raw_response.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            claim_text = line[2:].strip()
            if claim_text:
                claims.append(Claim(id=str(uuid.uuid4()), text=claim_text, source_answer=answer_text))

    return claims
