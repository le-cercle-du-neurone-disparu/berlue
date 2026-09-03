"""Vérification d'une affirmation par recherche de preuves dans l'index FEVER (RAG inversé)."""

import json
import logging
import pickle
from pathlib import Path

import faiss
from sentence_transformers import SentenceTransformer

from berlue.core.schemas import Claim, Evidence, RagJudgment, RagVerdict
from berlue.params import NUM_PREDICT_RAG, RAG_EMBEDDING_MODEL, RAG_SYSTEM_PROMPT, RAG_VECTOR_DB_PATH

logger = logging.getLogger(__name__)

# Verdict rendu par le LLM du RAG (str du prompt) -> RagJudgment, le contrat interne.
# Ce ne sont PAS les labels FEVER du dataset : ceux-ci ("SUPPORTS"/"REFUTES") décrivent
# les extraits fournis au prompt, pas la décision. "NOT ENOUGH INFO" n'est plus produit
# par prompts/rag.py mais reste accepté, d'anciennes réponses pouvant le contenir.
RAG_VERDICT_TO_JUDGMENT = {
    "FEVER_CONFIRMS": RagJudgment.FEVER_CONFIRMS,
    "FEVER_REFUTES": RagJudgment.FEVER_REFUTES,
    "LIKELY_TRUE": RagJudgment.LIKELY_TRUE,
    "LIKELY_FALSE": RagJudgment.LIKELY_FALSE,
    "NOT ENOUGH INFO": RagJudgment.I_DONT_KNOWN,
    "I_DONT_KNOW": RagJudgment.I_DONT_KNOWN,
}


def _source_de(evidence: dict) -> str:
    """Titre de la page Wikipédia d'un extrait FEVER, ou "FEVER" à défaut.

    `evidence_url` est imbriqué sur quatre niveaux et sa forme varie selon les
    entrées : une indexation directe `[0][0][2]` levait une IndexError qui faisait
    perdre le verdict entier.
    """
    try:
        return evidence["evidence_url"][0][0][2]
    except KeyError, IndexError, TypeError:
        return "FEVER"


class RagPanne(RuntimeError):
    """Le RAG n'a pas pu se prononcer pour une raison TECHNIQUE.

    À distinguer d'un `I_DONT_KNOW`, qui est un jugement : le modèle a répondu et
    dit ne pas savoir. Ici il n'a pas répondu, ou sa réponse est inexploitable.
    Les confondre faisait passer une panne pour une ignorance, et le pipeline
    concluait « incertain » là où il aurait dû annoncer une erreur — observé sur
    trois affirmations dont les verdicts, corrects, avaient été perdus au parsing.
    """


def _premier_objet_json(texte: str) -> dict:
    r"""Décode le premier objet JSON complet de `texte` et ignore ce qui suit.

    `re.search(r"\{.*\}", ..., DOTALL)` allait du premier `{` au dernier `}` :
    dès qu'un modèle ajoutait un second objet ou un commentaire après sa réponse,
    la capture contenait deux valeurs et `json.loads` échouait sur « Extra data »,
    perdant un verdict pourtant bien formé. `raw_decode` s'arrête à la fin de la
    première valeur valide, quel que soit ce qui traîne derrière.
    """
    debut = texte.find("{")
    if debut == -1:
        return {}
    try:
        objet, _fin = json.JSONDecoder().raw_decode(texte, debut)
    except json.JSONDecodeError:
        objet = _reparer_objet_tronque(texte[debut:])
        if objet is None:
            raise
    return objet


def _reparer_objet_tronque(texte: str) -> dict | None:
    """Récupère un objet JSON coupé avant sa fin, ou `None` si c'est irrécupérable.

    Une génération peut s'arrêter au milieu — plafond de tokens atteint, fenêtre
    de contexte saturée. La réponse porte alors un verdict complet mais aucune
    accolade fermante, et tout était jeté : un `FEVER_REFUTES` à 0.99 était perdu
    aussi sûrement qu'une réponse absurde, et le pipeline concluait « pas assez
    d'infos » là où le modèle avait tranché.

    On raccourcit donc depuis la fin jusqu'à obtenir un objet décodable, puis on
    referme. Rien n'est inventé, mais un nombre coupé peut être relu plus court —
    `0.95` tronqué après le `9` se lit `0.9`. L'imprécision est bornée et vaut
    mieux que de perdre le verdict entier ; une chaîne coupée, elle, donne un
    verdict que le pipeline ne reconnaîtra pas et traitera comme une ignorance.
    """
    decodeur = json.JSONDecoder()
    # On raccourcit depuis la fin jusqu'à ce qu'une fermeture rende le texte
    # décodable. La virgule finale éventuelle est retirée avec le reste.
    for fin in range(len(texte), 0, -1):
        fragment = texte[:fin].rstrip().rstrip(",")
        if not fragment:
            break
        try:
            objet, _ = decodeur.raw_decode(fragment + "}")
        except json.JSONDecodeError:
            continue
        return objet if isinstance(objet, dict) else None
    return None


def _trace(claim, evidences: list[dict], meta: dict, resultat: dict, verdict_final: str) -> dict:
    """Détail d'une vérification, sous forme de données.

    Sert deux usages à partir d'une seule construction : la trace journalisée et
    le champ `debug` de l'API. Les dupliquer les aurait fait diverger.
    """
    return {
        "claim_id": claim.id,
        "claim_text": claim.text,
        "evidences": [
            {"index": i, "distance": ev["distance"], "label": ev["label"], "text": ev["text"]}
            for i, ev in enumerate(evidences)
        ],
        "generation": dict(meta),
        "verdict": verdict_final,
        "confidence": resultat.get("confidence"),
        "used_evidence_index": resultat.get("used_evidence_index"),
        "reasoning": resultat.get("reasoning"),
    }


def bloc_trace(detail: dict) -> str:
    """Rend une vérification en texte lisible, à partir des données de `_trace`.

    Publique parce que l'API s'en sert pour son champ `debug` : le journal du
    serveur et le retour HTTP doivent montrer exactement la même chose, sinon
    on diagnostique sur une version et on corrige d'après l'autre.
    """
    lignes = [
        f"┌─ RAG · affirmation {detail['claim_id']}",
        f"│ affirmation  : {detail['claim_text']}",
        "│ extraits     :" if detail["evidences"] else "│ extraits     : aucun",
    ]
    for ev in detail["evidences"]:
        lignes.append(f"│   [{ev['index']}] d={ev['distance']:.3f} {ev['label']:<9} {ev['text']}")
    meta = detail.get("generation") or {}
    if meta:
        lignes.append(
            f"│ génération   : {meta.get('modele')} · {meta.get('secondes')}s · "
            f"{meta.get('tokens')} tokens · {meta.get('caracteres')} car. · fin={meta.get('done_reason')}"
        )
    preuve = detail.get("used_evidence_index")
    lignes.append(
        f"│ verdict RAG  : {detail.get('verdict')} · confiance {detail.get('confidence')} · "
        f"preuve {'aucune' if preuve is None else f'[{preuve}]'}"
    )
    if detail.get("selfcheck_divergence") is not None:
        lignes.append(f"│ SelfCheck    : divergence {detail['selfcheck_divergence']:.2f}")
    if detail.get("fusion_verdict"):
        lignes.append(
            f"│ FUSION       : {detail['fusion_verdict'].upper()} · "
            f"confiance {detail.get('fusion_confidence')} · {detail.get('fusion_fondement')}"
        )
        if detail.get("fusion_explanation"):
            lignes.append(f"│                {detail['fusion_explanation']}")
    raisonnement = str(detail.get("reasoning") or "").strip()
    if raisonnement:
        lignes.append(f"│ raisonnement : {raisonnement}")
    lignes.append("└─")
    return "\n".join(lignes)


class RagRetriever:
    def __init__(
        self,
        llm_client,  # Injection de ton client Ollama
        index_path: str = RAG_VECTOR_DB_PATH,
        embedding_model: str = RAG_EMBEDDING_MODEL,
    ):
        self.llm_client = llm_client
        self.index_path = Path(index_path)

        # 1. Chargement de l'index FAISS
        self.index = faiss.read_index(str(self.index_path / "index.faiss"))

        # 2. Chargement des métadonnées
        with open(self.index_path / "metadata.pkl", "rb") as f:
            self.metadata = pickle.load(f)

        # 3. Chargement du modèle d'embedding
        self.model = SentenceTransformer(embedding_model)

        logger.info("✅ Index chargé : %d vecteurs", self.index.ntotal)
        logger.info("✅ Métadonnées : %d exemples", len(self.metadata["claims"]))

    def retrieve(self, claim: Claim, top_k: int = 5) -> list[dict]:
        """Recherche les `top_k` passages les plus proches de l'affirmation."""
        # ## Renvoie des dicts bruts (text/label/distance/evidence_url), pas des Evidence :
        # ## verify_claim (seul appelant, cf. grep) a besoin du label et de la distance de
        # ## chaque candidat pour son vote majoritaire, des champs que Evidence (le contrat de
        # ## core.schemas) n'a pas. Seule la preuve finalement citée devient une vraie Evidence.
        # 1. Génération l'embedding de l'affirmation
        claim_embedding = self.model.encode(claim.text, convert_to_numpy=True).reshape(1, -1)

        # 2. Recherche dans l'index
        distances, indices = self.index.search(claim_embedding, top_k)

        # 3. Construction les résultats
        evidences = []
        for i in range(len(distances[0])):
            dist = distances[0][i]
            idx = indices[0][i]
            # FAISS renvoie -1 pour un voisin manquant : sans la borne basse, `-1`
            # passait le test et injectait le DERNIER document du corpus comme preuve.
            if 0 <= idx < len(self.metadata["claims"]):
                evidences.append(
                    {
                        "text": self.metadata["claims"][idx],
                        "label": self.metadata["labels"][idx],
                        "distance": float(dist),
                        "evidence_url": self.metadata["evidence_urls"][idx],
                    }
                )
        return evidences

    def verify_claim(self, claim: Claim, traces: list[dict] | None = None) -> RagVerdict:
        # 1. Récupération des preuves (le contexte)
        evidences = self.retrieve(claim, top_k=3)  # Top 3 est souvent suffisant pour un LLM

        if not evidences:
            # Ce n'est pas une panne : la recherche a fonctionné et n'a rien trouvé.
            # Le RAG dit qu'il ne sait pas, ce qui est un jugement recevable.
            return RagVerdict(claim_id=claim.id, verdict=RagJudgment.I_DONT_KNOWN, confidence=0.0, evidence=None)

        # 2. Préparation du contexte (liste de dictionnaires convertie en chaîne formatée)
        # On inclut l'index pour la traçabilité, le texte, et surtout le statut de vérité (label)
        context_list = []
        for i, ev in enumerate(evidences):
            context_list.append({"excerpt_index": i, "text": ev["text"], "fever_label": ev["label"]})

        context_texts = json.dumps(context_list, ensure_ascii=False, indent=2)

        # 3. Construction du prompt blindé anti-hallucination
        prompt = RAG_SYSTEM_PROMPT.format(claim_text=claim.text, context_texts=context_texts)

        # 4. Appel au LLM (via Ollama)
        try:
            response_text = self.llm_client.generate(prompt, num_predict=NUM_PREDICT_RAG)
            llm_result = _premier_objet_json(response_text)

            verdict_str = llm_result.get("verdict", "NOT ENOUGH INFO")

            confidence = float(llm_result.get("confidence", 0.0))
            used_idx = llm_result.get("used_evidence_index")
            used_idx = used_idx[0] if isinstance(used_idx, list) else used_idx

            # L'index cité est-il exploitable ? `isinstance(True, int)` valant vrai en
            # Python, on écarte explicitement les booléens.
            index_valide = (
                isinstance(used_idx, int) and not isinstance(used_idx, bool) and 0 <= used_idx < len(evidences)
            )

            # Une preuve n'est attachée qu'à un verdict qui en revendique une.
            # LIKELY_TRUE, LIKELY_FALSE et I_DONT_KNOW affirment tous que la base
            # manque d'information : leur joindre un extrait le ferait afficher
            # comme « Preuve » par l'API, qui étiquette toute preuve présente
            # FEVER_corpus — alors que le verdict dit ne pas s'appuyer dessus. Le
            # prompt impose déjà `used_evidence_index: null` dans ces cas, mais le
            # modèle ne s'y tient pas toujours.
            verdict_avec_preuve = verdict_str in ("FEVER_CONFIRMS", "FEVER_REFUTES")

            if index_valide and verdict_avec_preuve:
                # LA preuve précise que le LLM a choisie.
                chosen_ev = evidences[used_idx]
                final_evidence = Evidence(
                    text=chosen_ev["text"],
                    source=_source_de(chosen_ev),
                    # La distance FAISS, pas la confiance du LLM : le champ est
                    # documenté comme un score de similarité.
                    similarity_score=chosen_ev["distance"],
                )
            else:
                # Pas de preuve citée : on n'en renvoie aucune. Le verdict, lui, survit
                # — le prompt impose justement `used_evidence_index: null` pour
                # LIKELY_TRUE / LIKELY_FALSE / I_DONT_KNOW, qui sont des jugements
                # valides sans preuve en base. Seuls FEVER_CONFIRMS et FEVER_REFUTES
                # exigent une preuve citée : sans elle, ils ne prouvent rien.
                final_evidence = None
                if verdict_avec_preuve:
                    logger.warning(
                        "⚠️ Verdict %s sans preuve citée sur l'affirmation %s : dégradé en I_DONT_KNOW.",
                        verdict_str,
                        claim.id,
                    )
                    verdict_str = "I_DONT_KNOW"
                    confidence = 0.0

            meta = getattr(self.llm_client, "derniere_generation", {})
            detail = _trace(claim, evidences, meta, {**llm_result, "confidence": confidence}, verdict_str)
            if traces is not None:
                traces.append(detail)
            logger.info("%s", bloc_trace(detail))

            return RagVerdict(
                claim_id=claim.id,
                verdict=RAG_VERDICT_TO_JUDGMENT.get(verdict_str, RagJudgment.I_DONT_KNOWN),
                confidence=confidence,
                evidence=final_evidence,
            )

        except json.JSONDecodeError as e:
            meta = getattr(self.llm_client, "derniere_generation", {})
            logger.warning(
                "┌─ RAG · affirmation %s — RÉPONSE ILLISIBLE\n"
                "│ erreur       : %s\n"
                "│ génération   : %s · %ss · %s tokens · %s car. · fin=%s\n"
                "│ réponse brute:\n%s\n└─",
                claim.id,
                e,
                meta.get("modele"),
                meta.get("secondes"),
                meta.get("tokens"),
                meta.get("caracteres"),
                meta.get("done_reason"),
                response_text,
            )
            raise RagPanne(f"réponse du RAG inexploitable sur l'affirmation {claim.id}") from e
        except RagPanne:
            raise
        except Exception as e:
            logger.warning("⚠️ Erreur inattendue sur l'affirmation %s : %s", claim.id, e)
            raise RagPanne(f"échec du RAG sur l'affirmation {claim.id} : {e}") from e

    def verify_claims(self, claims: list[Claim]) -> list[RagVerdict]:
        """Vérifie une liste d'affirmations, une par une."""
        verdicts = []
        for i, claim in enumerate(claims, 1):
            logger.debug("   - Vérification RAG de l'affirmation %d/%d...", i, len(claims))
            verdicts.append(self.verify_claim(claim))
        return verdicts
