#!/usr/bin/env bash
# scripts/gcp_doctor.sh
#
# Vérifie brique par brique que l'infra GCP provisionnée par `make gcp_setup`
# est réellement utilisable — pas seulement que les commandes de création
# n'ont pas protesté. Ne s'arrête jamais à la première erreur : on veut la
# liste complète de ce qui manque, pas la première marche ratée.
#
# Lancé automatiquement en fin de `make gcp_setup`, ou seul : `make gcp_doctor`.
# Toute la configuration vient de l'environnement (le Makefile racine exporte
# ses variables) — ce script n'est pas prévu pour un appel direct.

set -uo pipefail

: "${GCP_PROJECT:?GCP_PROJECT manquant (lancez via make gcp_doctor)}"
: "${GCP_REGION:?GCP_REGION manquant (lancez via make gcp_doctor)}"
ARTIFACT_PROJECT="${ARTIFACT_PROJECT:-$GCP_PROJECT}"
BUCKET_PROJECT="${BUCKET_PROJECT:-$GCP_PROJECT}"

FAILURES=0
WARNINGS=0

ok()   { echo "  ✅ $1"; }
ko()   { echo "  ❌ $1"; FAILURES=$((FAILURES + 1)); }
warn() { echo "  ⚠️  $1"; WARNINGS=$((WARNINGS + 1)); }

# probe "<libellé>" <commande...> — ✅ si la commande réussit, ❌ sinon.
probe() {
    local label="$1"
    shift
    if "$@" >/dev/null 2>&1 </dev/null; then
        ok "$label"
    else
        ko "$label refusé(e)"
    fi
}

echo "🩺 Diagnostic de l'infra GCP — projet $GCP_PROJECT ($GCP_REGION)"
echo ""

# --- Session et projet -------------------------------------------------------
echo "Session"
ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -n1)"
if [ -n "$ACCOUNT" ]; then
    ok "compte actif : $ACCOUNT"
else
    ko "aucun compte gcloud actif — make gcp_auth"
fi

# --- API ---------------------------------------------------------------------
# Une seule requête pour toutes : `gcloud services list` est lent, et il y a
# une dizaine d'API à contrôler.
echo ""
echo "API"
ENABLED="$(gcloud services list --enabled --project="$GCP_PROJECT" --format='value(config.name)' 2>/dev/null </dev/null)"
if [ -z "$ENABLED" ]; then
    ko "impossible de lister les API activées sur $GCP_PROJECT"
else
    for api in run.googleapis.com firestore.googleapis.com bigquery.googleapis.com compute.googleapis.com; do
        if echo "$ENABLED" | grep -qx "$api"; then
            ok "$api"
        else
            ko "$api désactivée — make gcp_enable_apis"
        fi
    done
fi
if gcloud services list --enabled --project="$ARTIFACT_PROJECT" --format='value(config.name)' 2>/dev/null </dev/null \
    | grep -qx artifactregistry.googleapis.com; then
    ok "artifactregistry.googleapis.com (dans $ARTIFACT_PROJECT)"
else
    ko "artifactregistry.googleapis.com désactivée dans $ARTIFACT_PROJECT — make artifact_registry_enable_api"
fi

# --- Existence des ressources -------------------------------------------------
echo ""
echo "Ressources de l'éval"
if gcloud firestore databases describe --database='(default)' --project="$GCP_PROJECT" >/dev/null 2>&1 </dev/null; then
    ok "base Firestore (default) présente"
else
    ko "base Firestore (default) absente — make firestore_create_database"
fi
if bq --headless show --project_id="$GCP_PROJECT" "${BQ_DATASET:-berlue}" >/dev/null 2>&1 </dev/null; then
    ok "dataset BigQuery ${BQ_DATASET:-berlue} présent"
else
    ko "dataset BigQuery ${BQ_DATASET:-berlue} absent — make bigquery_create_dataset"
fi

# --- Identité testée : sa-berlue, pas vous -------------------------------------
# Firestore et BigQuery sont toujours lus/écrits en impersonant sa-berlue, en
# local comme sur Cloud Run (cf. berlue/evaluation/gcp_result_store.py et
# docs/gcp/auth.md). Sonder avec le compte humain ne dit donc rien d'utile :
# un Owner passe même sans que sa-berlue ait ses droits, et quelqu'un sans
# accès direct échoue alors que l'éval fonctionnerait très bien.
echo ""
echo "Accès de ${CLOUDRUN_SA_EMAIL:-sa-berlue} (l'identité qui compte au runtime)"
if gcloud iam service-accounts describe "$CLOUDRUN_SA_EMAIL" --project="$GCP_PROJECT" >/dev/null 2>&1 </dev/null; then
    ok "compte de service présent"
else
    ko "compte de service absent — make iam_setup_cloudrun_service_account"
fi
SA_TOKEN=$(gcloud auth print-access-token \
    --impersonate-service-account="$CLOUDRUN_SA_EMAIL" 2>/dev/null </dev/null || true)

if [ -z "$SA_TOKEN" ]; then
    ko "impersonation impossible — sondes Firestore/BigQuery non exécutées (make iam_setup_cloudrun_service_account)"
else
    ok "impersonation (roles/iam.serviceAccountTokenCreator)"

    FS_URL="https://firestore.googleapis.com/v1/projects/${GCP_PROJECT}/databases/(default)/documents/_access_probe/probe"
    code=$(curl -s -o /dev/null -w "%{http_code}" "$FS_URL" -H "Authorization: Bearer $SA_TOKEN")
    case "$code" in
        200|404) ok "Firestore : lecture (http $code)" ;;
        *)       ko "Firestore : lecture refusée (http $code)" ;;
    esac

    code=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH "$FS_URL" \
        -H "Authorization: Bearer $SA_TOKEN" -H "Content-Type: application/json" \
        -d '{"fields": {"ok": {"booleanValue": true}}}')
    if [ "$code" = "200" ]; then
        curl -s -X DELETE "$FS_URL" -H "Authorization: Bearer $SA_TOKEN" >/dev/null
        ok "Firestore : écriture"
    else
        ko "Firestore : écriture refusée (http $code)"
    fi

    BQ_API="https://bigquery.googleapis.com/bigquery/v2/projects/${GCP_PROJECT}"
    code=$(curl -s -o /dev/null -w "%{http_code}" \
        "${BQ_API}/datasets/${BQ_DATASET:-berlue}" -H "Authorization: Bearer $SA_TOKEN")
    if [ "$code" = "200" ]; then
        ok "BigQuery : lecture du dataset ${BQ_DATASET:-berlue}"
    else
        ko "BigQuery : lecture refusée (http $code)"
    fi

    # Écriture ET exécution de requête d'un coup : dataEditor seul ne suffit
    # pas à lancer un job, il faut aussi jobUser (cf. iam_setup_cloudrun_service_account).
    probe_sql="CREATE OR REPLACE TABLE \`${GCP_PROJECT}.${BQ_DATASET:-berlue}._access_probe\` AS SELECT 1 AS ok"
    code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BQ_API}/queries" \
        -H "Authorization: Bearer $SA_TOKEN" -H "Content-Type: application/json" \
        -d "{\"query\": \"${probe_sql}\", \"useLegacySql\": false}")
    if [ "$code" = "200" ]; then
        curl -s -o /dev/null -X POST "${BQ_API}/queries" \
            -H "Authorization: Bearer $SA_TOKEN" -H "Content-Type: application/json" \
            -d "{\"query\": \"DROP TABLE \\\`${GCP_PROJECT}.${BQ_DATASET:-berlue}._access_probe\\\`\", \"useLegacySql\": false}"
        ok "BigQuery : écriture et exécution de requête"
    else
        ko "BigQuery : écriture refusée (http $code)"
    fi
fi

# --- Artifact Registry -------------------------------------------------------
echo ""
echo "Artifact Registry (images Docker)"
if gcloud artifacts repositories describe "${ARTIFACTSREPO:-berlue-repo}" \
    --location="$GCP_REGION" --project="$ARTIFACT_PROJECT" >/dev/null 2>&1 </dev/null; then
    ok "dépôt ${ARTIFACTSREPO:-berlue-repo} présent dans $ARTIFACT_PROJECT"
else
    ko "dépôt ${ARTIFACTSREPO:-berlue-repo} absent — make artifact_registry_create"
fi
if ! command -v docker >/dev/null 2>&1; then
    warn "docker non installé — build/push impossibles (sans effet sur l'éval)"
elif grep -q "$GCP_REGION-docker.pkg.dev" "${HOME}/.docker/config.json" 2>/dev/null; then
    ok "authentification Docker configurée pour $GCP_REGION-docker.pkg.dev"
else
    ko "docker non authentifié auprès d'Artifact Registry — make docker_auth"
fi

# --- Bucket RAG --------------------------------------------------------------
echo ""
echo "Bucket RAG"
if gcloud storage buckets describe "gs://${RAG_BUCKET_NAME}" --project="$BUCKET_PROJECT" >/dev/null 2>&1 </dev/null; then
    ok "gs://${RAG_BUCKET_NAME} présent"
    version="${RAG_CORPUS_VERSION:-full-145k}"
    if gcloud storage ls "gs://${RAG_BUCKET_NAME}/faiss/${version}/index.faiss" >/dev/null 2>&1 </dev/null; then
        ok "index RAG présent pour RAG_CORPUS_VERSION=${version}"
    else
        # Un "faiss/ non vide" ne suffit pas : cloudrun_deploy monte un
        # sous-dossier précis, et l'API ne démarre pas si c'est le mauvais.
        warn "aucun index pour RAG_CORPUS_VERSION=${version} — l'API ne démarrera pas"
        present=$(gcloud storage ls "gs://${RAG_BUCKET_NAME}/faiss/" 2>/dev/null </dev/null \
            | sed -e 's#.*/faiss/##' -e 's#/$##' | tr '\n' ' ')
        echo "      versions présentes : ${present:-aucune}"
    fi
else
    ko "gs://${RAG_BUCKET_NAME} absent — make rag_bucket_create"
fi

# --- Bucket de code ----------------------------------------------------------
# L'image applicative ne contient pas le code : sans ce bucket, ni l'API ni le
# service d'éval ne démarrent (cf. docs/gcp/code-en-bucket.md).
echo ""
echo "Bucket de code"
if gcloud storage buckets describe "gs://${CODE_BUCKET_NAME}" --project="$BUCKET_PROJECT" >/dev/null 2>&1 </dev/null; then
    ok "gs://${CODE_BUCKET_NAME} présent"
    code_version="${CODE_VERSION:-current}"
    if gcloud storage ls "gs://${CODE_BUCKET_NAME}/${code_version}/berlue/params.py" >/dev/null 2>&1 </dev/null; then
        ok "code publié pour CODE_VERSION=${code_version}"
    else
        warn "aucun code pour CODE_VERSION=${code_version} — les services ne démarreront pas (make code_push)"
        present=$(gcloud storage ls "gs://${CODE_BUCKET_NAME}/" 2>/dev/null </dev/null \
            | sed -e "s#.*/${CODE_BUCKET_NAME}/##" -e 's#/$##' | tr '\n' ' ')
        echo "      versions présentes : ${present:-aucune}"
    fi
else
    ko "gs://${CODE_BUCKET_NAME} absent — make code_bucket_create"
fi

# --- Bucket de modèles -------------------------------------------------------
# Les services partent avec HF_HUB_OFFLINE=1 : sans ce cache, le premier appel
# échoue au lieu de télécharger 2 Go en pleine requête.
if gcloud storage buckets describe "gs://${MODELS_BUCKET_NAME}" --project="$BUCKET_PROJECT" >/dev/null 2>&1 </dev/null; then
    ok "gs://${MODELS_BUCKET_NAME} présent"
    if gcloud storage ls "gs://${MODELS_BUCKET_NAME}/hub/" >/dev/null 2>&1 </dev/null; then
        ok "cache HuggingFace publié"
    else
        ko "cache HuggingFace vide — make models_push"
    fi
else
    ko "gs://${MODELS_BUCKET_NAME} absent — make models_bucket_create"
fi

# --- Verdict -----------------------------------------------------------------
echo ""
if [ "$FAILURES" -eq 0 ]; then
    echo "✅ Infra GCP prête ($WARNINGS avertissement(s))."
else
    echo "❌ $FAILURES problème(s) — relancez la commande indiquée, puis 'make gcp_doctor'."
fi

cat <<'MANUEL'

Reste à faire à la main (volontairement hors de gcp_setup) :
  1. Quota GPU — un projet neuf a 0 en "Total Nvidia L4 GPU allocation, per
     project per region" (europe-west1). cloudrun_llm_deploy échouera tant
     que la demande n'est pas accordée (console GCP, délai possible de
     plusieurs heures) : à demander tôt.
  2. Images + services : make gcp_deploy          (CLOUDRUN_ENV=test par défaut)
     Puis pour allumer  : make gcp_up      WARM_MODELS="llama3.1:8b"   (API + LLM)
                          make gcp_eval_up WARM_MODELS="llama3.1:8b"   (eval + LLM)
     et toujours        : make gcp_down    (les 3 a 0 — coût, cf. docs/gcp/cloudrun.md)
  3. Index RAG: make download_fever_data_full && make build_fever_index && make rag_index_upload
  4. Code applicatif : make code_push (puis make code_deploy à chaque changement
     de Python — aucun rebuild d'image, cf. docs/gcp/code-en-bucket.md)
MANUEL

[ "$FAILURES" -eq 0 ]
