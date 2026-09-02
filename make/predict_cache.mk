# ==============================================================================
# CACHE DES PRÉDICTIONS — /predict
# ==============================================================================
# Sans rapport avec les caches d'évaluation (cf. evaluate_model_purge) : celui-ci
# garde le retour complet de /predict pour une question déjà posée, et identifie
# un modèle par sa TAILLE et non par son tag exact (cf. berlue/api/predict_cache.py).
# Les deux sont indépendants — purger l'un ne touche jamais l'autre.
#
# Le magasin visé suit BERLUE_EVAL_STORE_TARGET : SQLite en local, Firestore
# quand il vaut gcp.

predict_cache_list: ## Affiche le contenu du cache de prédiction (question, température, modèles, date)
	@python -m berlue.api.predict_cache_cli list

# Variables préfixées CACHE_ : `QUESTION` a déjà une valeur par défaut dans
# make/pipeline.mk, si bien qu'un filtre était toujours transmis — la purge
# annonçait son travail et ne supprimait rien.
predict_cache_purge: ## Vide le cache de prédiction — filtres facultatifs CACHE_QUESTION=, CACHE_TEMPERATURE=, CACHE_MODEL= (sans filtre : tout)
	@python -m berlue.api.predict_cache_cli purge \
		$(if $(CACHE_QUESTION),--question "$(CACHE_QUESTION)") \
		$(if $(CACHE_TEMPERATURE),--temperature $(CACHE_TEMPERATURE)) \
		$(if $(CACHE_MODEL),--model $(CACHE_MODEL))

predict_cache_push: gcp_check_cli_auth ## Publie le cache de prédiction local vers Firestore — CACHE_QUESTION= pour une seule, CACHE_FORCE=1 pour écraser une entrée distante meilleure
	@python -m berlue.api.predict_cache_cli push \
		$(if $(CACHE_QUESTION),--question "$(CACHE_QUESTION)") \
		$(if $(CACHE_FORCE),--force)
