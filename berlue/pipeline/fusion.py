from berlue.core.schemas import FusedVerdict, PipelineResult, RagJudgment, Verdict

# --- Seuils de la zone "sans preuve FEVER" ---
# < HALLU_THRESHOLD -> hallu (CONTRADICTED) | entre les deux -> incertain (NOT_ENOUGH_INFO)
# > VALIDATED_THRESHOLD -> validé (SUPPORTED). Zone incertaine = 0.50 (+/- 0.10).
HALLU_THRESHOLD = 0.40
VALIDATED_THRESHOLD = 0.60

# Bonus appliqué quand cohérence ET preuve DB convergent fortement (cas FEVER_REFUTES)
CONVERGENCE_BONUS = 0.05
# Facteur de décote appliqué au signal RAG quand SelfCheck est indisponible (pas de second avis)
SINGLE_SIGNAL_DISCOUNT = 0.7


def _rag_directional_belief(rag_judgment: RagJudgment, rag_confidence: float) -> float:
    """
    Traduit un jugement RAG SANS preuve FEVER en un score directionnel 0-1 :
    0.0 = penche franchement faux, 0.5 = neutre/aucune idée, 1.0 = penche franchement vrai.
    """
    if rag_judgment == RagJudgment.LIKELY_TRUE:
        return 0.5 + (rag_confidence * 0.5)
    if rag_judgment == RagJudgment.LIKELY_FALSE:
        return 0.5 - (rag_confidence * 0.5)
    return 0.5  # I_DONT_KNOWN


def do_fusion(
    result: PipelineResult,
    weight_rag: float = 0.7,
    weight_selfcheck: float = 0.3,
    weight_rag_unproven: float = 0.5,
    weight_selfcheck_unproven: float = 0.5,
) -> PipelineResult:
    """
    Dernière étape : combine le jugement RAG (5 cas) et SelfCheckGPT pour statuer sur
    chaque affirmation.

    - FEVER_CONFIRMS / FEVER_REFUTES : preuve formelle en base, le RAG domine
      (weight_rag/weight_selfcheck, logique inchangée).
    - LIKELY_TRUE / LIKELY_FALSE / I_DONT_KNOWN : pas de preuve en base. On calcule un score
      combiné (weight_rag_unproven/weight_selfcheck_unproven, 50/50 par défaut puisque le RAG
      n'a ici aucune preuve à faire valoir) puis on le classe via les seuils hallu/incertain/validé.
    """
    print("\n🧬 [Fusion] Début de la synthèse des résultats...")

    rag_dict = {v.claim_id: v for v in result.rag_scores}
    sc_dict = {s.claim_id: s for s in result.selfcheck_scores}

    for claim in result.claims:
        rag = rag_dict.get(claim.id)
        print(f"DEBUG FUSION: verdict={rag.verdict if rag else None} (type: {type(rag.verdict if rag else None)})")
        sc = sc_dict.get(claim.id)

        sc_available = sc is not None
        coherence = (1.0 - sc.divergence_score) if sc_available else 0.5

        evidence = None
        rag_judgment = rag.verdict if rag else RagJudgment.I_DONT_KNOWN
        print(f"le jugement de rag c'est :{rag_judgment}")

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
                final_conf = min(final_conf + CONVERGENCE_BONUS, 1.0)
            explanation = "L'affirmation est formellement contredite par la base de données."
            evidence = rag.evidence

        # --- CAS 3/4/5 : rien dans FEVER -> score combiné + seuils hallu/incertain/validé ---
        else:
            # Garde-fou : vraiment aucune information nulle part (ni RAG, ni SelfCheck)
            if not sc_available and rag_judgment == RagJudgment.I_DONT_KNOWN:
                final_verdict = Verdict.NOT_ENOUGH_INFO
                final_conf = 0.3
                explanation = "Aucune preuve disponible (ni base, ni jugement RAG, ni vérification interne)."
            else:
                rag_belief = _rag_directional_belief(rag_judgment, rag.confidence if rag else 0.0)

                if sc_available:
                    score = (rag_belief * weight_rag_unproven) + (coherence * weight_selfcheck_unproven)
                else:
                    # Un seul signal dispo : on tire le score vers le neutre plutôt que de lui faire confiance à 100%
                    score = 0.5 + (rag_belief - 0.5) * SINGLE_SIGNAL_DISCOUNT

                if score < HALLU_THRESHOLD:
                    final_verdict = Verdict.CONTRADICTED
                    final_conf = 1.0 - score
                    explanation = (
                        f"Score combiné {score:.2f} sous le seuil d'hallucination "
                        f"({HALLU_THRESHOLD}) : probablement faux, sans preuve en base."
                    )
                elif score > VALIDATED_THRESHOLD:
                    final_verdict = Verdict.SUPPORTED
                    final_conf = score
                    explanation = (
                        f"Score combiné {score:.2f} au-dessus du seuil de validation "
                        f"({VALIDATED_THRESHOLD}) : probablement vrai, mais sans preuve en base."
                    )
                else:
                    final_verdict = Verdict.NOT_ENOUGH_INFO
                    final_conf = 1.0 - 2 * abs(score - 0.5)
                    explanation = (
                        f"Score combiné {score:.2f} dans la zone d'incertitude "
                        f"({HALLU_THRESHOLD}-{VALIDATED_THRESHOLD}) : ni preuve, ni signal tranché."
                    )

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
