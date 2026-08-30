"""Tests pour `berlue.evaluation.judge` — client LLM factice, aucun appel
réseau/Ollama requis."""

from berlue.core.schemas import Verdict
from berlue.evaluation.judge import _build_prompt, _parse_verdict, judge_answer


class FakeClient:
    """Renvoie toujours la même réponse brute, et garde le dernier prompt reçu
    pour inspection."""

    def __init__(self, response: str):
        self.response = response
        self.last_prompt: str | None = None

    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        self.last_prompt = prompt
        return self.response


def test_parse_verdict_true():
    assert _parse_verdict("TRUE") == Verdict.SUPPORTED


def test_parse_verdict_false():
    assert _parse_verdict("FALSE") == Verdict.CONTRADICTED


def test_parse_verdict_unparseable_defaults_to_contradicted():
    """Décision binaire assumée : le juge sert de vérité-terrain, pas de
    détecteur — pas de sortie 'incertain' possible, tout ce qui n'est pas
    clairement TRUE est FALSE par défaut."""
    assert _parse_verdict("blabla, I don't know") == Verdict.CONTRADICTED


def test_parse_verdict_does_not_match_substring_inside_another_word():
    """'untrue' contient 'true' comme sous-chaîne — ne doit pas déclencher un
    faux positif sur TRUE (mot entier requis)."""
    assert _parse_verdict("That statement is untrue.") == Verdict.CONTRADICTED


def test_parse_verdict_ignores_true_appearing_after_a_runaway_continuation():
    """Cas réel observé avec phi3:14b : le modèle répond FALSE (correct) puis
    ignore la consigne "un seul mot" et continue à halluciner un second
    exercice qui répète le prompt — "TRUE" y réapparaît. Seule la première
    ligne compte, sinon ce FALSE bien répondu serait inversé en SUPPORTED."""
    runaway = "FALSE\n\n**Instruction 2 (More Difficult):**\n\nReply with EXACTLY ONE WORD: TRUE or FALSE.\n"
    assert _parse_verdict(runaway) == Verdict.CONTRADICTED


def test_judge_answer_returns_verdict_from_client_response():
    client = FakeClient("TRUE")
    verdict = judge_answer("Q?", "correct answer", ["wrong answer"], "candidate", client=client)
    assert verdict == Verdict.SUPPORTED


def test_judge_answer_picks_one_incorrect_answer_among_several():
    """Avec plusieurs variantes incorrectes (cf. TruthfulQA), une seule doit
    être injectée dans le prompt, choisie via le `seed` fourni."""
    client = FakeClient("FALSE")
    judge_answer("Q?", "correct answer", ["wrong A", "wrong B", "wrong C"], "candidate", client=client, seed=0)

    incorrect_variants_in_prompt = sum(v in client.last_prompt for v in ["wrong A", "wrong B", "wrong C"])
    assert incorrect_variants_in_prompt == 1


def test_build_prompt_order_is_randomized_by_correct_first():
    """Les deux réponses de référence gardent leurs étiquettes CORRECT/
    INCORRECT correctement attachées à leur contenu quel que soit l'ordre —
    seul l'ordre de présentation change, pas l'association contenu/étiquette."""
    true_first = _build_prompt("Q", "TXT_CORRECT", "TXT_WRONG", "CAND", correct_first=True)
    false_first = _build_prompt("Q", "TXT_CORRECT", "TXT_WRONG", "CAND", correct_first=False)

    assert true_first != false_first
    assert true_first.index("TXT_CORRECT") < true_first.index("TXT_WRONG")
    assert false_first.index("TXT_WRONG") < false_first.index("TXT_CORRECT")

    # Les étiquettes restent correctes dans les deux cas, seul l'ordre change
    assert 'CORRECT reference answer: "TXT_CORRECT"' in true_first
    assert 'INCORRECT reference answer: "TXT_WRONG"' in true_first
    assert 'CORRECT reference answer: "TXT_CORRECT"' in false_first
    assert 'INCORRECT reference answer: "TXT_WRONG"' in false_first
