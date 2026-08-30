"""LLM-juge du mode 2 de l'évaluation (réponse générée par le LLM sous test,
plutôt que la réponse figée du dataset) — détermine si une réponse candidate
se rapproche de la réponse correcte ou d'une réponse incorrecte de référence,
toutes deux tirées du dataset. Sert de vérité-terrain de substitution pour une
réponse générée à la volée, qui n'a pas de label direct dans le dataset.

Params utilisés (`berlue.params`) : `JUDGE_MODEL`.
"""

import random
import re
import textwrap

from berlue.core.schemas import Verdict
from berlue.llm.client import OllamaClient
from berlue.params import JUDGE_MODEL

_TRUE_TOKEN = re.compile(r"\bTRUE\b")


def _build_prompt(
    question: str, correct_answer: str, incorrect_answer: str, candidate_answer: str, *, correct_first: bool
) -> str:
    """Prompt en anglais (le dataset — questions et réponses de référence —
    est en anglais ; mélanger des instructions françaises à du contenu
    anglais introduit une confusion inutile, surtout pour un petit modèle).

    L'ordre de présentation des deux réponses de référence est randomisé
    (`correct_first`) pour éviter un biais de position — les étiquettes
    CORRECT/INCORRECT, elles, restent toujours correctement attachées à leur
    contenu (le juge doit savoir laquelle est laquelle pour trancher).

    Chaque champ est entouré de guillemets : une référence correcte très
    courte (fréquent dans HaluEval, ex. "country") juxtaposée à une référence
    incorrecte reformulée en phrase complète peut sinon donner l'impression
    d'un champ tronqué ou manquant plutôt que d'une valeur délibérément
    courte."""
    if correct_first:
        references = f'CORRECT reference answer: "{correct_answer}"\nINCORRECT reference answer: "{incorrect_answer}"'
    else:
        references = f'INCORRECT reference answer: "{incorrect_answer}"\nCORRECT reference answer: "{correct_answer}"'

    return textwrap.dedent(f"""\
        You are a factual judge.

        Question: "{question}"

        {references}

        Candidate answer to evaluate: "{candidate_answer}"

        Does the candidate answer match the CORRECT reference answer above
        (not the INCORRECT one)?

        Reply with EXACTLY ONE WORD: TRUE or FALSE. Any reply other than
        exactly TRUE counts as FALSE, including if you are unsure or hesitate.

        Answer:
    """)


def judge_answer(
    question: str,
    correct_answer: str,
    incorrect_answers: list[str],
    candidate_answer: str,
    client: OllamaClient | None = None,
    seed: int | None = None,
) -> Verdict:
    """Juge une réponse candidate (générée par le LLM sous test) en la comparant
    à une réponse correcte et une réponse incorrecte de référence, toutes deux
    tirées du dataset — sert de vérité-terrain de substitution en mode 2.

    `incorrect_answers` : une ou plusieurs variantes connues (cf. TruthfulQA,
    qui en fournit plusieurs par question) — une seule est tirée au hasard et
    présentée au juge, pour ne pas surcharger le prompt.
    """
    client = client or OllamaClient(model=JUDGE_MODEL)
    rng = random.Random(seed)

    incorrect_answer = rng.choice(incorrect_answers)
    correct_first = rng.random() < 0.5

    prompt = _build_prompt(question, correct_answer, incorrect_answer, candidate_answer, correct_first=correct_first)
    raw_response = client.generate(prompt=prompt, temperature=0.0)

    return _parse_verdict(raw_response)


def _parse_verdict(raw_response: str) -> Verdict:
    """Décision binaire assumée : le juge joue le rôle d'une vérité-terrain de
    substitution, pas d'un détecteur — une vérité-terrain incertaine ne sert à
    rien (cf. `NliBaseline.predict`, jamais `NOT_ENOUGH_INFO` non plus, pour
    la même raison). Seul "TRUE" en mot entier donne `SUPPORTED` (évite qu'un
    mot contenant "true" comme sous-chaîne, ex. "untrue", ne matche à tort)
    — tout le reste (FALSE explicite, sortie mal formée, hedge) est
    `CONTRADICTED` par défaut.

    Seule la première ligne de la réponse est examinée : un modèle qui ne
    respecte pas la consigne "un seul mot" peut continuer à générer après sa
    réponse (ex. halluciner un second exercice qui répète le prompt, TRUE
    inclus) — chercher "TRUE" sur tout le texte inverserait alors un FALSE
    réellement répondu en premier mot."""
    first_line = raw_response.strip().upper().split("\n", 1)[0]

    if _TRUE_TOKEN.search(first_line):
        return Verdict.SUPPORTED

    return Verdict.CONTRADICTED
