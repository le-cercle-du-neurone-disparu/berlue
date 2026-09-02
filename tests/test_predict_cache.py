"""Clé et règle d'usage du cache de prédiction — `berlue.api.predict_cache`.

C'est la partie où une erreur ne casse rien visiblement : elle sert
silencieusement un résultat calculé par un modèle plus faible que celui
demandé. D'où une couverture serrée.
"""

import pytest

from berlue.api.predict_cache import normaliser_question, satisfait, taille_modele


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("  Quelle est la capitale ?  ", "quelle est la capitale ?"),
        ("QUELLE EST LA CAPITALE ?", "quelle est la capitale ?"),
        ("quelle est la capitale ?", "quelle est la capitale ?"),
        ("", ""),
        ("\n\tUne question\n", "une question"),
    ],
)
def test_normalisation(brut, attendu):
    assert normaliser_question(brut) == attendu


def test_la_normalisation_ne_touche_ni_ponctuation_ni_accents():
    """Choix documenté : ces deux formulations restent des entrées distinctes.
    Le test existe pour que le jour où on change d'avis, ce soit délibéré."""
    assert normaliser_question("la France?") != normaliser_question("la France ?")
    assert normaliser_question("la france") != normaliser_question("la françe")


@pytest.mark.parametrize(
    ("tag", "attendu"),
    [
        ("llama3.2:3b", 3.0),
        ("llama3.1:8b", 8.0),
        ("phi3:14b", 14.0),
        ("gemma3:27b", 27.0),
        ("qwen2.5:0.5b", 0.5),
        ("llama3.1:8b-instruct-q4_0", 8.0),
        # Le numéro de version ne doit pas être pris pour une taille.
        ("phi3.5:latest", None),
        ("mon-modele:custom", None),
    ],
)
def test_taille_modele(tag, attendu):
    assert taille_modele(tag) == attendu


def test_la_version_du_modele_n_est_pas_sa_taille():
    """`llama3.2:3b` vaut 3 milliards de paramètres, pas 3.2 : la version
    précède les deux-points, la taille les suit."""
    assert taille_modele("llama3.2:3b") == 3.0


# --- La règle d'usage : (générateur, extraction, RAG) ---

TRIPLET_CACHE = ("phi3:14b", "phi3:14b", "phi3:14b")


@pytest.mark.parametrize(
    ("demandes", "attendu", "pourquoi"),
    [
        (("phi3:14b", "phi3:14b", "phi3:14b"), True, "identiques"),
        (("llama3.2:3b", "llama3.1:8b", "llama3.1:8b"), True, "tous plus petits"),
        (("gemma3:27b", "phi3:14b", "phi3:14b"), False, "générateur plus gros"),
        (("phi3:14b", "gemma3:27b", "phi3:14b"), False, "extraction plus grosse"),
        (("phi3:14b", "phi3:14b", "gemma3:27b"), False, "RAG plus gros"),
        (("llama3.2:3b", "gemma3:27b", "llama3.1:8b"), False, "un seul rôle plus gros suffit à refuser"),
    ],
)
def test_regle_de_taille(demandes, attendu, pourquoi):
    assert satisfait(demandes, TRIPLET_CACHE) is attendu, pourquoi


def test_la_famille_du_modele_est_ignoree():
    """Décision produit : seule la taille compte côté pipeline. Un verdict de
    Mistral sert une demande de Gemma à taille égale — ce qui serait faux côté
    évaluation, où le modèle exact fait partie du scope."""
    assert satisfait(("gemma:7b", "gemma:7b", "gemma:7b"), ("mistral:7b", "mistral:7b", "mistral:7b"))


def test_deux_tags_identiques_conviennent_meme_sans_taille_lisible():
    """Le cas courant ne doit dépendre d'aucune analyse du nom."""
    inconnu = ("phi3.5:latest", "phi3.5:latest", "phi3.5:latest")
    assert satisfait(inconnu, inconnu)


def test_une_taille_illisible_interdit_la_comparaison():
    """Servir une entrée dont on ne sait pas si elle vient d'un modèle plus
    faible reviendrait à dégrader le résultat sans le dire."""
    assert not satisfait(("phi3.5:latest", "phi3:14b", "phi3:14b"), TRIPLET_CACHE)
    assert not satisfait(("llama3.2:3b", "phi3:14b", "phi3:14b"), ("phi3.5:latest", "phi3:14b", "phi3:14b"))


def test_roles_non_apparies():
    with pytest.raises(ValueError, match="rôles non appariés"):
        satisfait(("phi3:14b",), TRIPLET_CACHE)


# ==============================================================================
# PUBLICATION DU CACHE LOCAL VERS GCP
# ==============================================================================
# La règle de collision est le point sensible : une entrée locale ne remplace la
# distante que si ses modèles sont au moins aussi gros. Un poste de
# développement travaille souvent avec de petits modèles, faute de GPU —
# publier sans condition dégraderait le cache de production.

from unittest.mock import patch  # noqa: E402

import berlue.api.predict_cache_cli as cli  # noqa: E402
from berlue.evaluation.result_store import LocalResultStore  # noqa: E402

PETIT = ("llama3.2:3b", "llama3.2:3b", "llama3.2:3b")
GROS = ("phi3:14b", "phi3:14b", "phi3:14b")


class _Args:
    def __init__(self, question=None, force=False):
        self.question = question
        self.force = force


def _deux_magasins(tmp_path):
    local = LocalResultStore(db_path=str(tmp_path / "local.db"))
    distant = LocalResultStore(db_path=str(tmp_path / "distant.db"))

    def faux_store(target="local"):
        return local if target == "local" else distant

    return local, distant, faux_store


def _publier(faux_store, args=None):
    with patch.object(cli, "get_result_store", faux_store):
        return cli._publier(args or _Args())


def test_publication_ajoute_une_entree_absente(tmp_path):
    local, distant, faux = _deux_magasins(tmp_path)
    local.put_predict_cache("Q", 0.0, *PETIT, {"claims": ["local"]})
    assert _publier(faux) == 0
    assert distant.get_predict_cache("Q", 0.0)["payload"] == {"claims": ["local"]}


def test_publication_conserve_une_entree_distante_meilleure(tmp_path):
    """Locale calculée par un 3b, distante par un 14b : la distante gagne."""
    local, distant, faux = _deux_magasins(tmp_path)
    local.put_predict_cache("Q", 0.0, *PETIT, {"claims": ["local"]})
    distant.put_predict_cache("Q", 0.0, *GROS, {"claims": ["distant"]})
    _publier(faux)
    assert distant.get_predict_cache("Q", 0.0)["payload"] == {"claims": ["distant"]}


def test_publication_remplace_quand_la_locale_vaut_mieux(tmp_path):
    local, distant, faux = _deux_magasins(tmp_path)
    local.put_predict_cache("Q", 0.0, *GROS, {"claims": ["local"]})
    distant.put_predict_cache("Q", 0.0, *PETIT, {"claims": ["distant"]})
    _publier(faux)
    assert distant.get_predict_cache("Q", 0.0)["payload"] == {"claims": ["local"]}


def test_force_ecrase_meme_une_entree_distante_meilleure(tmp_path):
    """Pour publier délibérément un résultat recalculé après un changement de
    prompt, que la règle de taille refuserait."""
    local, distant, faux = _deux_magasins(tmp_path)
    local.put_predict_cache("Q", 0.0, *PETIT, {"claims": ["local"]})
    distant.put_predict_cache("Q", 0.0, *GROS, {"claims": ["distant"]})
    _publier(faux, _Args(force=True))
    assert distant.get_predict_cache("Q", 0.0)["payload"] == {"claims": ["local"]}


def test_publication_filtree_sur_une_question(tmp_path):
    local, distant, faux = _deux_magasins(tmp_path)
    local.put_predict_cache("Gardée", 0.0, *PETIT, {"claims": []})
    local.put_predict_cache("Ignorée", 0.0, *PETIT, {"claims": []})
    _publier(faux, _Args(question="  GARDÉE  "))
    assert distant.get_predict_cache("Gardée", 0.0) is not None
    assert distant.get_predict_cache("Ignorée", 0.0) is None


def test_publication_publie_chaque_temperature(tmp_path):
    """Les températures sont des entrées distinctes : aucune ne doit être
    perdue au passage."""
    local, distant, faux = _deux_magasins(tmp_path)
    local.put_predict_cache("Q", 0.0, *PETIT, {"claims": ["froid"]})
    local.put_predict_cache("Q", 0.7, *PETIT, {"claims": ["chaud"]})
    _publier(faux)
    assert distant.get_predict_cache("Q", 0.0)["payload"] == {"claims": ["froid"]}
    assert distant.get_predict_cache("Q", 0.7)["payload"] == {"claims": ["chaud"]}


def test_publication_sans_rien_a_publier(tmp_path):
    _, _, faux = _deux_magasins(tmp_path)
    assert _publier(faux) == 0
