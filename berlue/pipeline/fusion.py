import logging

from berlue.core.schemas import FusedVerdict, PipelineResult, Verdict

logger = logging.getLogger(__name__)


def do_fusion(result: PipelineResult, weight_rag: float = 0.7, weight_selfcheck: float = 0.3) -> PipelineResult:
    """
    Dernière étape : combine les scores RAG et SelfCheckGPT pour statuer sur chaque affirmation.
    Prend en compte les 5 nouveaux statuts RAG pour affiner l'explication et la confiance.
    """
    logger.info("🧬 [Fusion] Début de la synthèse des résultats...")

    rag_dict = {v.claim_id: v for v in result.rag_scores}
    sc_dict = {s.claim_id: s for s in result.selfcheck_scores}

    for claim in result.claims:
        rag = rag_dict.get(claim.id)
        sc = sc_dict.get(claim.id)

        # 1. Calcul de la cohérence interne (l'inverse de la divergence)
        coherence = 1.0 - sc.divergence_score if sc else 0.5

        # On extrait la valeur du verdict RAG en texte (gère les Enum et les strings)
        rag_verdict = str(rag.verdict).split(".")[-1] if rag else "I_DONT_KNOW"

        # 2. Application de l'arbre de décision
        if rag_verdict == "FEVER_CONFIRMS":
            final_verdict = Verdict.SUPPORTED
            final_conf = (rag.confidence * weight_rag) + (coherence * weight_selfcheck)
            explanation = "L'affirmation est factuellement prouvée par la base de données FEVER."
            evidence = rag.evidence

        elif rag_verdict == "FEVER_REFUTES":
            final_verdict = Verdict.CONTRADICTED
            final_conf = (rag.confidence * weight_rag) + (coherence * weight_selfcheck)
            explanation = "L'affirmation est formellement contredite par la base de données FEVER."
            evidence = rag.evidence

        elif rag_verdict == "LIKELY_TRUE":
            final_verdict = Verdict.SUPPORTED
            final_conf = (rag.confidence * weight_rag) + (coherence * weight_selfcheck)
            explanation = "Absente de FEVER, mais jugée très vraisemblable selon les connaissances générales du modèle."
            evidence = None

        elif rag_verdict == "LIKELY_FALSE":
            final_verdict = Verdict.CONTRADICTED
            # Si c'est LIKELY_FALSE, une faible cohérence (hallucination SelfCheck) renforce l'idée que c'est faux
            final_conf = (rag.confidence * weight_rag) + ((1.0 - coherence) * weight_selfcheck)
            explanation = (
                "Absente de FEVER, mais jugée invraisemblable (hallucination probable) "
                "selon les connaissances générales."
            )
            evidence = None

        else:
            # CAS "I_DONT_KNOW" : Ni FEVER ni les connaissances internes ne peuvent trancher.
            # On s'en remet à 100% au comportement du générateur (SelfCheck).
            if coherence < 0.5:
                # Le générateur s'est contredit dans ses propres réponses.
                final_verdict = Verdict.CONTRADICTED
                final_conf = 1.0 - coherence
                explanation = (
                    "Hallucination détectée : aucune information disponible et le modèle se contredit lui-même."
                )
            else:
                # Le générateur est très cohérent, mais on a zéro preuve.
                final_verdict = Verdict.NOT_ENOUGH_INFO
                final_conf = coherence
                explanation = (
                    "L'affirmation semble cohérente, mais manque de sources et sort des connaissances générales."
                )
            evidence = None

        # Petite sécurité pour être sûr que la confiance reste entre 0.0 et 1.0
        final_conf = min(max(final_conf, 0.0), 1.0)

        # 3. Création de l'objet final
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
