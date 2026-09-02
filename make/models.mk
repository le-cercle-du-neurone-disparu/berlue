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
NLI_MODEL := $(shell python -c "from selfcheckgpt.utils import NLIConfig; print(NLIConfig.nli_model)" 2>/dev/null)
# Noms tels qu'ils apparaissent dans l'arborescence du cache HuggingFace.
MODELS_ATTENDUS := sentence-transformers--$(RAG_EMBEDDING_MODEL) $(subst /,--,$(NLI_MODEL))

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
# Vérifie la présence des POIDS, pas seulement du dossier : un cache où il manque
# un modèle laisse passer le déploiement et casse au premier appel.
_models_check:
	@manquants=""; \
	for m in $(MODELS_ATTENDUS); do \
		gcloud storage ls "gs://$(MODELS_BUCKET_NAME)/hub/models--$$m/**" 2>/dev/null </dev/null \
			| grep -qE '\.(safetensors|bin)$$' || manquants="$$manquants $$m"; \
	done; \
	if [ -n "$$manquants" ]; then \
		echo "❌ Poids absents du cache gs://$(MODELS_BUCKET_NAME)/hub/ :$$manquants"; \
		echo "   Les services partent avec HF_HUB_OFFLINE=1 : sans eux, le premier"; \
		echo "   appel échouerait au lieu de télécharger."; \
		echo "   👉 make models_push"; \
		exit 1; \
	fi

models_push: gcp_check_cli_auth ## Publie les poids des modèles du pipeline dans gs://MODELS_BUCKET_NAME (~2 Go, à refaire seulement si un modèle change)
	@bash scripts/models_push.sh $(MODELS_BUCKET_NAME) $(RAG_EMBEDDING_MODEL)

# Appelé par gcp_deploy : publier 2,2 Go à chaque déploiement serait absurde alors
# que ces poids ne changent qu'au changement de modèle. On ne publie que si le
# bucket est vide — `make models_push` force la republication.
# Pendant de rag_index_import pour les poids HuggingFace (~2,1 Go). Les
# reconstruire suppose de les télécharger depuis HuggingFace puis de matérialiser
# le cache — long, et inutile si un collègue les a déjà publiés.
#
#   make models_import MODELS_SOURCE_BUCKET=<projet-du-collegue>-berlue-models
models_import: gcp_check_cli_auth ## Copie les poids HuggingFace d'un bucket tiers vers le nôtre (MODELS_SOURCE_BUCKET requis)
	@if [ -z "$(MODELS_SOURCE_BUCKET)" ]; then \
		echo "❌ ERREUR : MODELS_SOURCE_BUCKET manquant."; \
		echo "👉 make models_import MODELS_SOURCE_BUCKET=<projet-source>-berlue-models"; \
		exit 1; \
	fi
	@if ! gcloud storage ls "gs://$(MODELS_SOURCE_BUCKET)/" >/dev/null 2>&1 </dev/null; then \
		echo "❌ gs://$(MODELS_SOURCE_BUCKET) introuvable ou illisible."; \
		echo "   👉 Le propriétaire doit vous accorder la lecture : make data_buckets_grant USER=<votre email>"; \
		exit 1; \
	fi
	@echo "📥 Copie de gs://$(MODELS_SOURCE_BUCKET) vers gs://$(MODELS_BUCKET_NAME) (~2,1 Go, de bucket à bucket)..."
	gcloud storage rsync --recursive "gs://$(MODELS_SOURCE_BUCKET)" "gs://$(MODELS_BUCKET_NAME)"
	@echo "✅ Modèles importés. Vérification :"
	@$(MAKE) --no-print-directory _models_check

models_ensure: gcp_check_cli_auth ## Publie les modèles seulement s'ils sont absents du bucket (appelé par gcp_deploy)
	@if gcloud storage ls gs://$(MODELS_BUCKET_NAME)/hub/ >/dev/null 2>&1 </dev/null; then \
		echo "✅ Modèles déjà publiés dans gs://$(MODELS_BUCKET_NAME)/, publication sautée."; \
	else \
		$(MAKE) --no-print-directory models_push; \
	fi

models_content: ## Affiche ce que contient le bucket de modèles
	@echo "🧠 Contenu de gs://$(MODELS_BUCKET_NAME)/hub/ :"
	@gcloud storage ls gs://$(MODELS_BUCKET_NAME)/hub/ 2>/dev/null </dev/null \
		| sed -e 's#gs://$(MODELS_BUCKET_NAME)/hub/#  #' -e 's#/$$##' \
		|| echo "  (bucket vide ou absent)"
