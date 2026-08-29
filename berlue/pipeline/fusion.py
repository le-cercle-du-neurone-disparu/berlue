from berlue.core.schemas import FusedVerdict, PipelineResult, Verdict


def do_fusion(result: PipelineResult, weight_rag: float = 0.7, weight_selfcheck: float = 0.3) -> PipelineResult:
    """
    Dernière étape : combine les scores RAG et SelfCheckGPT pour statuer sur chaque affirmation.
    Utilise le pattern Passe-Plat.
    """
    print("\n🧬 [Fusion] Début de la synthèse des résultats...")

    # Pour retrouver les résultats en O(1) sans faire des boucles imbriquées
    rag_dict = {v.claim_id: v for v in result.rag_scores}
    sc_dict = {s.claim_id: s for s in result.selfcheck_scores}

    for claim in result.claims:
        rag = rag_dict.get(claim.id)
        sc = sc_dict.get(claim.id)

        # 1. Calcul de la cohérence interne (l'inverse de la divergence)
        # Si le score de divergence est 0.1, la cohérence est 0.9 (très sûr)
        coherence = 1.0 - sc.divergence_score if sc else 0.5

        # 2. Application de l'arbre de décision
        if rag and rag.verdict != Verdict.NOT_ENOUGH_INFO:
            # CAS A : Le RAG a trouvé une preuve tranchée dans la base de données
            final_verdict = rag.verdict

            # Le score est un mix : le RAG pèse 70%, la certitude du LLM pèse 30%
            final_conf = (rag.confidence * weight_rag) + (coherence * weight_selfcheck)

            if final_verdict == Verdict.SUPPORTED:
                explanation = "L'affirmation est factuellement prouvée par la base de données."
            else:
                explanation = "L'affirmation est formellement contredite par la base de données."

            evidence = rag.evidence

        else:
            # CAS B : Le RAG n'a rien trouvé. On s'en remet au comportement du LLM.
            if coherence < 0.5:
                # Le LLM s'est contredit dans les samples. C'est une hallucination !
                final_verdict = Verdict.CONTRADICTED
                final_conf = 1.0 - coherence  # Plus il est incohérent, plus on est sûr que c'est faux
                explanation = "Hallucination probable détectée : le LLM s'est contredit lui-même."
            else:
                # Le LLM est sûr de lui, mais on n'a pas de preuve.
                final_verdict = Verdict.NOT_ENOUGH_INFO
                final_conf = coherence
                explanation = "L'affirmation semble cohérente, mais manque de sources dans la base."

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
