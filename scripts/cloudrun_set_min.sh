#!/usr/bin/env bash
# scripts/cloudrun_set_min.sh
#
# Passe un service Cloud Run à min-instances=<n>, en ne faisant rien (et sans
# échouer) s'il n'existe pas encore.
#
# Pourquoi : gcp_up, gcp_eval_up et gcp_down agissent sur trois services, mais
# rien n'oblige les trois à être déployés (on peut n'avoir que l'éval). Un
# `gcloud run services update` nu échoue sur un service absent et interrompt
# la série, laissant les suivants intacts. Côté gcp_down c'est un risque de
# facturation : un service resté à min-instances=1 faute d'avoir été traité.
#
# Usage : scripts/cloudrun_set_min.sh <service> <min-instances> [args gcloud...]
# GCP_PROJECT et GCP_REGION viennent de l'environnement (exportés par le Makefile).

set -uo pipefail

: "${GCP_PROJECT:?GCP_PROJECT manquant (lancez via make)}"
: "${GCP_REGION:?GCP_REGION manquant (lancez via make)}"

if [ "$#" -lt 2 ]; then
    echo "Usage : $0 <service> <min-instances> [args gcloud...]" >&2
    exit 2
fi

service="$1"
min="$2"
shift 2

current=$(gcloud run services describe "$service" \
    --region "$GCP_REGION" --project "$GCP_PROJECT" \
    --format="value(spec.template.metadata.annotations['"'"'autoscaling.knative.dev/minScale'"'"'])" \
    2>/dev/null </dev/null) || {
    echo "   ⚠️  $service n'existe pas — ignoré (make gcp_deploy pour le créer)."
    exit 0
}

# `services update` crée une révision même quand rien ne change : sans réglage
# supplémentaire à appliquer, une valeur déjà correcte n'a pas à repayer un
# déploiement complet (~1 min) ni à gonfler l'historique de révisions.
if [ "$#" -eq 0 ] && [ "${current:-0}" = "$min" ]; then
    echo "   ✅ $service : déjà à min-instances=$min"
    exit 0
fi

echo "   🔧 $service : min-instances=$min"
gcloud run services update "$service" \
    --region "$GCP_REGION" --project "$GCP_PROJECT" \
    --min-instances="$min" "$@" </dev/null >/dev/null
