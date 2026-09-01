import logging

from berlue.core.schemas import FusedVerdict, PipelineResult, RagJudgment, Verdict

logger = logging.getLogger(__name__)

# Seuil sous lequel on considère que SelfCheckGPT indique une incohérence significative
COHERENCE_THRESHOLD = 0.5
# Bonus appliqué quand cohérence ET preuve DB convergent fortement (cas FEVER_REFUTES)
CONVERGENCE_BONUS = 0.05
# Confiance plafonnée quand RAG et SelfCheck se contredisent (aucun des deux ne doit dominer)
CONFLICT_CONFIDENCE_CAP = 0.35
# Décote appliquée quand un seul des deux signaux est disponible (pas de second avis)
SINGLE_SIGNAL_DISCOUNT = 0.7


def do_fusion(result: PipelineResult, weight_rag: float = 0.7, weight_selfcheck: float = 0.3) -> PipelineResult:
    """
    Dernière étape : combine le jugement RAG (5 cas) et SelfCheckGPT pour statuer sur
    chaque affirmation.

    - FEVER_CONFIRMS / FEVER_REFUTES : preuve formelle en base, le RAG domine (logique inchangée).
    - LIKELY_TRUE / LIKELY_FALSE : pas de preuve en base, mais le RAG a un avis. On regarde
      si SelfCheck converge (confiance renforcée), diverge (conflit -> confiance plafonnée
      basse), ou est indisponible (un seul signal -> confiance décotée).
    - I_DONT_KNOWN : RAG indécis, on retombe sur SelfCheck seul.
    """
    logger.info("\n🧬 [Fusion] Début de la synthèse des résultats...")

    rag_dict = {v.claim_id: v for v in result.rag_scores}
    sc_dict = {s.claim_id: s for s in result.selfcheck_scores}

    for claim in result.claims:
        rag = rag_dict.get(claim.id)
        sc = sc_dict.get(claim.id)

        sc_available = sc is not None
        coherence = (1.0 - sc.divergence_score) if sc_available else 0.5
        # Le LLM ne s'est pas contredit entre ses échantillons (≠ "c'est vrai")
        llm_self_consistent = coherence >= COHERENCE_THRESHOLD

        evidence = None
        rag_judgment = rag.verdict if rag else RagJudgment.I_DONT_KNOWN

        # --- CAS 1 : FEVER prouve que c'est vrai ---
        if rag_judgment == RagJudgment.FEVER_CONFIRMS:
            final_verdict = Verdict.SUPPORTED
            final_conf = (rag.confidence * weight_rag) + (coherence * weight_selfcheck)
            explanation = "L'affirmation est factuellement prouvée par la base de données."
            evidence = rag.evidence

        # --- CAS 2 : FEVER prouve que c'est faux ---
        elif rag_judgment == RagJudgment.FEVER_REFUTES:
            final_verdict = Verdict.CONTRADICTED
            final_conf = rag.confidence
            if sc_available and coherence > 0.7:
                # LLM confiant à tort = signal d'hallucination supplémentaire, jamais un facteur d'atténuation
                final_conf = min(final_conf + CONVERGENCE_BONUS, 1.0)
            explanation = "L'affirmation est formellement contredite par la base de données."
            evidence = rag.evidence

        # --- CAS 3 : rien dans FEVER, mais le RAG est persuadé que c'est vrai ---
        elif rag_judgment == RagJudgment.LIKELY_TRUE:
            final_verdict = Verdict.NOT_ENOUGH_INFO  # jamais SUPPORTED sans preuve en base
            if sc_available and llm_self_consistent:
                final_conf = (rag.confidence * weight_rag) + (coherence * weight_selfcheck)
                explanation = (
                    "Le jugement du RAG et la cohérence du LLM convergent vers vrai,mais aucune preuve en base."
                )
            elif not sc_available:
                final_conf = rag.confidence * SINGLE_SIGNAL_DISCOUNT
                explanation = "Le RAG penche pour vrai, mais sans confirmation SelfCheck ni preuve en base."
            else:
                final_conf = CONFLICT_CONFIDENCE_CAP
                explanation = (
                    "Signaux contradictoires : le RAG penche pour vrai, mais le LLM s'est contredit lui-même"
                    "— à vérifier manuellement."
                )

        # --- CAS 4 : rien dans FEVER, mais le RAG est persuadé que c'est faux ---
        elif rag_judgment == RagJudgment.LIKELY_FALSE:
            if sc_available and not llm_self_consistent:
                final_verdict = Verdict.CONTRADICTED
                final_conf = (rag.confidence * weight_rag) + ((1.0 - coherence) * weight_selfcheck)
                explanation = (
                    "Le jugement du RAG et l'incohérence du LLM convergent : hallucination probable,"
                    "sans preuve en base."
                )
            elif not sc_available:
                final_verdict = Verdict.CONTRADICTED
                final_conf = rag.confidence * SINGLE_SIGNAL_DISCOUNT
                explanation = "Le RAG penche pour faux, mais sans confirmation SelfCheck ni preuve en base."
            else:
                # LLM cohérent (confiant) MAIS le RAG estime que c'est faux : à prendre au sérieux,
                # une hallucination "stable" est justement ce que SelfCheck seul ne détecte pas.
                final_verdict = Verdict.CONTRADICTED
                final_conf = CONFLICT_CONFIDENCE_CAP
                explanation = (
                    "Signaux contradictoires : le LLM est resté cohérent, mais le RAG estime que c'est faux"
                    "— à vérifier manuellement en priorité."
                )

        # --- CAS 5 : le RAG n'a aucune idée ---
        else:
            if not sc_available:
                final_verdict = Verdict.NOT_ENOUGH_INFO
                final_conf = 0.3
                explanation = "Aucune preuve disponible (ni base, ni jugement RAG, ni vérification interne)."
            elif not llm_self_consistent:
                final_verdict = Verdict.CONTRADICTED
                final_conf = 1.0 - coherence
                explanation = (
                    "Hallucination probable détectée : le LLM s'est contredit lui-même"
                    "(RAG indécis, aucune preuve en base)."
                )
            else:
                final_verdict = Verdict.NOT_ENOUGH_INFO
                final_conf = coherence
                explanation = "L'affirmation semble cohérente, mais manque de sources dans la base (RAG indécis)."

        # Petite sécurité pour être sûr que la confiance reste entre 0.0 et 1.0
        final_conf = min(max(final_conf, 0.0), 1.0)

        fused = FusedVerdict(
            claim_id=claim.id,
            claim_text=claim.text,
            verdict=final_verdict,
            confidence=final_conf,
            evidence=evidence,
            explanation=explanation,
        )
        result.fused_verdicts.append(fused)

    return result
