"""Vérification d'une affirmation par recherche de preuves dans l'index FEVER (RAG inversé)."""

import json
import logging
import pickle
import re
from pathlib import Path

import faiss
from sentence_transformers import SentenceTransformer

from berlue.core.schemas import Claim, Evidence, RagVerdict, Verdict, RagJudgment
from berlue.params import RAG_EMBEDDING_MODEL, RAG_SYSTEM_PROMPT, RAG_VECTOR_DB_PATH

logger = logging.getLogger(__name__)

# Labels FEVER (str du dataset) -> Verdict (enum du contrat interne berlue.core.schemas).
# "NOT ENOUGH INFO" n'apparaît jamais parmi les labels indexés (indexer.build_index ne
# garde que SUPPORTS/REFUTES) ; gardé ici pour les retours anticipés de verify_claim.
FEVER_LABEL_TO_VERDICT = {
    "FEVER_CONFIRMS": RagJudgment.FEVER_CONFIRMS,
    "FEVER_REFUTES": RagJudgment.FEVER_REFUTES,
    "LIKELY_TRUE": RagJudgment.LIKELY_TRUE,
    "LIKELY_FALSE": RagJudgment.LIKELY_FALSE,
    "NOT ENOUGH INFO": RagJudgment.I_DONT_KNOWN,
    "I_DONT_KNOW": RagJudgment.I_DONT_KNOWN,
}


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
            if idx < len(self.metadata["claims"]):
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
            return RagVerdict(claim_id=claim.id, verdict=Verdict.NOT_ENOUGH_INFO, confidence=0.0, evidence=None)

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
            response_text = self.llm_client.generate(prompt)
            match = re.search(r"\{.*\}", response_text, re.DOTALL)
            clean_json_str = match.group(0) if match else "{}"
            llm_result = json.loads(clean_json_str)

            logger.info("\n=========== llm_result ===============\n")
            logger.info(f"{llm_result}")
            logger.info("\n===============================\n")

            verdict_str = llm_result.get("verdict", "NOT ENOUGH INFO")

            logger.info("\n=========== verdict_str ===============\n")
            logger.info(f"{verdict_str}")
            logger.info("\n===============================\n")

            confidence = float(llm_result.get("confidence", 0.0))
            used_idx = llm_result.get("used_evidence_index")

            # Si le LLM n'a pas assez d'infos, on ne renvoie AUCUNE preuve
            if (
                verdict_str == "NOT ENOUGH INFO"
                or used_idx is None
                or not isinstance(used_idx, int)
                or used_idx >= len(evidences)
            ):
                final_evidence = None
                verdict_str = "NOT ENOUGH INFO"
                confidence = 0.0
            else:
                # On récupère LA preuve spécifique que le LLM a choisi
                chosen_ev = evidences[used_idx]
                final_evidence = Evidence(
                    text=chosen_ev["text"],
                    source=chosen_ev["evidence_url"][0][0][2] if chosen_ev.get("evidence_url") else "FEVER",
                    similarity_score=confidence,
                )

            return RagVerdict(
                claim_id=claim.id,
                verdict=FEVER_LABEL_TO_VERDICT.get(verdict_str, RagJudgment.I_DONT_KNOWN),
                confidence=confidence,
                evidence=final_evidence,
            )

        except json.JSONDecodeError as e:
            # Si le JSON est trouvé mais mal formé (ex: virgule manquante)
            logger.warning("⚠️ Erreur de parsing JSON sur l'affirmation %s : %s", claim.id, e)
            logger.warning("Texte problématique : %s", clean_json_str)
            return RagVerdict(claim_id=claim.id, verdict=Verdict.NOT_ENOUGH_INFO, confidence=0.0, evidence=None)
        except Exception as e:
            logger.warning("⚠️ Erreur inattendue sur l'affirmation %s : %s", claim.id, e)
            return RagVerdict(claim_id=claim.id, verdict=Verdict.NOT_ENOUGH_INFO, confidence=0.0, evidence=None)

    def verify_claims(self, claims: list[Claim]) -> list[RagVerdict]:
        """Vérifie une liste d'affirmations, une par une."""
        verdicts = []
        for i, claim in enumerate(claims, 1):
            logger.debug("   - Vérification RAG de l'affirmation %d/%d...", i, len(claims))
            verdicts.append(self.verify_claim(claim))
        return verdicts
