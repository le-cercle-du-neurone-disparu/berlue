#!/usr/bin/env bash
# scripts/cloudrun_delete.sh
#
# Supprime un service Cloud Run, sans échouer s'il n'existe pas.
#
# La suppression est le seul arrêt garanti de la facturation : min-instances=0
# retire la garantie de capacité chaude mais ne tue pas une instance déjà
# démarrée, qui passe idle et reste facturée (plein tarif sur berlue-llm, dont
# le GPU impose CPU toujours alloué).
#
# Sans coût caché, vérifié en conditions réelles : l'historique des métriques
# reste consultable dans la console après recréation sous le même nom, et
# l'URL du service est inchangée.
#
# Usage : scripts/cloudrun_delete.sh <service>
# GCP_PROJECT et GCP_REGION viennent de l'environnement (exportés par le Makefile).

set -uo pipefail

: "${GCP_PROJECT:?GCP_PROJECT manquant (lancez via make)}"
: "${GCP_REGION:?GCP_REGION manquant (lancez via make)}"

if [ "$#" -ne 1 ]; then
    echo "Usage : $0 <service>" >&2
    exit 2
fi

service="$1"

if ! gcloud run services describe "$service" \
    --region "$GCP_REGION" --project "$GCP_PROJECT" \
    --format="value(status.url)" >/dev/null 2>&1 </dev/null; then
    echo "   ✅ $service : déjà absent."
    exit 0
fi

echo "   🗑️  $service : suppression..."
if gcloud run services delete "$service" \
    --region "$GCP_REGION" --project "$GCP_PROJECT" \
    --quiet </dev/null >/dev/null 2>&1; then
    echo "   ✅ $service supprimé."
else
    echo "   ❌ $service : suppression échouée, à traiter à la main."
    exit 1
fi
