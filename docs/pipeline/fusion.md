# Fusion

Combine le verdict RAG ([`rag.md`](rag.md), `RagVerdict`) et le score
SelfCheckGPT ([`selfcheck.md`](selfcheck.md), `SelfCheckScore`) d'une même
affirmation en un seul verdict final (`FusedVerdict`) — voir
`berlue/pipeline/hurlu_berlu.py::HurluBerlu.fuse_results`, dernière étape de
l'orchestrateur ([`hurlu_berlu.md`](hurlu_berlu.md)).

## Logique

```python
fuse_results(result, weight_rag=0.7, weight_selfcheck=0.3) -> PipelineResult
```

Pour chaque affirmation, la cohérence interne (`coherence`) est déduite du
score SelfCheckGPT (`1 - divergence_score`, ou `0.5` si aucun score) :

- **Le RAG a trouvé une preuve tranchée** (verdict RAG ≠
  `NOT_ENOUGH_INFO`) : le verdict RAG l'emporte. Confiance finale = mix
  pondéré (`weight_rag` sur la confiance RAG, `weight_selfcheck` sur la
  cohérence interne). La preuve citée est celle du RAG.
- **Sinon** (pas de preuve RAG) : on se base sur SelfCheckGPT seul — grande
  incohérence entre les tirages (`coherence < 0.5`) → `CONTRADICTED`
  (hallucination probable) ; sinon → `NOT_ENOUGH_INFO` (cohérent mais sans
  source).

La confiance finale est toujours ramenée dans `[0.0, 1.0]`.

## Lancer cette étape

Pas de cible `make` dédiée à la fusion seule — c'est la dernière étape de
l'orchestrateur :

```bash
python -m berlue.pipeline.hurlu_berlu --until fusion --question "..."
```

Voir [`hurlu_berlu.md`](hurlu_berlu.md).
