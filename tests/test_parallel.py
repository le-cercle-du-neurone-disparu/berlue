"""Tests pour `berlue.pipeline.parallel.map_parallele` et la branche SelfCheck
(`berlue.selfcheck.branch.run_selfcheck`)."""

import threading
import time

import pytest

from berlue.core.schemas import Claim, SelfCheckScore
from berlue.pipeline.parallel import map_parallele
from berlue.selfcheck import branch as selfcheck_branch

# --- map_parallele -------------------------------------------------------------


def test_map_parallele_conserve_l_ordre_d_entree():
    """L'ordre est un contrat : les échantillons SelfCheck sont appariés à leur
    température par leur rang, et un run doit rester rejouable à l'identique."""

    def lent_a_l_envers(n: int) -> int:
        # Les premiers éléments sont les plus lents : l'ordre d'achèvement est
        # l'inverse de l'ordre d'entrée.
        time.sleep(0.02 * (5 - n))
        return n * 10

    assert map_parallele(lent_a_l_envers, [0, 1, 2, 3, 4], max_workers=5, prefixe="test") == [0, 10, 20, 30, 40]


def test_map_parallele_repartit_bien_sur_plusieurs_threads():
    threads: set[str] = set()

    def _tache(n: int) -> int:
        threads.add(threading.current_thread().name)
        time.sleep(0.05)
        return n

    debut = time.monotonic()
    map_parallele(_tache, list(range(4)), max_workers=4, prefixe="test")
    duree = time.monotonic() - debut

    assert len(threads) > 1
    assert duree < 0.15, f"les tâches se sont enchaînées ({duree:.2f}s pour 4 x 0.05s)"


def test_map_parallele_sur_une_liste_vide_n_appelle_rien():
    appels = []
    assert map_parallele(appels.append, [], max_workers=4, prefixe="test") == []
    assert appels == []


def test_map_parallele_a_un_seul_worker_reste_sequentiel():
    """Mode de repli pour déboguer : aucun pool créé, tout dans le thread courant."""
    principal = threading.current_thread().name
    threads = map_parallele(lambda _: threading.current_thread().name, [1, 2, 3], max_workers=1, prefixe="test")
    assert threads == [principal, principal, principal]


def test_map_parallele_remonte_l_exception_de_la_tache():
    """Un `RagPanne` levé sur une affirmation doit invalider la question entière,
    donc remonter à l'appelant plutôt que d'être avalé par le pool."""

    def _echoue_sur_2(n: int) -> int:
        if n == 2:
            raise ValueError("échec sur 2")
        return n

    with pytest.raises(ValueError, match="échec sur 2"):
        map_parallele(_echoue_sur_2, [1, 2, 3], max_workers=3, prefixe="test")


# --- run_selfcheck -------------------------------------------------------------


class ClientEchantillons:
    def __init__(self, samples: list[str]):
        self.samples = samples
        self.appels: list[dict] = []

    def generate_many(self, prompt, k, temperature_min, temperature_max, num_predict=None, max_workers=1):
        self.appels.append({"k": k, "max_workers": max_workers})
        return self.samples


def test_run_selfcheck_score_chaque_affirmation(monkeypatch):
    monkeypatch.setattr(
        selfcheck_branch,
        "compute_divergence",
        lambda claim, samples: SelfCheckScore(claim_id=claim.id, divergence_score=0.2, confidence=0.8),
    )
    claims = [Claim(id="c1", text="A.", source_answer="..."), Claim(id="c2", text="B.", source_answer="...")]
    client = ClientEchantillons(["éch. 1", "éch. 2"])

    outcome = selfcheck_branch.run_selfcheck("Q ?", claims, client, k=2)

    assert outcome.samples == ["éch. 1", "éch. 2"]
    assert [s.claim_id for s in outcome.scores] == ["c1", "c2"]
    assert all(s.divergence_score == 0.2 for s in outcome.scores)


def test_run_selfcheck_score_les_affirmations_en_parallele(monkeypatch):
    threads: set[str] = set()

    def _score_lent(claim, samples):
        threads.add(threading.current_thread().name)
        time.sleep(0.05)
        return SelfCheckScore(claim_id=claim.id, divergence_score=0.1, confidence=0.9)

    monkeypatch.setattr(selfcheck_branch, "compute_divergence", _score_lent)
    claims = [Claim(id=f"c{i}", text=f"{i}.", source_answer="...") for i in range(4)]

    outcome = selfcheck_branch.run_selfcheck("Q ?", claims, ClientEchantillons(["éch."]), k=1, score_workers=4)

    assert [s.claim_id for s in outcome.scores] == ["c0", "c1", "c2", "c3"]
    assert len(threads) > 1, "les scores NLI ne se sont pas répartis sur plusieurs threads"


def test_run_selfcheck_echantillonne_meme_sans_affirmation():
    """Les échantillons décrivent la stabilité du modèle sur la QUESTION, pas sur
    une affirmation : l'API les affiche même quand l'extraction n'a rien rendu."""
    client = ClientEchantillons(["éch. 1"])

    outcome = selfcheck_branch.run_selfcheck("Q ?", [], client, k=1)

    assert outcome.samples == ["éch. 1"]
    assert outcome.scores == []
