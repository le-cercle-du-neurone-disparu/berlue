"""Tests de `berlue.pipeline.extraction` — robustesse face aux sorties du LLM.

Le prompt demande un tableau de chaînes, mais rien ne l'y contraint : ces tests
vérifient qu'une sortie inattendue dégrade proprement au lieu de faire tomber le
run d'évaluation en cours.
"""

from berlue.pipeline.extraction import do_extraction


class FakeLLM:
    def __init__(self, response: str):
        self.response = response

    def generate(self, prompt: str, temperature: float = 0.0, num_predict: int | None = None) -> str:
        return self.response


def _extraire(reponse: str):
    return do_extraction(FakeLLM(reponse), question="Q ?", answer_text="Une réponse.")


def test_tableau_de_chaines_nominal():
    claims = _extraire('["Première affirmation.", "Seconde affirmation."]')
    assert [c.text for c in claims] == ["Première affirmation.", "Seconde affirmation."]


def test_objets_au_lieu_de_chaines_ne_font_pas_planter():
    """Un `[{"claim": "..."}]` levait un AttributeError non attrapé, qui arrêtait
    tout le run."""
    assert _extraire('[{"claim": "Une affirmation."}]') == []


def test_elements_non_textuels_ignores_sans_perdre_les_autres():
    claims = _extraire('["Valide.", 42, null, "Aussi valide."]')
    assert [c.text for c in claims] == ["Valide.", "Aussi valide."]


def test_tableau_recupere_meme_enveloppe_dans_un_objet():
    """Le modèle enveloppe parfois le tableau dans un objet. On récupère le
    tableau plutôt que de tout jeter — rattrapage volontaire."""
    claims = _extraire('{"claims": ["Une affirmation."]}')
    assert [c.text for c in claims] == ["Une affirmation."]


def test_json_malforme():
    assert _extraire('["Une affirmation.",]') == []


def test_aucun_tableau_dans_la_reponse():
    assert _extraire("Je ne sais pas répondre en JSON.") == []


def test_chaines_vides_ecartees():
    claims = _extraire('["", "   ", "Une vraie affirmation."]')
    assert [c.text for c in claims] == ["Une vraie affirmation."]


def test_le_tableau_extrait_n_avale_pas_le_texte_qui_suit():
    """La regex gourmande `\\[.*\\]` allait du premier `[` au dernier `]` de la
    réponse, emportant tout ce qu'il y avait entre les deux."""
    claims = _extraire('["Une affirmation."]\n\nNote : voir aussi [1] et [2].')
    assert [c.text for c in claims] == ["Une affirmation."]


def test_reponse_vide_ne_declenche_aucun_appel():
    assert do_extraction(FakeLLM("[]"), question="Q ?", answer_text="   ") == []


# --- Identifiants reproductibles ---------------------------------------------


def test_les_identifiants_sont_stables_entre_deux_extractions():
    """Un uuid4() rendait un cas impossible à rejouer depuis les logs."""
    a = _extraire('["Première.", "Seconde."]')
    b = _extraire('["Première.", "Seconde."]')
    assert [c.id for c in a] == [c.id for c in b]


def test_deux_affirmations_differentes_ont_des_identifiants_differents():
    claims = _extraire('["Première.", "Seconde."]')
    assert claims[0].id != claims[1].id


def test_une_meme_affirmation_dans_deux_reponses_a_des_identifiants_differents():
    """Le contexte compte : la même phrase extraite de deux réponses distinctes ne
    désigne pas le même objet à vérifier."""
    llm = FakeLLM('["Une affirmation."]')
    a = do_extraction(llm, question="Q ?", answer_text="Première réponse.")
    b = do_extraction(llm, question="Q ?", answer_text="Seconde réponse.")
    assert a[0].id != b[0].id


def test_une_affirmation_repetee_garde_des_identifiants_distincts():
    """Le rang entre dans l'empreinte : deux occurrences identiques restent
    distinguables, sinon la fusion en perdrait une."""
    claims = _extraire('["Doublon.", "Doublon."]')
    assert claims[0].id != claims[1].id
