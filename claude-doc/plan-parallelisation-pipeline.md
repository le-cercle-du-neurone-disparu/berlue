# Plan — parallélisation du pipeline HurluBerlu (RAG ∥ SelfCheckGPT, échantillonnage multi-température)

> **Statut : plan seulement, aucun code touché.** Coordination : une session
> front tourne en parallèle et lance Berlue en local pour tester contre lui —
> ce refacto part sur une branche dédiée (pas `feat-berlu-sur-gcp` ni `main`)
> et ne change ni le contrat HTTP `/predict` (`berlue/api/schemas.py`) ni le
> comportement observable du pipeline (mêmes verdicts, juste plus rapide) :
> rien ne doit exiger que le front change quoi que ce soit ni ré-clone.

## Objectif

Actuellement, dans `HurluBerlu` (`berlue/pipeline/hurlu_berlu.py`), tout est
séquentiel : génération → extraction → **échantillonnage SelfCheckGPT (K
appels LLM, un par un) → score SelfCheckGPT → vérification RAG (un appel LLM
par affirmation, un par un)** → fusion. Deux axes de parallélisme demandés :

1. **Niveau pipeline** : la branche SelfCheckGPT (échantillonnage + score) et
   la branche RAG tournent en parallèle plutôt que l'une après l'autre —
   toutes deux ne dépendent que de `result.claims` (étape 2), jamais l'une de
   l'autre.
2. **Niveau échantillonnage** : à l'intérieur de SelfCheckGPT, les K appels
   LLM à températures différentes (`OllamaClient.generate_many`, appelé par
   `selfcheck/sampler.py`) partent en parallèle via des threads, plutôt
   qu'en boucle.

```
AVANT (séquentiel)                          APRÈS (visé)
─────────────────────                       ─────────────────────
extract_claims                              extract_claims
   │                                            │
   ▼                                    ┌───────┴───────┐
generate_samples (K appels en série)    ▼               ▼
   │                              generate_samples   evaluate_rag
   ▼                              (K appels EN        (1 appel LLM
evaluate_selfcheck                 PARALLÈLE, threads)  par claim,
   │                                   │                 en série)
   ▼                              evaluate_selfcheck     │
evaluate_rag (N appels en série)      │               ◄──┘
   │                              └───────┬───────┘
   ▼                                      ▼
fuse_results                        fuse_results
```

## Le vrai obstacle : le remplissage de `PipelineResult`

`PipelineResult` (`berlue/core/schemas.py`) est une dataclass mutable unique,
remplie **progressivement** par mutation en place : chaque étape reçoit le
même objet, lui ajoute des champs (`result.samples = [...]`,
`result.selfcheck_scores.append(...)`, `result.rag_scores.append(...)`) et le
retourne. Ça marche en séquentiel parce qu'il n'y a jamais deux écritures
concurrentes. Dès qu'on parallélise, deux cas très différents :

- **Branches RAG et SelfCheck en parallèle (axe 1)** : elles écrivent des
  attributs *disjoints* de `PipelineResult` (`rag_scores` d'un côté,
  `samples`/`selfcheck_scores` de l'autre) — deux threads qui mutent deux
  attributs différents du même objet ne se marchent pas dessus. Ça reste
  vrai tant qu'aucune des deux branches ne touche à l'attribut de l'autre.
  Fragile à documenter explicitement (cf. section design), mais pas de
  réorganisation profonde nécessaire ici.
- **K échantillons en parallèle (axe 2) — le point signalé par Xavier** :
  `OllamaClient.generate_many` construit aujourd'hui sa liste de réponses par
  un `for temp in temperatures: responses.append(resp)` strictement
  séquentiel — l'ordre de la liste retournée == l'ordre des températures
  demandées, par construction. Paralléliser ça avec un
  `.append()` déclenché à la complétion de chaque thread casse cette
  garantie : les réponses arrivent dans l'ordre où les threads *finissent*
  (dépend de la charge du serveur Ollama, pas de l'ordre de soumission), pas
  dans l'ordre des températures. Il faut donc **remplacer l'append
  séquentiel par un mécanisme qui réassemble les résultats par position**
  (voir design ci-dessous) — c'est le "remplissage à reorganiser" en
  question.

Principe retenu pour les deux cas, minimal-diff : **séparer le calcul
(parallèle, chaque worker produit une valeur autonome) de l'assemblage
(toujours séquentiel, un seul thread écrit dans `PipelineResult` ou dans la
liste finale)**. On ne touche pas au schéma de `PipelineResult` ni à la
structure des dataclasses de `core/schemas.py`.

## Design proposé

### Axe 2 — `OllamaClient.generate_many` (le plus contraint, à faire en premier)

```python
def generate_many(self, prompt, k, temperature_min, temperature_max) -> list[str]:
    ...
    temperatures = [...]  # inchangé
    with ThreadPoolExecutor(max_workers=k) as executor:
        # executor.map() préserve l'ordre des résultats == l'ordre de
        # `temperatures`, quel que soit l'ordre réel de complétion des
        # threads — remplace le `responses.append()` séquentiel sans
        # changer le contrat de la fonction (même signature, même liste
        # ordonnée en sortie).
        responses = list(executor.map(lambda t: self.generate(prompt, temperature=t), temperatures))
    return responses
```

- Pas de verrou nécessaire : chaque thread ne touche que son propre appel
  `self.generate(...)` (aucun état partagé écrit — `self.client` du SDK
  `ollama` fait un appel HTTP par requête, sans état mutable côté client).
- Erreurs : `executor.map` fait remonter la première exception rencontrée
  (dans l'ordre de la liste) au moment où on la consomme via `list(...)` —
  même sémantique fail-fast qu'aujourd'hui (une erreur dans le for-loop
  actuel interrompt aussi tout de suite). Pas de tolérance partielle
  ajoutée (ex. "4 échantillons sur 5 ok") — décision explicite pour rester
  minimal, à discuter séparément si voulu.
- `max_workers=k` : k vaut `SELFCHECK_K` par défaut (5, `berlue/params.py`)
  — pas besoin d'un pool partagé/persistant, un pool éphémère par appel
  suffit (k appels de plusieurs secondes chacun, le coût de création des
  threads est négligeable en comparaison).

### Axe 1 — branches RAG ∥ SelfCheck dans `HurluBerlu`

Nouvelle méthode d'orchestration sur `HurluBerlu`, à la place des 3 appels
séquentiels (`generate_samples` → `evaluate_selfcheck` → `evaluate_rag`)
dupliqués aujourd'hui dans `berlue/api/service.py` (lignes 21-23) et
`berlue/evaluation/berlue_pipeline.py` (lignes 61-63) :

```python
def evaluate_branches(self, result: PipelineResult) -> PipelineResult:
    """Lance la branche SelfCheckGPT (échantillonnage + score) et la
    branche RAG en parallèle — toutes deux ne lisent que `result.claims`,
    aucune des deux n'écrit l'attribut de l'autre."""

    def selfcheck_branch():
        r = self.generate_samples(result)
        return self.evaluate_selfcheck(r)

    with ThreadPoolExecutor(max_workers=2) as executor:
        selfcheck_future = executor.submit(selfcheck_branch)
        rag_future = executor.submit(self.evaluate_rag, result)
        selfcheck_future.result()  # propage l'exception si une branche a échoué (fail-fast)
        rag_future.result()

    return result
```

- Les deux branches reçoivent la **même instance** `result` (pas de copie) —
  volontaire : elles écrivent des attributs disjoints
  (`samples`/`selfcheck_scores` vs `rag_scores`), donc pas de conflit, et ça
  évite d'avoir à fusionner deux objets à la fin (déjà "assemblé" par
  construction). Documenter cette invariante en commentaire à côté des deux
  méthodes (`evaluate_selfcheck`, `evaluate_rag`) pour que personne n'y
  ajoute un jour une écriture croisée sans le remarquer.
- `.result()` appelé sur les deux futures (pas seulement celle qui finit en
  premier) pour que l'exception d'une branche ne soit jamais avalée
  silencieusement.
- Remplace les 3 lignes dupliquées dans `api/service.py` et
  `evaluation/berlue_pipeline.py` par un seul appel à
  `pipeline.evaluate_branches(res)` — réduit aussi la duplication actuelle
  entre les deux call sites au passage.

### Ce qui ne change pas

- `PipelineResult`, `Claim`, `SelfCheckScore`, `RagVerdict`, `FusedVerdict`
  (`core/schemas.py`) — aucun champ ajouté/renommé.
- `berlue/api/schemas.py` (`PredictInput`/`PredictOutput`) — le contrat HTTP
  `/predict` est identique, donc rien à changer côté front.
- Pas de passage à `asyncio` : `predict_endpoint` (`berlue/api/fast.py`) est
  un `def` synchrone, déjà exécuté par FastAPI dans son threadpool — des
  threads internes supplémentaires ne bloquent donc rien de plus qu'avant,
  pas besoin de réécrire l'endpoint en `async def`.
- La boucle externe par question de `evaluation/run_eval.py`
  (`ThreadPoolExecutor(max_workers=concurrency)`, déjà en place,
  `concurrency=1` par défaut) — hors scope, cf. section suivante.

## Prérequis / risques à vérifier avant de coder

- **Capacité du serveur Ollama.** `run_eval.py` a déjà un axe de parallélisme
  (par question, via `concurrency`), documenté comme devant rester aligné
  sur `OLLAMA_NUM_PARALLEL` du serveur ciblé
  (`docs/gcp/ollama-gpu-parallelism.md` — au-delà de `N_max`, les requêtes
  en trop s'empilent côté serveur sans rien gagner). Ce refacto **ajoute un
  second axe multiplicatif** : pic de requêtes Ollama simultanées ≈
  `concurrency_run_eval × (K + 1)` au lieu de `concurrency_run_eval × 1`
  aujourd'hui (K=5 par défaut, +1 pour la branche RAG qui tourne maintenant
  en même temps). À vérifier contre le `N_max` du modèle utilisé
  (`docs/gcp/ollama-gpu-parallelism.md`, tableau par modèle) avant
  d'activer `concurrency > 1` dans `run_eval.py` en même temps que ce
  refacto — sinon gain nul voire régression (files d'attente côté serveur).
  En usage `/predict` normal (une question à la fois, pas via `run_eval.py`),
  le pic passe juste de 1 à `K+1` — sans commune mesure, aucun risque.
- **Thread-safety de `RagRetriever`.** Déjà documentée comme sûre pour un
  usage concurrent par le commentaire existant dans `run_eval.py:517-520`
  (`verify_claim` n'écrit aucun état d'instance partagé). Ce refacto ne
  change pas la façon dont RAG est appelé (toujours un appel par claim, en
  série, juste dans un thread différent) — pas de nouveau risque, mais à
  re-vérifier une fois `evaluate_branches` en place : `SentenceTransformer.
  encode()` et `faiss.Index.search()` doivent tolérer un appel concurrent à
  un appel de `OllamaClient.generate` sur un thread voisin (aucune raison
  que non — pas d'état partagé entre les deux — mais à confirmer par un test
  fonctionnel réel, pas juste mocké).
- **Comportement d'erreur inchangé (fail-fast).** Décision explicite des
  deux designs ci-dessus : la première exception rencontrée interrompt tout
  le pipeline, comme aujourd'hui. Ne pas glisser vers une tolérance
  partielle (« continuer avec 4 échantillons sur 5 ») sans decision
  explicite séparée — ce serait un changement de comportement, pas
  juste une parallélisation.

## Tests à mettre à jour

- `tests/test_llm_client.py::test_generate_many_distributes_temperatures_evenly`
  vérifie aujourd'hui l'ordre d'**arrivée des appels** sur le
  `FakeInnerClient` (`client.calls[i]`) — plus garanti une fois les appels
  parallélisés (le serveur/mock peut répondre dans le désordre). À adapter :
  garder l'assertion sur le **résultat retourné** (déjà ordonné par
  `executor.map`), remplacer l'assertion sur `calls` par une comparaison en
  ensemble (`{c["options"]["temperature"] for c in calls} == {...}`) plutôt
  qu'en séquence.
- Ajouter un test qui force explicitement le désordre de complétion (ex.
  `FakeInnerClient` qui dort plus longtemps sur la 1ʳᵉ température que sur
  la dernière) et vérifie que `generate_many` renvoie quand même les
  réponses dans l'ordre des températures — c'est le test qui aurait attrapé
  la régression que ce refacto cherche justement à éviter.
- `tests/temp_test_pipeline.py::test_evaluate_selfcheck_appends_one_score_per_claim`
  : inchangé, cette boucle-là (par claim, à l'intérieur d'une branche) reste
  séquentielle dans ce plan (cf. "Hors scope").
- Nouveau test pour `HurluBerlu.evaluate_branches` : vérifier que
  `result.samples`, `result.selfcheck_scores` et `result.rag_scores` sont
  tous les trois remplis après appel (les deux branches ont bien tourné),
  et qu'une exception levée dans une branche stubée remonte bien à
  l'appelant (fail-fast).

## Hors scope (pour rester minimal)

- Paralléliser la boucle par claim *à l'intérieur* d'une branche (le
  `for claim in result.claims` de `evaluate_selfcheck` et de
  `RagRetriever.verify_claims`) — demanderait de gérer un troisième niveau
  d'imbrication de threads (question × branche × claim), pas demandé
  explicitement, et le gain est plus incertain (le score NLI tourne déjà en
  mémoire/GPU local, pas un appel réseau comme les LLM calls des deux axes
  ci-dessus).
- Le `concurrency` déjà existant de `evaluation/run_eval.py` (parallélisme
  par question) — pas touché, juste documenté comme facteur multiplicatif à
  surveiller une fois ce refacto en place (section prérequis).

## Étapes d'implémentation (une fois ce plan validé)

1. Branche dédiée (pas `feat-berlu-sur-gcp`).
2. `OllamaClient.generate_many` → `ThreadPoolExecutor.map` (axe 2 seul,
   testable indépendamment).
3. Mettre à jour `tests/test_llm_client.py` (ordre d'arrivée → ordre de
   résultat, + test anti-régression désordre).
4. `HurluBerlu.evaluate_branches` (axe 1), + test dédié.
5. Basculer `api/service.py` et `evaluation/berlue_pipeline.py` sur
   `evaluate_branches` (supprime les 3 lignes dupliquées dans les deux).
6. Test fonctionnel réel (`@pytest.mark.functional`, vrai Ollama) pour
   confirmer le gain de latence et l'absence de dégradation RAG.
7. Mettre à jour `docs/pipeline/hurlu_berlu.md` et
   `docs/pipeline/selfcheck.md` (schéma des étapes, actuellement présenté
   comme strictement séquentiel 1→2→3→4→5).
