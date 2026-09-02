# ==============================================================================
# CODE EN BUCKET — publication et rechargement sans rebuild d'image
# ==============================================================================
# L'image `berlue-runtime` ne contient que les dépendances (cf. Dockerfile) :
# le code vient de gs://$(CODE_BUCKET_NAME)/$(CODE_VERSION)/, monté en volume
# GCS FUSE sur /mnt/code et recopié dans /app au démarrage du conteneur
# (docker/entrypoint.sh).
#
# Deux cycles, deux coûts :
#   make gcp_deploy    build + push des images, puis les services   (~15 min,
#                      seulement quand requirements.txt ou le Dockerfile bougent)
#   make code_deploy   publie le code et fait redémarrer dessus     (~1 min,
#                      le geste courant, à chaque changement de Python)
#
# Détail : docs/gcp/code-en-bucket.md.

code_bucket_create: gcp_check_cli_auth ## Crée le bucket GCS du code s'il n'existe pas déjà (dans BUCKET_PROJECT) — appelé par gcp_setup, doit rester rejouable sans erreur
	@if gcloud storage buckets describe gs://$(CODE_BUCKET_NAME) --project=$(BUCKET_PROJECT) >/dev/null 2>&1 </dev/null; then \
		echo "✅ Bucket gs://$(CODE_BUCKET_NAME) déjà présent, création sautée."; \
	else \
		echo "🪣 Création du bucket gs://$(CODE_BUCKET_NAME)..."; \
		$(RETRY) "création du bucket gs://$(CODE_BUCKET_NAME)" \
			gcloud storage buckets create gs://$(CODE_BUCKET_NAME) \
				--location=$(GCP_REGION) \
				--project=$(BUCKET_PROJECT); \
	fi

code_bucket_grant_sa: gcp_check_cli_auth ## Autorise sa-berlue à lire le bucket de code — requis par le volume GCS FUSE des services applicatifs
	@echo "🔐 Lecture pour $(CLOUDRUN_SA_EMAIL) sur gs://$(CODE_BUCKET_NAME)..."
	@$(RETRY) "autorisation de $(CLOUDRUN_SA_EMAIL) sur gs://$(CODE_BUCKET_NAME)" \
		gcloud storage buckets add-iam-policy-binding gs://$(CODE_BUCKET_NAME) \
			--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
			--role="roles/storage.objectViewer"

code_bucket_delete: ## Supprime le bucket de code et tout son contenu (appelé par gcp_destroy)
	@echo "💣 Suppression du bucket gs://$(CODE_BUCKET_NAME)..."
	gcloud storage rm --recursive gs://$(CODE_BUCKET_NAME)

# Un service déployé sur une version de code absente du bucket donne un
# conteneur qui ne boote pas, l'erreur enfouie dans les logs Cloud Run après
# plusieurs minutes — même raisonnement que le contrôle de l'index RAG dans
# cloudrun_deploy. Prérequis des déploiements, jamais appelé directement.
_code_version_check:
	@gcloud storage ls gs://$(CODE_BUCKET_NAME)/$(CODE_VERSION)/berlue/params.py >/dev/null 2>&1 </dev/null || { \
		echo "❌ Code introuvable : gs://$(CODE_BUCKET_NAME)/$(CODE_VERSION)/berlue/"; \
		echo "   Sans lui, aucun service applicatif ne démarrera."; \
		$(MAKE) --no-print-directory code_versions; \
		echo "   👉 make code_push (publie CODE_VERSION=$(CODE_VERSION))"; \
		exit 1; \
	}

code_push: gcp_check_cli_auth ## Publie le code local dans gs://CODE_BUCKET_NAME/CODE_VERSION (défaut current) — ne redémarre rien, cf. code_reload
	@bash scripts/code_push.sh $(CODE_BUCKET_NAME) $(CODE_VERSION)

code_versions: ## Liste les versions de code présentes dans le bucket
	@echo "📚 Versions dans gs://$(CODE_BUCKET_NAME)/ :"
	@gcloud storage ls gs://$(CODE_BUCKET_NAME)/ 2>/dev/null </dev/null \
		| sed -e 's#gs://$(CODE_BUCKET_NAME)/#  #' -e 's#/$$##' \
		|| echo "  (bucket vide ou absent)"

# Une nouvelle révision est indispensable, pas un confort : un process Python
# déjà démarré ne relit pas ses imports, et GCS FUSE cache ses métadonnées.
# Le marqueur horodaté sert uniquement à garantir que gcloud voie bien un
# changement de configuration — sans lui, un `update` sans diff ne crée
# aucune révision et le code publié ne serait jamais chargé.
code_reload: gcp_check_cli_auth ## Fait repartir les services applicatifs déployés sur la version de code publiée (nouvelle révision, aucun rebuild)
	@STAMP=$$(date -u +%Y%m%dT%H%M%SZ); \
	for SVC in $(GAR_IMAGE)-$(CLOUDRUN_ENV) $(CLOUDRUN_EVAL_SERVICE); do \
		if gcloud run services describe $$SVC --region $(GCP_REGION) --project $(GCP_PROJECT) >/dev/null 2>&1 </dev/null; then \
			echo "♻️  $$SVC -> code $(CODE_VERSION) (révision $$STAMP)..."; \
			gcloud run services update $$SVC \
				--region $(GCP_REGION) \
				--project $(GCP_PROJECT) \
				--update-env-vars=BERLUE_CODE_DIR=/mnt/code/$(CODE_VERSION),BERLUE_CODE_RELOADED_AT=$$STAMP \
				--quiet </dev/null; \
		else \
			echo "⏭️  $$SVC non déployé — rien à recharger."; \
		fi; \
	done
	@echo "✅ code_reload terminé."

code_deploy: ## Publie le code ET fait redémarrer les services dessus — le geste courant après un changement de Python (aucun build, aucun push d'image)
	@$(MAKE) --no-print-directory code_push
	@$(MAKE) --no-print-directory code_reload
