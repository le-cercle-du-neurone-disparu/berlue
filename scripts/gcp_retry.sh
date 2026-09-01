#!/usr/bin/env bash
# scripts/gcp_retry.sh
#
# Relance une commande jusqu'à ce qu'elle réussisse. GCP est éventuellement
# cohérent : un compte de service ou une API tout juste créés ne sont pas
# visibles immédiatement par la commande suivante — une seule tentative
# échoue alors sur un projet neuf, là où elle passe toujours sur un projet
# déjà provisionné (où la ressource existe depuis longtemps).
#
# La sortie des tentatives ratées est retenue et affichée seulement si la
# dernière échoue aussi : pas de mur d'erreurs pour un simple délai.
#
# Usage : scripts/gcp_retry.sh "<description>" <commande...>
# Réglages : GCP_RETRY_ATTEMPTS (défaut 12), GCP_RETRY_DELAY (défaut 5s).

set -uo pipefail

ATTEMPTS="${GCP_RETRY_ATTEMPTS:-12}"
DELAY="${GCP_RETRY_DELAY:-5}"

if [ "$#" -lt 2 ]; then
    echo "Usage : $0 \"<description>\" <commande...>" >&2
    exit 2
fi

label="$1"
shift

out=""
for i in $(seq 1 "$ATTEMPTS"); do
    # stdin fermé : une commande gcloud qui poserait une question doit
    # échouer, jamais bloquer la recette make en attendant une réponse que
    # personne ne voit — la sortie étant redirigée, l'invite est invisible.
    if out="$("$@" 2>&1 </dev/null)"; then
        [ -n "$out" ] && echo "$out"
        exit 0
    fi
    if [ "$i" -lt "$ATTEMPTS" ]; then
        echo "   ⏳ $label : pas encore disponible, nouvelle tentative dans ${DELAY}s ($i/$ATTEMPTS)..."
        sleep "$DELAY"
    fi
done

echo "$out" >&2
echo "❌ $label : toujours en échec après $ATTEMPTS tentatives." >&2
exit 1
