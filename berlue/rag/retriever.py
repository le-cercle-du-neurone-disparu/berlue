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
    objet, _fin = json.JSONDecoder().raw_decode(texte, debut)
    return objet


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

        logger.info("\n===============================\n")
        logger.info(f"claim : {claim.text}")
        logger.info("\n===============================\n")

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

    def verify_claim(self, claim: Claim) -> RagVerdict:
        # 1. Récupération des preuves (le contexte)
        evidences = self.retrieve(claim, top_k=3)  # Top 3 est souvent suffisant pour un LLM

        logger.info("\n===============================\n")
        logger.info(f"evidences : {evidences}")
        logger.info("\n===============================\n")

        if not evidences:
            return RagVerdict(claim_id=claim.id, verdict=RagJudgment.I_DONT_KNOWN, confidence=0.0, evidence=None)

        # 2. Préparation du contexte (liste de dictionnaires convertie en chaîne formatée)
        # On inclut l'index pour la traçabilité, le texte, et surtout le statut de vérité (label)
        context_list = []
        for i, ev in enumerate(evidences):
            context_list.append({"excerpt_index": i, "text": ev["text"], "fever_label": ev["label"]})

        context_texts = json.dumps(context_list, ensure_ascii=False, indent=2)

        logger.info("\n===============================\n")
        logger.info(f"chunks JSON : \n{context_texts}")
        logger.info("\n===============================\n")

        # 3. Construction du prompt blindé anti-hallucination
        prompt = RAG_SYSTEM_PROMPT.format(claim_text=claim.text, context_texts=context_texts)

        # 4. Appel au LLM (via Ollama)
        try:
            response_text = self.llm_client.generate(prompt, num_predict=NUM_PREDICT_RAG)
            llm_result = _premier_objet_json(response_text)

            logger.info("\n=========== llm_result ===============\n")
            logger.info(f"{llm_result}")
            logger.info("\n===============================\n")

            verdict_str = llm_result.get("verdict", "NOT ENOUGH INFO")

            logger.info("\n=========== verdict_str ===============\n")
            logger.info(f"{verdict_str}")
            logger.info("\n===============================\n")

            confidence = float(llm_result.get("confidence", 0.0))
            used_idx = llm_result.get("used_evidence_index")
            used_idx = used_idx[0] if isinstance(used_idx, list) else used_idx

            # L'index cité est-il exploitable ? `isinstance(True, int)` valant vrai en
            # Python, on écarte explicitement les booléens.
            index_valide = (
                isinstance(used_idx, int) and not isinstance(used_idx, bool) and 0 <= used_idx < len(evidences)
            )

            if index_valide:
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
                if verdict_str in ("FEVER_CONFIRMS", "FEVER_REFUTES"):
                    logger.warning(
                        "⚠️ Verdict %s sans preuve citée sur l'affirmation %s : dégradé en I_DONT_KNOW.",
                        verdict_str,
                        claim.id,
                    )
                    verdict_str = "I_DONT_KNOW"
                    confidence = 0.0

            return RagVerdict(
                claim_id=claim.id,
                verdict=RAG_VERDICT_TO_JUDGMENT.get(verdict_str, RagJudgment.I_DONT_KNOWN),
                confidence=confidence,
                evidence=final_evidence,
            )

        except json.JSONDecodeError as e:
            # Si le JSON est trouvé mais mal formé (ex: virgule manquante)
            logger.warning("⚠️ Erreur de parsing JSON sur l'affirmation %s : %s", claim.id, e)
            logger.warning("Réponse brute du modèle : %s", response_text)
            return RagVerdict(claim_id=claim.id, verdict=RagJudgment.I_DONT_KNOWN, confidence=0.0, evidence=None)
        except Exception as e:
            logger.warning("⚠️ Erreur inattendue sur l'affirmation %s : %s", claim.id, e)
            return RagVerdict(claim_id=claim.id, verdict=RagJudgment.I_DONT_KNOWN, confidence=0.0, evidence=None)

    def verify_claims(self, claims: list[Claim]) -> list[RagVerdict]:
        """Vérifie une liste d'affirmations, une par une."""
        verdicts = []
        for i, claim in enumerate(claims, 1):
            logger.debug("   - Vérification RAG de l'affirmation %d/%d...", i, len(claims))
            verdicts.append(self.verify_claim(claim))
        return verdicts
