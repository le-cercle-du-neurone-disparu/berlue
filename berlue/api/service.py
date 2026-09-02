import logging

from berlue.api.predict_cache import satisfait
from berlue.api.schemas import STATUS_BY_VERDICT, ClaimResult, PredictInput, PredictOrigin, PredictOutput
from berlue.llm.client import OllamaClient
from berlue.params import EXTRACT_MODEL, RAG_MODEL
from berlue.pipeline.hurlu_berlu import HurluBerlu
from berlue.rag.retriever import bloc_trace

logger = logging.getLogger(__name__)


class BerlueService:
    def predict(self, payload: PredictInput, retriever, extractor, store=None) -> PredictOutput:
        """Exécute le pipeline et retourne une réponse typée Pydantic.

        `store` active le cache de prédiction. Absent, le pipeline tourne
        toujours — un appel direct ou un test n'a pas à fournir de magasin.

        `payload.ignore_cache` saute la LECTURE du cache, jamais son écriture :
        le résultat recalculé remplace l'entrée existante. Un paramètre qui se
        contenterait de contourner le cache laisserait la vieille réponse en
        place, et le prochain appelant la recevrait — l'inverse de ce qu'on
        cherche après un changement de prompt.
        """
        modeles = (payload.llm.name, EXTRACT_MODEL, RAG_MODEL)

        if store is not None and not payload.ignore_cache:
            en_cache = self._lire_cache(store, payload, modeles)
            if en_cache is not None:
                return en_cache
        elif payload.ignore_cache:
            logger.info("🔄 Cache ignoré à la demande — le pipeline va tourner et remplacer l'entrée.")

        # 1. Création du client cible via le payload
        target_llm = OllamaClient(model=payload.llm.name, temperature=payload.llm.temperature)

        # 2. Initialisation du pipeline avec nos outils
        pipeline = HurluBerlu(llm_client=target_llm, llm_extract=extractor, retriever=retriever)

        # 3. Exécution du pipeline
        res = pipeline.generate_response(payload.question)
        res = pipeline.extract_claims(res)
        res = pipeline.generate_samples(res)
        res = pipeline.evaluate_selfcheck(res)
        res = pipeline.evaluate_rag(res)
        res = pipeline.fuse_results(res)

        # 4. Formatage strict avec Pydantic
        claims_output = []
        for fused in res.fused_verdicts:
            claim_res = ClaimResult(
                claim_text=fused.claim_text,
                status=STATUS_BY_VERDICT[fused.verdict],
                fusion_score=fused.confidence,
                evidence_source="FEVER_corpus" if fused.evidence else "SelfCheckGPT",
                evidence_text=fused.evidence.text if fused.evidence else fused.explanation,
            )
            claims_output.append(claim_res)

        # 5. Retourne l'objet global PredictOutput
        sortie = PredictOutput(
            question=payload.question,
            llm_used=payload.llm,
            full_llm_answer=res.raw_answer,
            claims=claims_output,
            origin=PredictOrigin(
                cached=False,
                generator_model=modeles[0],
                extract_model=modeles[1],
                rag_model=modeles[2],
            ),
            debug=_construire_debug(res, modeles),
        )

        if store is not None:
            self._ecrire_cache(store, payload, modeles, sortie)

        # Calculé et mis en cache dans tous les cas, exposé seulement sur demande.
        if not payload.debug:
            sortie.debug = None
        return sortie

    def _lire_cache(self, store, payload: PredictInput, modeles: tuple[str, str, str]) -> PredictOutput | None:
        """Résultat en cache utilisable pour cette requête, ou `None`.

        L'entrée ne convient que si les modèles qui l'ont produite sont au moins
        aussi gros que ceux demandés. Une lecture qui échoue n'est pas une
        erreur de prédiction : on recalcule.
        """
        try:
            entree = store.get_predict_cache(payload.question, payload.llm.temperature)
        except Exception:
            logger.warning("⚠️ Lecture du cache de prédiction impossible — le pipeline va tourner.", exc_info=True)
            return None

        if entree is None:
            return None

        caches = (entree["generator_model"], entree["extract_model"], entree["rag_model"])
        if not satisfait(modeles, caches):
            return None

        sortie = PredictOutput(**entree["payload"])
        # Le détail vient du calcul qui a produit CETTE réponse : le resservir
        # avec elle est cohérent. On le masque seulement si l'appelant n'en veut
        # pas.
        if not payload.debug:
            sortie.debug = None
        # L'origine est réécrite à la lecture : elle doit nommer les modèles de
        # l'entrée servie, pas ceux enregistrés au moment de son calcul si le
        # schéma venait à diverger.
        sortie.origin = PredictOrigin(
            cached=True,
            generator_model=caches[0],
            extract_model=caches[1],
            rag_model=caches[2],
            computed_at=entree["computed_at"],
        )
        return sortie

    def _ecrire_cache(self, store, payload: PredictInput, modeles: tuple[str, str, str], sortie: PredictOutput) -> None:
        """Enregistre le résultat. Une écriture qui échoue ne doit jamais faire
        échouer une requête : la prédiction calculée reste valide."""
        try:
            store.put_predict_cache(
                payload.question,
                payload.llm.temperature,
                *modeles,
                sortie.model_dump(exclude={"origin"}),
            )
        except Exception:
            logger.warning("⚠️ Écriture du cache de prédiction impossible — le résultat reste valide.", exc_info=True)

    def get_available_llms(self) -> list[str]:
        """
        Récupère la liste des modèles installés sur le serveur Ollama ciblé
        (`BERLUE_OLLAMA_HOST`). Passe par `OllamaClient` plutôt que le module
        `ollama` global : hérite de son auth OIDC, nécessaire quand la cible
        est un service Cloud Run privé (`berlue-llm`), pas seulement un
        Ollama local. Si le serveur est inaccessible, l'erreur remontera
        naturellement jusqu'au endpoint FastAPI.
        """
        return OllamaClient().list_models()


def _construire_debug(res, modeles: tuple[str, str, str]) -> str:
    """Rend en texte lisible tout ce qui n'existait que dans les logs du serveur.

    Le même rendu que le journal, à partir des mêmes données : diagnostiquer
    depuis l'API et depuis les logs doit montrer la même chose, sinon on corrige
    d'après une version ce qu'on a observé sur l'autre.

    Les trois étages sont appariés par identifiant d'affirmation, jamais par
    position : une affirmation peut manquer d'un côté — RAG en panne, score
    SelfCheck absent — et un appariement positionnel décalerait tout le reste
    sans rien signaler.
    """
    divergences = {sc.claim_id: sc.divergence_score for sc in res.selfcheck_scores}
    fusions = {v.claim_id: v for v in res.fused_verdicts}

    lignes = [
        "═══ BERLUE · détail de l'analyse ═══",
        f"question   : {res.question}",
        f"réponse    : {res.raw_answer}",
        f"modèles    : génération {modeles[0]} · extraction {modeles[1]} · RAG {modeles[2]}",
        f"affirmations : {len(res.claims)} · échantillons SelfCheck : {len(res.samples)}",
    ]
    if res.panne:
        lignes.append(f"⚠️ PANNE   : {res.panne} — aucun verdict n'est rendu.")
    lignes.append("")

    traces = {t["claim_id"]: t for t in res.rag_traces}
    for claim in res.claims:
        detail = dict(traces.get(claim.id) or {"claim_id": claim.id, "claim_text": claim.text, "evidences": []})
        detail["selfcheck_divergence"] = divergences.get(claim.id)
        fusion = fusions.get(claim.id)
        if fusion:
            detail["fusion_verdict"] = fusion.verdict.value
            detail["fusion_confidence"] = fusion.confidence
            detail["fusion_explanation"] = fusion.explanation
            detail["fusion_fondement"] = fusion.fondement.value
        lignes.append(bloc_trace(detail))
        lignes.append("")

    if res.samples:
        lignes.append("═══ échantillons SelfCheck ═══")
        for i, echantillon in enumerate(res.samples, 1):
            lignes.append(f"  [{i}] {echantillon}")

    return "\n".join(lignes)
