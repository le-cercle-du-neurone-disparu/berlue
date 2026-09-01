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

# --- Firestore ---------------------------------------------------------------
echo ""
echo "Firestore (cache des résultats d'éval)"
if gcloud firestore databases describe --database='(default)' --project="$GCP_PROJECT" >/dev/null 2>&1 </dev/null; then
    ok "base (default) présente"
    probe "lecture"  make --no-print-directory firestore_test_read
    probe "écriture" make --no-print-directory firestore_test_write
else
    ko "base (default) absente — make firestore_create_database"
fi

# --- BigQuery ----------------------------------------------------------------
echo ""
echo "BigQuery (matrices d'éval)"
if bq --headless show --project_id="$GCP_PROJECT" "${BQ_DATASET:-berlue}" >/dev/null 2>&1 </dev/null; then
    ok "dataset ${BQ_DATASET:-berlue} présent"
    probe "lecture"  make --no-print-directory bigquery_test_read
    probe "écriture" make --no-print-directory bigquery_test_write
else
    ko "dataset ${BQ_DATASET:-berlue} absent — make bigquery_create_dataset"
fi

# --- Compte de service -------------------------------------------------------
# L'impersonation est le seul chemin d'auth du runtime (cf. docs/gcp/auth.md) :
# si elle échoue, l'éval en local contre GCP ne marchera pas, quoi que disent
# les autres lignes. Les bindings IAM mettent jusqu'à ~1 min à se propager,
# d'où le retry plutôt qu'un verdict immédiat après un gcp_setup.
echo ""
echo "Compte de service ${CLOUDRUN_SA_EMAIL:-sa-berlue}"
if gcloud iam service-accounts describe "$CLOUDRUN_SA_EMAIL" --project="$GCP_PROJECT" >/dev/null 2>&1 </dev/null; then
    ok "présent"
    IMPERSONATION_OK=0
    for i in 1 2 3 4 5 6; do
        if gcloud auth print-access-token --impersonate-service-account="$CLOUDRUN_SA_EMAIL" >/dev/null 2>&1 </dev/null; then
            IMPERSONATION_OK=1
            break
        fi
        [ "$i" -lt 6 ] && sleep 10
    done
    if [ "$IMPERSONATION_OK" = "1" ]; then
        ok "impersonation (roles/iam.serviceAccountTokenCreator)"
    else
        ko "impersonation refusée après ~1 min — make iam_setup_cloudrun_service_account"
    fi
else
    ko "absent — make iam_setup_cloudrun_service_account"
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
MANUEL

[ "$FAILURES" -eq 0 ]
