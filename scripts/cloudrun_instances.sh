#!/usr/bin/env bash
# scripts/cloudrun_instances.sh
#
# Nombre d'instances Cloud Run réellement en vie pour un service (0 si aucune,
# 0 aussi si le service n'existe pas). Écrit le nombre sur stdout.
#
# Somme les états `active` ET `idle` : une instance idle est démarrée et
# facturée, elle ne traite simplement aucune requête — ne regarder que
# `active` fait conclure à tort qu'un service est éteint. L'agrégation est
# faite côté serveur (REDUCE_SUM groupé par service) pour couvrir toutes les
# révisions d'un coup.
#
# L'API Monitoring n'a pas d'équivalent `gcloud` (pas de `gcloud monitoring
# time-series list`), d'où l'appel REST direct.
#
# Usage : scripts/cloudrun_instances.sh <service>
# GCP_PROJECT vient de l'environnement (exporté par le Makefile).

set -uo pipefail

: "${GCP_PROJECT:?GCP_PROJECT manquant (lancez via make)}"

if [ "$#" -ne 1 ]; then
    echo "Usage : $0 <service>" >&2
    exit 2
fi

service="$1"
token=$(gcloud auth print-access-token 2>/dev/null </dev/null) || {
    echo "0"
    exit 0
}

# Fenêtre large côté début, la métrique étant échantillonnée chaque minute ;
# seul le point le plus récent est retenu ensuite.
start=$(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
end=$(date -u +%Y-%m-%dT%H:%M:%SZ)

curl -sG "https://monitoring.googleapis.com/v3/projects/${GCP_PROJECT}/timeSeries" \
    -H "Authorization: Bearer ${token}" \
    --data-urlencode "filter=metric.type=\"run.googleapis.com/container/instance_count\" AND resource.labels.service_name=\"${service}\"" \
    --data-urlencode "interval.startTime=${start}" \
    --data-urlencode "interval.endTime=${end}" \
    --data-urlencode "aggregation.alignmentPeriod=60s" \
    --data-urlencode "aggregation.perSeriesAligner=ALIGN_MAX" \
    --data-urlencode "aggregation.crossSeriesReducer=REDUCE_SUM" \
    --data-urlencode "aggregation.groupByFields=resource.label.service_name" \
    2>/dev/null \
| python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print(0); sys.exit()
best = 0
for s in d.get("timeSeries", []):
    pts = s.get("points", [])
    if not pts:
        continue
    v = pts[0]["value"]
    best = max(best, int(float(v.get("doubleValue", v.get("int64Value", 0)))))
print(best)
'
