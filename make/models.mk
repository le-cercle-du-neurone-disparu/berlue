# ==============================================================================
# MODÈLES EN BUCKET — poids HuggingFace hors de l'image
# ==============================================================================
# Le pipeline charge deux modèles paresseusement, au premier usage réel :
# le SentenceTransformer d'embedding (RagRetriever.__init__) et le NLI de
# SelfCheckGPT (selfcheck/scorer.py). Sans cache, chaque démarrage à froid les
# retélécharge — ~2 Go, en plein milieu d'une requête déjà longue.
#
# Ils vivent donc dans gs://$(MODELS_BUCKET_NAME)/, monté en volume GCS FUSE
# sur /mnt/models et désigné aux bibliothèques par HF_HOME. Même raison que
# l'index RAG et le code : ce qui est lourd et rarement modifié n'a pas sa
# place dans l'image, dont chaque octet est rebuildé et repoussé.
#
# Détail : docs/gcp/modeles-en-bucket.md.

# Nom du modèle d'embedding lu depuis params.py plutôt que recopié ici : un
# changement de modèle suit tout seul. Celui du NLI vient du paquet selfcheckgpt,
# lu directement par le script de publication.
RAG_EMBEDDING_MODEL := $(shell python -c "from berlue.params import RAG_EMBEDDING_MODEL; print(RAG_EMBEDDING_MODEL)" 2>/dev/null)

models_bucket_create: gcp_check_cli_auth ## Crée le bucket GCS des modèles s'il n'existe pas déjà (dans BUCKET_PROJECT) — appelé par gcp_setup, doit rester rejouable sans erreur
	@if gcloud storage buckets describe gs://$(MODELS_BUCKET_NAME) --project=$(BUCKET_PROJECT) >/dev/null 2>&1 </dev/null; then \
		echo "✅ Bucket gs://$(MODELS_BUCKET_NAME) déjà présent, création sautée."; \
	else \
		echo "🪣 Création du bucket gs://$(MODELS_BUCKET_NAME)..."; \
		$(RETRY) "création du bucket gs://$(MODELS_BUCKET_NAME)" \
			gcloud storage buckets create gs://$(MODELS_BUCKET_NAME) \
				--location=$(GCP_REGION) \
				--project=$(BUCKET_PROJECT); \
	fi

models_bucket_grant_sa: gcp_check_cli_auth ## Autorise sa-berlue à lire le bucket de modèles — requis par le volume GCS FUSE des services applicatifs
	@echo "🔐 Lecture pour $(CLOUDRUN_SA_EMAIL) sur gs://$(MODELS_BUCKET_NAME)..."
	@$(RETRY) "autorisation de $(CLOUDRUN_SA_EMAIL) sur gs://$(MODELS_BUCKET_NAME)" \
		gcloud storage buckets add-iam-policy-binding gs://$(MODELS_BUCKET_NAME) \
			--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
			--role="roles/storage.objectViewer"

models_bucket_delete: ## Supprime le bucket de modèles et tout son contenu (appelé par gcp_destroy)
	@echo "💣 Suppression du bucket gs://$(MODELS_BUCKET_NAME)..."
	gcloud storage rm --recursive gs://$(MODELS_BUCKET_NAME)

# Les services partent avec HF_HUB_OFFLINE=1 : un cache absent ne dégénère pas
# en téléchargement silencieux de 2 Go par démarrage à froid, il échoue. Autant
# le détecter au déploiement plutôt que dans les logs Cloud Run. Prérequis des
# déploiements applicatifs, jamais appelé directement.
_models_check:
	@gcloud storage ls gs://$(MODELS_BUCKET_NAME)/hub/ >/dev/null 2>&1 </dev/null || { \
		echo "❌ Cache de modèles introuvable : gs://$(MODELS_BUCKET_NAME)/hub/"; \
		echo "   Les services partent avec HF_HUB_OFFLINE=1 : sans lui, le premier"; \
		echo "   appel échouerait au lieu de télécharger."; \
		echo "   👉 make models_push"; \
		exit 1; \
	}

models_push: gcp_check_cli_auth ## Publie les poids des modèles du pipeline dans gs://MODELS_BUCKET_NAME (~2 Go, à refaire seulement si un modèle change)
	@bash scripts/models_push.sh $(MODELS_BUCKET_NAME) $(RAG_EMBEDDING_MODEL)

models_content: ## Affiche ce que contient le bucket de modèles
	@echo "🧠 Contenu de gs://$(MODELS_BUCKET_NAME)/hub/ :"
	@gcloud storage ls gs://$(MODELS_BUCKET_NAME)/hub/ 2>/dev/null </dev/null \
		| sed -e 's#gs://$(MODELS_BUCKET_NAME)/hub/#  #' -e 's#/$$##' \
		|| echo "  (bucket vide ou absent)"
