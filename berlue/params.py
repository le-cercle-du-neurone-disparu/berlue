import os

from berlue.prompts import EXTRACT_SYSTEM_PROMPT as _EXTRACT_SYSTEM_PROMPT
from berlue.prompts import OLLAMA_SYSTEM_PROMPT as _OLLAMA_SYSTEM_PROMPT
from berlue.prompts import RAG_SYSTEM_PROMPT as _RAG_SYSTEM_PROMPT

##################  VARIABLES (paramétrables via .env : diffèrent par personne/environnement)  ##################
DATA_SIZE = os.environ.get("DATA_SIZE")

# USE_MOCK : sert la pipeline mockée (berlue/mocks/) plutôt que le vrai modèle sur
# l'API — pratique pour développer/tester le front sans dépendre d'un modèle
# entraîné. Défaut "0" (désactivé).
USE_MOCK = bool(int(os.environ.get("USE_MOCK", "0")))

# GCP : identité du projet de chacun + secrets/emplacements propres à la machine
GCP_PROJECT = os.environ.get("GCP_PROJECT")

# Bucket : unique GLOBALEMENT sur GCP, jamais un nom fixe littéral. Reconstruit à
# partir du projet de chacun + un nom commun + un suffixe (cf. .env.sample) —
# même formule que BUCKET_NAME dans le Makefile.
BUCKET_SUFFIX = os.environ.get("BUCKET_SUFFIX", "1")
BUCKET_NAME = f"{GCP_PROJECT}-berlue_{BUCKET_SUFFIX}"

# Notifications : secret (URL de webhook)
NOTIFY_BASE_URL = os.environ.get("NOTIFY_BASE_URL")

# RUN_ENV : quel environnement pour `make run_*` (local/docker/gcp) — pilote aussi
# MLFLOW_TRACKING_URI ci-dessous. Défaut "local".
RUN_ENV = os.environ.get("RUN_ENV", "local")

# MODEL_TARGET se règle en ligne de commande, pas dans .env — cf. make/pipeline.mk
# (ex: `make run_train MODEL_TARGET=gcs`). Défaut "local".
MODEL_TARGET = os.environ.get("MODEL_TARGET", "local")
assert MODEL_TARGET in ("local", "gcs", "mlflow"), (
    f"❌ MODEL_TARGET invalide : {MODEL_TARGET!r} (doit être local, gcs ou mlflow)"
)

# LOG_LEVEL : niveau de log par défaut pour tout le package (cf.
# berlue.logging_config.setup_logging) — surchargeable en ligne de commande
# (--log-level) sur les scripts qui l'exposent. Défaut "INFO".
LOG_LEVEL = os.environ.get("BERLUE_LOG_LEVEL", "INFO")
assert LOG_LEVEL in ("ERROR", "WARNING", "INFO", "DEBUG"), (
    f"❌ LOG_LEVEL invalide : {LOG_LEVEL!r} (doit être ERROR, WARNING, INFO ou DEBUG)"
)

# EVAL_RUN_TARGET : où le service d'évaluation s'exécute (local ou GCP, ex.
# Cloud Run Job) — indépendant d'EVAL_STORE_TARGET (où sont stockés les
# résultats), sauf contrainte dans un seul sens ci-dessous.
EVAL_RUN_TARGET = os.environ.get("BERLUE_EVAL_RUN_TARGET", "local")
assert EVAL_RUN_TARGET in ("local", "gcp"), (
    f"❌ EVAL_RUN_TARGET invalide : {EVAL_RUN_TARGET!r} (doit être local ou gcp)"
)

# EVAL_STORE_TARGET : où sont stockés les résultats d'évaluation (cache de
# prédictions + matrices finales) — indépendant d'où le calcul s'exécute
# (contrairement à MODEL_TARGET/RUN_ENV). "gcp" = Firestore (résultats
# individuels) + BigQuery (matrices), cf. docs/evaluation/storage.md.
EVAL_STORE_TARGET = os.environ.get("BERLUE_EVAL_STORE_TARGET", "local")
assert EVAL_STORE_TARGET in ("local", "gcp"), (
    f"❌ EVAL_STORE_TARGET invalide : {EVAL_STORE_TARGET!r} (doit être local ou gcp)"
)

# EVAL_FIRESTORE_PROJECT/EVAL_BIGQUERY_PROJECT : projet GCP par service, pas
# un seul GCP_PROJECT qui piloterait tout — une équipe de plusieurs devs,
# chacun avec son propre projet, doit pouvoir pointer vers le cache déjà
# rempli par un collègue sur l'un ou l'autre service indépendamment. Défaut :
# son propre GCP_PROJECT (comportement inchangé si non précisé).
EVAL_FIRESTORE_PROJECT = os.environ.get("BERLUE_EVAL_FIRESTORE_PROJECT", GCP_PROJECT)
EVAL_BIGQUERY_PROJECT = os.environ.get("BERLUE_EVAL_BIGQUERY_PROJECT", GCP_PROJECT)

# EVAL_SERVICE_ACCOUNT : identité utilisée pour s'authentifier auprès de
# Firestore/BigQuery (GcpResultStore) — impersonation systématique du
# service account dédié plutôt que la session gcloud CLI de la personne
# directement, en local comme en exécution GCP. Mêmes droits partout : ce
# qui tourne en local est borné aux mêmes permissions que ce qui tournera
# une fois déployé, jamais plus large. Toujours dans son propre GCP_PROJECT
# (jamais EVAL_FIRESTORE_PROJECT/EVAL_BIGQUERY_PROJECT, qui peuvent pointer
# vers le projet d'un collègue) — nécessite `roles/iam.serviceAccountTokenCreator`
# sur ce SA (cf. `make gcp_setup`, docs/gcp/auth.md).
_EVAL_SERVICE_ACCOUNT_NAME = os.environ.get("BERLUE_EVAL_SERVICE_ACCOUNT_NAME", "sa-berlue")
EVAL_SERVICE_ACCOUNT = os.environ.get("BERLUE_EVAL_SERVICE_ACCOUNT") or (
    f"{_EVAL_SERVICE_ACCOUNT_NAME}@{GCP_PROJECT}.iam.gserviceaccount.com" if GCP_PROJECT else None
)

# Contrainte dans un seul sens : exécution GCP -> stockage GCP obligatoire
# (pas de local persistant/partagé dans un container Cloud Run). L'inverse
# est libre : exécution locale -> stockage local OU gcp au choix.
assert not (EVAL_RUN_TARGET == "gcp" and EVAL_STORE_TARGET != "gcp"), (
    "❌ EVAL_RUN_TARGET=gcp exige EVAL_STORE_TARGET=gcp "
    f"(reçu EVAL_STORE_TARGET={EVAL_STORE_TARGET!r}) — pas de stockage local persistant en exécution GCP."
)

# MLflow : le serveur de tracking dépend de RUN_ENV.
# TODO: pas encore de serveur MLflow partagé pour "gcp".
_MLFLOW_TRACKING_URIS = {
    "local": "http://localhost:5000",
    "docker": "http://localhost:5000",
    "gcp": None,
}
MLFLOW_TRACKING_URI = _MLFLOW_TRACKING_URIS.get(RUN_ENV, "http://localhost:5000")

##################  PIPELINE BERLUE (LLM local, RAG inversé, SelfCheckGPT)  ##################

# --- LLM (Ollama) ---
OLLAMA_HOST = os.environ.get("BERLUE_OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("BERLUE_OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_SYSTEM_PROMPT = _OLLAMA_SYSTEM_PROMPT
BASE_TEMPERATURE = float(os.environ.get("BERLUE_BASE_TEMPERATURE", "0.0"))

# --- EXTRACTION ---
# Extraction et RAG tournent sur un modèle plus gros que celui évalué : ce sont
# les deux étages qui doivent COMPRENDRE (découper une réponse en affirmations,
# juger une affirmation), pas produire. 8B est le compromis retenu — pas un qwen,
# décevant sur ces deux tâches à l'essai, et pas un 14B, qui portait une requête
# /predict de trois affirmations à 6 min 24 sur Cloud Run.
EXTRACT_MODEL = os.environ.get("EXTRACT_MODEL", "llama3.1:8b")
# EXTRACT_MODEL = os.environ.get("EXTRACT_MODEL", "qwen2.5:0.5b")
EXTRACT_SYSTEM_PROMPT = _EXTRACT_SYSTEM_PROMPT

# --- SELFCHECK ---
SELFCHECK_K = int(os.environ.get("BERLUE_SELFCHECK_K", "5"))
SELFCHECK_TEMPERATURE_MIN = float(os.environ.get("BERLUE_SELFCHECK_TEMPERATURE_MIN", "0.3"))
SELFCHECK_TEMPERATURE_MAX = float(os.environ.get("BERLUE_SELFCHECK_TEMPERATURE_MAX", "1.0"))

# --- JUGE (évaluation d'une réponse générée contre les réponses de référence
# du dataset) : modèle dédié, indépendant de OLLAMA_MODEL, pour comparer
# plusieurs modèles sous test à juge constant. 7B minimum — en dessous, le
# juge valide quasi systématiquement (cf. docs/evaluation/model-comparison-notes.md).
JUDGE_MODEL = os.environ.get("BERLUE_JUDGE_MODEL", "llama3.1:8b")

# --- Embeddings + RAG inversé ---
RAG_EMBEDDING_MODEL = "all-mpnet-base-v2"
RAG_INDEX_DIR = "data/fever/faiss"
# Surchargeable pour pointer vers un volume monté (ex. GCS FUSE sur Cloud
# Run, cf. docs/gcp/cloudrun.md) plutôt que le chemin local par défaut.
RAG_VECTOR_DB_PATH = os.environ.get("RAG_VECTOR_DB_PATH", "data/fever/faiss")
RAG_MODEL = os.environ.get("RAG_MODEL", "llama3.1:8b")
RAG_SYSTEM_PROMPT = _RAG_SYSTEM_PROMPT

# --- NLI léger ---
NLI_MODEL = os.environ.get("BERLUE_NLI_MODEL", "microsoft/deberta-v3-small")
NLI_BASELINE_PATH = os.environ.get("BERLUE_NLI_BASELINE_PATH", "./models/nli_tfidf_logreg.joblib")

# --- Données ---
FEVER_DATA_PATH = os.environ.get("BERLUE_FEVER_DATA_PATH", "./data/fever/raw/fever.jsonl")

# EVAL_DATASETS : quel(s) jeu(x) de données labellisés utiliser pour l'évaluation
# offline (entraînement du baseline NLI + jeu de test, cf. evaluation/data.py) —
# "halueval", "truthfulqa", ou les deux. Pratique pour itérer sur un seul dataset
# à la fois sans toucher au code. Défaut : les deux.
_EVAL_DATASETS_RAW = os.environ.get("BERLUE_EVAL_DATASETS", "halueval,truthfulqa")
EVAL_DATASETS = [d.strip() for d in _EVAL_DATASETS_RAW.split(",") if d.strip()]

# TRAIN_RATIO : proportion des questions uniques allouée au train par
# `evaluation.data.split_train_test` (le reste va au test). Défaut : 0.8 (80% train
# / 20% test).
TRAIN_RATIO = float(os.environ.get("BERLUE_TRAIN_RATIO", "0.8"))

# --- MLOps ---
MLOPS_DB_PATH = os.environ.get("BERLUE_MLOPS_DB_PATH", "./data/mlops/hallucination_tracker.db")

# --- Bornes de génération (num_predict) ---
# Sans borne, un modèle qui ignore la consigne de longueur génère jusqu'à saturer
# `n_ctx_slot` (4096 sur nos serveurs) puis enchaîne les *context shifts*, chacun
# coûtant plusieurs secondes : un seul appel dépasse alors le timeout client et fait
# tomber le run entier. Constaté deux fois — sur GCP (bloqué à 97/100) et en local
# (91/300).
#
# Les valeurs sont dimensionnées sur les longueurs réellement produites (mesurées sur
# 30 traces, ~4 caractères par token), avec une marge large : la sécurité ne dépend pas
# de leur précision, seulement du fait d'être nettement sous `n_ctx`. Une borne trop
# serrée tronquerait un JSON en plein milieu — d'où l'avertissement émis par
# `OllamaClient.generate` quand la borne est atteinte.
#
#   réponse et échantillons : max observé 126  -> 300 (valeur déjà retenue en mode généré)
#   extraction              : max observé  35  -> 400 (la réponse brute peut préambuler)
#   RAG                     : max observé 172  -> 600 (le raisonnement peut s'allonger)
NUM_PREDICT_ANSWER = int(os.environ.get("BERLUE_NUM_PREDICT_ANSWER", "300"))
NUM_PREDICT_EXTRACTION = int(os.environ.get("BERLUE_NUM_PREDICT_EXTRACTION", "400"))
NUM_PREDICT_RAG = int(os.environ.get("BERLUE_NUM_PREDICT_RAG", "600"))

# --- Fusion des scores ---
# Fonctionnel de référence : claude-doc/specification-fusion-2026-09-02.md.
#
# Poids d'arbitrage quand le RAG et SelfCheck se contredisent (règle R5). C'est le
# chemin principal, pas un cas limite : FEVER ne tranche que 0,3 % des affirmations
# de nos jeux, donc hors preuve documentaire la décision se joue entre deux sources
# — la conviction propre du modèle du RAG, et SelfCheck.
#
# Objectif : 50/50 d'influence GLOBALE entre les deux, pas direction par direction.
#
# Côté décharge, SelfCheck est bridé par nécessité : pour qu'un RAG catégorique
# « c'est faux » reste CONTREDIT face à un modèle parfaitement stable —
# l'hallucination stable, le cas d'usage du projet — il faut
#
#     (0·RAG + décharge·0,95) / (RAG + décharge) < FUSION_SEUIL_FAUX
#     soit  décharge < 0,727 · RAG,  donc < 0,36 ici.
#
# Sa part y plafonne donc à 41 %. Le poids à charge compense au-dessus de 50 % pour
# que la moyenne des deux revienne à 50 : 56,5 % à charge, 41,2 % à décharge, soit
# 48,8 % en moyenne. C'est le réglage le plus proche d'un vrai 50/50 sans franchir
# la falaise mesurée à charge = 0,75, où le taux d'accusation sur les réponses
# VRAIES saute de 38 % à 56 % sans que la séparation progresse.
#
# Pondérer par la fréquence réelle des deux directions (87 % d'accusations) aurait
# été trompeur : cette proportion vient de la saturation de SelfCheck avec le 1b,
# la figer dans le réglage reviendrait à inscrire un défaut dans la formule.
#
# `test_hallucination_stable_est_contredite` et
# `test_la_decharge_ne_peut_pas_annuler_un_jugement_categorique` gardent la limite.
#
# Mesuré : ce rééquilibrage ne change aucun verdict sur les données actuelles. Il
# prendra effet quand SelfCheck cessera d'être saturé (divergence médiane 0,95 avec
# llama3.2:1b, 0,51 avec le 3b).
FUSION_WEIGHT_RAG = float(os.environ.get("BERLUE_FUSION_WEIGHT_RAG", "0.5"))
# Poids de SelfCheck, asymétrique : une divergence forte est un signal plus
# informatif qu'une divergence faible. Se contredire n'a qu'une lecture (le modèle
# ne sait pas) ; être cohérent en a deux (il sait, ou il se trompe avec constance).
# La cohérence ne peut donc pas peser autant que l'incohérence.
FUSION_WEIGHT_SELFCHECK_CHARGE = float(os.environ.get("BERLUE_FUSION_WEIGHT_SELFCHECK_CHARGE", "0.65"))
FUSION_WEIGHT_SELFCHECK_DECHARGE = float(os.environ.get("BERLUE_FUSION_WEIGHT_SELFCHECK_DECHARGE", "0.35"))

# Divergence à laquelle SelfCheck est neutre : en deçà il penche vers le vrai,
# au-delà vers le faux. À calibrer sur la distribution réelle des divergences ;
# 0.5 reproduit le `1 - divergence` historique.
FUSION_DIVERGENCE_NEUTRE = float(os.environ.get("BERLUE_FUSION_DIVERGENCE_NEUTRE", "0.5"))

# Bande dans laquelle le jugement du RAG est trop faible pour conclure (règle R3) :
# SelfCheck y décide seul, mais seulement si son signal est franc.
FUSION_BANDE_RAG_MIN = float(os.environ.get("BERLUE_FUSION_BANDE_RAG_MIN", "0.4"))
FUSION_BANDE_RAG_MAX = float(os.environ.get("BERLUE_FUSION_BANDE_RAG_MAX", "0.6"))
# Seuils au-delà desquels SelfCheck seul peut trancher. Volontairement extrêmes :
# une divergence moyenne peut venir de la créativité, d'une omission ou des
# températures étalées du protocole d'échantillonnage, pas d'une hallucination.
FUSION_SELFCHECK_SEUIL_HAUT = float(os.environ.get("BERLUE_FUSION_SELFCHECK_SEUIL_HAUT", "0.8"))
FUSION_SELFCHECK_SEUIL_BAS = float(os.environ.get("BERLUE_FUSION_SELFCHECK_SEUIL_BAS", "0.2"))

# Décote appliquée à une conviction qui ne repose que sur SelfCheck : sans elle, une
# conviction d'un seul signal ressortirait plus confiante qu'une conviction corroborée
# par le RAG, et la confiance baisserait quand le RAG devient plus convaincu.
FUSION_DECOTE_SIGNAL_SEUL = float(os.environ.get("BERLUE_FUSION_DECOTE_SIGNAL_SEUL", "0.6"))

# Seuils de classification du score final sur l'axe faux <-> vrai.
FUSION_SEUIL_FAUX = float(os.environ.get("BERLUE_FUSION_SEUIL_FAUX", "0.4"))
FUSION_SEUIL_VRAI = float(os.environ.get("BERLUE_FUSION_SEUIL_VRAI", "0.6"))

##################  CONFIGURATION FIXE (décisions de mainteneur, pas des paramètres .env)  ##################
# Mêmes valeurs pour tout le monde — cf. make/config.mk pour l'équivalent côté Make
# (GCP_REGION, ZONE, BQ_REGION, INSTANCE, SA_NAME, ARTIFACTSREPO, GAR_IMAGE...).
CHUNK_SIZE = 100_000
BQ_DATASET = "berlue"

MLFLOW_EXPERIMENT = "berlue_experiment"
MLFLOW_MODEL_NAME = "berlue_model"
PREFECT_FLOW_NAME = "berlue_main_flow"
PREFECT_LOG_LEVEL = "INFO"
EVALUATION_START_DATE = "2024-01-01"

NOTIFY_CHANNEL = "#berlue-alerts"
NOTIFY_AUTHOR = "Berlue_Pipeline_Bot"

# --- Datasets d'évaluation (HaluEval, TruthfulQA) : source + cache local ---
HALUEVAL_URL = "https://raw.githubusercontent.com/RUCAIBox/HaluEval/main/data/qa_data.json"
HALUEVAL_DATA_PATH = "data/halueval/raw/qa_data.json"

TRUTHFULQA_URL = "https://raw.githubusercontent.com/sylinrl/TruthfulQA/main/TruthfulQA.csv"
TRUTHFULQA_DATA_PATH = "data/truthfulqa/raw/truthfulqa.csv"

# Trois axes de version indépendants pour l'éval — à incrémenter manuellement
# à chaque évolution significative du composant correspondant, pour
# distinguer et pouvoir purger les résultats devenus obsolètes. Quel axe
# s'applique à quelle table : cf. docs/evaluation/storage.md.
PIPELINE_VERSION = "v1"  # logique du pipeline Berlue (RAG inversé + SelfCheckGPT)
GENERATION_VERSION = "v1"  # logique/prompt de génération de réponse par le LLM sous test
EVAL_VERSION = "v1"  # méthodologie d'éval (split train/test, sélection du jeu de test, prompt du juge, matrices)

##################  CONSTANTS  #####################
# 💡 Cette ligne trouve dynamiquement la racine du projet
# (__file__ = params.py -> dirname = ton package -> dirname = racine du projet)
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))

# 💡 On pointe désormais vers les dossiers que nous avons créés dans ton architecture !
LOCAL_DATA_PATH = os.path.join(PROJECT_ROOT, "data")
LOCAL_REGISTRY_PATH = os.path.join(PROJECT_ROOT, "models")

##################  SCHEMA DES DONNEES (TODO)  #################
# TODO: Définir les noms exacts des colonnes du dataset brut (requis pour le schéma BigQuery ou le parsing CSV).
# COLUMN_NAMES_RAW = ['feature_1', 'feature_2', 'target_variable']

# TODO: Imposer les dtypes des données brutes pour optimiser l'usage mémoire (ex. float32 au lieu de float64).
# DTYPES_RAW = {
#     "feature_1": "float32",
#     "feature_2": "int8",
#     "target_variable": "int8"
# }

# TODO: Définir le type de données final pour les matrices après prétraitement.
# DTYPES_PROCESSED = np.float32
