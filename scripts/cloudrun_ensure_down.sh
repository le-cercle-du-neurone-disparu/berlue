#!/usr/bin/env bash
# scripts/cloudrun_ensure_down.sh
#
# S'assure qu'un service Cloud Run ne fait plus tourner d'instance, et le
# SUPPRIME s'il en reste après le délai de grâce.
#
# `min-instances=0` retire la garantie de capacité chaude mais ne tue pas une
# instance déjà démarrée : Cloud Run la garde le temps qu'il juge utile, et
# elle reste facturée (état `idle`). La suppression du service est le seul
# levier qui arrête la facturation à coup sûr — décisif sur berlue-llm, dont
# le GPU L4 coûte ~0,67 $/h.
#
# Le service est recréable sans rebuild : `make cloudrun_deploy_all` (les
# images restent dans Artifact Registry), ou la cible cloudrun_*_deploy
# correspondante pour un seul service.
#
# Usage : scripts/cloudrun_ensure_down.sh <service>
# GCP_PROJECT et GCP_REGION viennent de l'environnement (exportés par le Makefile).
# Réglages : DOWN_GRACE_SECONDS (défaut 30), DOWN_POLL_SECONDS (défaut 10).

set -uo pipefail

: "${GCP_PROJECT:?GCP_PROJECT manquant (lancez via make)}"
: "${GCP_REGION:?GCP_REGION manquant (lancez via make)}"

GRACE="${DOWN_GRACE_SECONDS:-30}"
POLL="${DOWN_POLL_SECONDS:-10}"

if [ "$#" -ne 1 ]; then
    echo "Usage : $0 <service>" >&2
    exit 2
fi

service="$1"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! gcloud run services describe "$service" \
    --region "$GCP_REGION" --project "$GCP_PROJECT" \
    --format="value(status.url)" >/dev/null 2>&1 </dev/null; then
    exit 0
fi

elapsed=0
while :; do
    count=$(bash "$here/cloudrun_instances.sh" "$service")
    if [ "$count" = "0" ]; then
        echo "   ✅ $service : plus aucune instance en vie."
        exit 0
    fi
    if [ "$elapsed" -ge "$GRACE" ]; then
        break
    fi
    echo "   ⏳ $service : $count instance(s) encore en vie, nouvelle vérification dans ${POLL}s (${elapsed}/${GRACE}s)..."
    sleep "$POLL"
    elapsed=$((elapsed + POLL))
done

echo "   🗑️  $service : toujours $count instance(s) après ${GRACE}s — suppression du service (seul arrêt garanti)."
gcloud run services delete "$service" \
    --region "$GCP_REGION" --project "$GCP_PROJECT" \
    --quiet </dev/null >/dev/null 2>&1 \
    && echo "   ✅ $service supprimé (recréable sans rebuild : make cloudrun_deploy_all)." \
    || echo "   ❌ $service : suppression échouée, à traiter à la main."
