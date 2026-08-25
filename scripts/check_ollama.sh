#!/usr/bin/env bash
# scripts/check_ollama.sh
#
# Mode par défaut : vérifie qu'Ollama fonctionne — charge un modèle, envoie un
# prompt de test, confirme qu'il tourne bien (au moins partiellement) sur GPU
# (colonne PROCESSOR de `ollama ps`). C'est le check appelé automatiquement à la
# fin de scripts/setup_ollama.sh.
#
# Mode --bench : au lieu du check simple sur un seul modèle, détecte la VRAM du
# GPU de la machine courante puis sélectionne et teste les 3 meilleurs modèles
# (les plus gros tenant sous cette limite) pour chaque famille — Llama, Qwen2.5,
# Gemma, Mistral — et écrit un rapport CSV dans logs/. Résultat "OK/échec" +
# temps total approximatif (chargement + génération mélangés).
#
# Mode --perf : même sélection top-3/famille que --bench, mais mesure précise via
# l'API HTTP /api/generate (débit de génération en tokens/s isolé du temps de
# chargement, latence au premier token, débit de traitement du prompt) — plusieurs
# essais avec warm-up préalable. Écrit aussi un rapport CSV dans logs/.
#
# Pré-requis : Ollama installé et son serveur démarré (cf. scripts/setup_ollama.sh
# / `make ollama_setup`).
#
# Variables d'env optionnelles :
#   BERLUE_OLLAMA_HOST    (défaut: http://localhost:11434)
#   BERLUE_OLLAMA_MODEL   (défaut: qwen2.5:0.5b) — modèle testé en mode simple (sans --bench/--perf)
#   BENCH_VRAM_GB         (défaut: auto-détecté) — force la limite VRAM en Go (--bench/--perf)
#   BENCH_RUN_TIMEOUT     (défaut: 240)  — secondes max par appel (--bench/--perf)
#   BENCH_PULL_TIMEOUT    (défaut: 1800) — secondes max pour le téléchargement (--bench/--perf)
#   BENCH_KEEP_MODELS     (défaut: vide) — si non vide, garde les modèles téléchargés (--bench/--perf)
#   PERF_NUM_PREDICT      (défaut: 200)  — tokens générés par essai (--perf)
#   PERF_TRIALS           (défaut: 3)    — nombre d'essais mesurés par modèle, après warm-up (--perf)
#
# Usage :
#   ./scripts/check_ollama.sh            # check simple (GPU oui/non) sur BERLUE_OLLAMA_MODEL
#   ./scripts/check_ollama.sh --bench    # quel modèle passe, par famille + rapport CSV
#   ./scripts/check_ollama.sh --perf     # latence/débit précis sur la même sélection + rapport CSV

set -uo pipefail
# (pas de -e : en mode --bench on décide nous-mêmes de ce qui compte comme un
# échec par candidat et on continue sur le suivant)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/gpu_detect.sh
source "$SCRIPT_DIR/lib/gpu_detect.sh"

OLLAMA_HOST="${BERLUE_OLLAMA_HOST:-http://localhost:11434}"
OLLAMA_MODEL="${BERLUE_OLLAMA_MODEL:-qwen2.5:0.5b}"
RUN_TIMEOUT="${BENCH_RUN_TIMEOUT:-240}"
PULL_TIMEOUT="${BENCH_PULL_TIMEOUT:-1800}"
KEEP_MODELS="${BENCH_KEEP_MODELS:-}"
# Marge de sécurité (mode --bench) : on ne retient que les modèles tenant sous 90%
# de la VRAM détectée (headroom pour le KV-cache/contexte/OS).
VRAM_MARGIN="0.9"
# Dossier des rapports CSV du mode --bench (un fichier par run).
REPORT_DIR="logs"

log()  { printf '\033[1;34m[check-ollama]\033[0m %s\n' "$1" >&2; }
ok()   { printf '\033[1;32m[check-ollama]\033[0m %s\n' "$1" >&2; }
warn() { printf '\033[1;33m[check-ollama]\033[0m %s\n' "$1" >&2; }
err()  { printf '\033[1;31m[check-ollama]\033[0m %s\n' "$1" >&2; }
# (tous sur stderr : le stdout du script reste réservé aux tableaux de résultats
# et aux valeurs de retour capturées via $(...), ex. select_candidates)

require_ollama_ready() {
    if ! command -v ollama >/dev/null 2>&1; then
        err "Ollama n'est pas installé. Lance d'abord : make ollama_setup"
        exit 1
    fi
    if ! curl -fsS -m 3 "$OLLAMA_HOST/api/version" >/dev/null 2>&1; then
        err "Le serveur Ollama ne répond pas sur $OLLAMA_HOST. Lance d'abord : make ollama_setup"
        exit 1
    fi
}

# Colonne PROCESSOR de `ollama ps` pour un modèle actuellement chargé
# (ex: "100% GPU", "23%/77% CPU/GPU", "100% CPU") — vide si déjà déchargé.
processor_of() {
    OLLAMA_HOST="$OLLAMA_HOST" ollama ps 2>/dev/null | awk -v m="$1" '$1==m {print $5, $6}'
}

# ==============================================================================
# Mode par défaut : check simple sur un seul modèle
# ==============================================================================

run_check() {
    require_ollama_ready

    log "Chargement de $OLLAMA_MODEL et envoi d'un prompt de test..."
    if ! ollama pull "$OLLAMA_MODEL" >/tmp/check-ollama-pull.log 2>&1; then
        err "Échec du téléchargement de $OLLAMA_MODEL (voir /tmp/check-ollama-pull.log)."
        exit 1
    fi

    local response
    response="$(OLLAMA_HOST="$OLLAMA_HOST" ollama run "$OLLAMA_MODEL" "Réponds uniquement par le mot OK." 2>/tmp/check-ollama-run.log)"
    if [ -z "$response" ]; then
        err "Aucune réponse reçue du modèle $OLLAMA_MODEL — quelque chose ne va pas (voir /tmp/check-ollama-run.log)."
        exit 1
    fi
    ok "Réponse reçue de $OLLAMA_MODEL : ${response:0:120}"

    local processor
    processor="$(processor_of "$OLLAMA_MODEL")"
    if [ -z "$processor" ]; then
        warn "Impossible de lire la colonne PROCESSOR de 'ollama ps' ($OLLAMA_MODEL déjà déchargé ?)."
        return
    fi
    log "ollama ps → PROCESSOR = $processor"

    case "$processor" in
        *100%\ CPU*)
            err "❌ $OLLAMA_MODEL tourne intégralement sur CPU — le GPU n'est pas utilisé."
            exit 1
            ;;
        *GPU*)
            ok "✅ GPU utilisé pour $OLLAMA_MODEL (PROCESSOR = $processor)."
            ;;
        *)
            err "Format PROCESSOR inattendu ('$processor') — vérifie manuellement avec 'ollama ps'."
            exit 1
            ;;
    esac
}

# ==============================================================================
# Mode --bench : top 3 par famille (Llama/Qwen2.5/Gemma/Mistral) sous la VRAM détectée
# ==============================================================================

# Espace disponible en Go sur le filesystem contenant $HOME (portable Linux/macOS
# via `df -Pk`, format POSIX identique sur GNU et BSD).
free_disk_gb() {
    df -Pk "$HOME" | awk 'NR==2 { printf "%.0f", $4 / 1024 / 1024 }'
}

model_already_present() {
    ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$1"
}

# Catalogue complet par famille, triés du plus gros au plus petit — les tailles
# (Go, quantization par défaut Q4) sont approximatives, juste pour la sélection et
# la vérification d'espace disque, pas besoin de précision absolue.
CATALOG=(
    "Llama|llama3.1:405b|231"
    "Llama|llama3.1:70b|40"
    "Llama|llama3.1:8b|4.9"
    "Llama|llama3.2:3b|2.0"
    "Llama|llama3.2:1b|1.3"
    "Qwen3.5|qwen3.5:9b|6.6"
    "Qwen2.5|qwen2.5:72b|47"
    "Qwen2.5|qwen2.5:32b|20"
    "Qwen2.5|qwen2.5:14b|9.0"
    "Qwen2.5|qwen2.5:7b|4.7"
    "Qwen2.5|qwen2.5:3b|1.9"
    "Qwen2.5|qwen2.5:1.5b|1.0"
    "Qwen2.5|qwen2.5:0.5b|0.4"
    "Gemma|gemma3:27b|17"
    "Gemma|gemma2:27b|16"
    "Gemma|gemma3:12b|8.1"
    "Gemma|gemma2:9b|5.4"
    "Gemma|gemma3:4b|3.3"
    "Gemma|gemma3:1b|0.8"
    "Mistral|mixtral:8x22b|80"
    "Mistral|mixtral:8x7b|26"
    "Mistral|mistral-nemo:12b|7.1"
    "Mistral|mistral:7b|4.1"
 )


BENCH_RESULTS=()  # lignes "model|status|seconds|processor|note" pour le résumé final

bench_run_one() {
    local model="$1" size_gb="$2"
    local was_present start end elapsed note response exit_code processor avail

    log "=== $model (~${size_gb} Go) ==="

    avail="$(free_disk_gb)"
    if awk -v a="$avail" -v s="$size_gb" 'BEGIN { exit !(a < s * 1.15) }'; then
        warn "Espace disque insuffisant (${avail} Go libres, ~${size_gb} Go requis) — on passe au suivant."
        BENCH_RESULTS+=("$model|DISQUE INSUFFISANT|-|-|${avail} Go libres, ~${size_gb} Go requis")
        return
    fi

    was_present="false"
    model_already_present "$model" && was_present="true"

    log "Téléchargement (timeout ${PULL_TIMEOUT}s)..."
    if ! timeout "$PULL_TIMEOUT" ollama pull "$model" >/tmp/check-ollama-bench-pull.log 2>&1; then
        err "Échec du téléchargement (voir /tmp/check-ollama-bench-pull.log)."
        BENCH_RESULTS+=("$model|ÉCHEC TÉLÉCHARGEMENT|-|-|$(tail -n1 /tmp/check-ollama-bench-pull.log 2>/dev/null)")
        return
    fi

    log "Test d'un prompt (timeout ${RUN_TIMEOUT}s)..."
    start="$(date +%s)"
    response="$(timeout "$RUN_TIMEOUT" env OLLAMA_HOST="$OLLAMA_HOST" ollama run "$model" "Réponds uniquement par le mot OK." 2>/tmp/check-ollama-bench-run.log)"
    exit_code=$?
    end="$(date +%s)"
    elapsed=$((end - start))

    processor="$(processor_of "$model")"
    [ -z "$processor" ] && processor="-"

    if [ "$was_present" = "false" ] && [ -z "$KEEP_MODELS" ]; then
        log "Nettoyage : suppression de $model téléchargé par ce script..."
        ollama rm "$model" >/dev/null 2>&1 || true
    fi

    if [ "$exit_code" -eq 124 ]; then
        err "Timeout (>${RUN_TIMEOUT}s)."
        BENCH_RESULTS+=("$model|TIMEOUT|>${elapsed}|${processor}|dépasse ${RUN_TIMEOUT}s")
    elif [ "$exit_code" -eq 137 ]; then
        err "Tué par le système (SIGKILL) — probablement out-of-memory."
        BENCH_RESULTS+=("$model|OOM (killed)|${elapsed}|${processor}|processus tué")
    elif [ "$exit_code" -ne 0 ] || [ -z "$response" ]; then
        note="$(tail -n1 /tmp/check-ollama-bench-run.log 2>/dev/null)"
        err "Échec (code $exit_code) : $note"
        BENCH_RESULTS+=("$model|ÉCHEC|${elapsed}|${processor}|$note")
    else
        ok "OK en ${elapsed}s (${processor}) — réponse : ${response:0:80}"
        BENCH_RESULTS+=("$model|OK|${elapsed}|${processor}|")
    fi
}

bench_print_summary() {
    echo
    log "=================== Résumé ==================="
    printf '%-20s %-20s %-8s %-14s %s\n' "MODÈLE" "RÉSULTAT" "TEMPS" "PROCESSEUR" "NOTE"
    local line model status secs processor note
    for line in "${BENCH_RESULTS[@]}"; do
        IFS='|' read -r model status secs processor note <<< "$line"
        printf '%-20s %-20s %-8s %-14s %s\n' "$model" "$status" "${secs}s" "$processor" "$note"
    done
    echo "================================================"
}

# Échappe un champ pour un CSV (entoure de guillemets, double les guillemets internes).
csv_field() {
    local f="${1//\"/\"\"}"
    printf '"%s"' "$f"
}

bench_write_csv_report() {
    local vram_gb="$1"
    local hostname_safe run_timestamp report_file
    hostname_safe="$(hostname 2>/dev/null | tr -d '\n' | tr -c 'A-Za-z0-9._-' '_')"
    [ -z "$hostname_safe" ] && hostname_safe="unknown-host"
    run_timestamp="$(date +%Y%m%d-%H%M%S)"
    report_file="${REPORT_DIR}/reports-ollama-benchgpu-${hostname_safe}-${run_timestamp}.csv"

    mkdir -p "$REPORT_DIR"
    {
        echo "timestamp,hostname,vram_gb,model,status,seconds,processor,note"
        local line model status secs processor note
        for line in "${BENCH_RESULTS[@]}"; do
            IFS='|' read -r model status secs processor note <<< "$line"
            printf '%s,%s,%s,%s,%s,%s,%s,%s\n' \
                "$(csv_field "$run_timestamp")" "$(csv_field "$hostname_safe")" "$(csv_field "$vram_gb")" \
                "$(csv_field "$model")" "$(csv_field "$status")" "$(csv_field "$secs")" \
                "$(csv_field "$processor")" "$(csv_field "$note")"
        done
    } > "$report_file"

    ok "Résultats sauvegardés dans $report_file"
}

# Détecte la VRAM et sélectionne, pour chaque famille (dans l'ordre du catalogue,
# du plus gros au plus petit), les 3 premiers modèles qui tiennent sous la marge
# retenue. Remplit les globales SELECTED ("model|size_gb", un par ligne) et
# SELECTED_VRAM_GB — PAS de retour via stdout/$(...) : ça tournerait dans un
# sous-shell et les tableaux remplis seraient perdus à la sortie. Partagée entre
# --bench et --perf : appeler en instruction simple, jamais en substitution de
# commande.
select_candidates() {
    local flag_hint="${1:---bench}"
    SELECTED_VRAM_GB="$(detect_vram_gb)"

    if [ -z "$SELECTED_VRAM_GB" ]; then
        warn "Aucun GPU dédié détecté (ni nvidia-smi, ni rocm-smi, ni macOS Apple Silicon) — impossible d'estimer une limite VRAM."
        warn "Force une valeur avec BENCH_VRAM_GB=<Go> ./scripts/check_ollama.sh $flag_hint"
        exit 1
    fi
    log "VRAM détectée : ${SELECTED_VRAM_GB} Go (marge retenue : $(awk -v v="$SELECTED_VRAM_GB" -v m="$VRAM_MARGIN" 'BEGIN{printf "%.1f", v*m}') Go utilisables)"

    declare -A family_count
    SELECTED=()
    local entry family model size_gb count
    for entry in "${CATALOG[@]}"; do
        IFS='|' read -r family model size_gb <<< "$entry"
        count="${family_count[$family]:-0}"
        [ "$count" -ge 3 ] && continue
        if awk -v s="$size_gb" -v lim="$SELECTED_VRAM_GB" -v m="$VRAM_MARGIN" 'BEGIN { exit !(s <= lim * m) }'; then
            SELECTED+=("${model}|${size_gb}")
            family_count[$family]=$((count + 1))
        fi
    done

    if [ "${#SELECTED[@]}" -eq 0 ]; then
        err "Aucun modèle du catalogue ne tient sous ${SELECTED_VRAM_GB} Go — matériel trop limité."
        exit 1
    fi

    log "Sélection retenue (${#SELECTED[@]} modèles) :"
    local sel model_sel size_sel
    for sel in "${SELECTED[@]}"; do
        IFS='|' read -r model_sel size_sel <<< "$sel"
        log "  - $model_sel (~${size_sel} Go)"
    done
}

run_bench() {
    require_ollama_ready
    select_candidates --bench

    local sel model_sel size_sel
    for sel in "${SELECTED[@]}"; do
        IFS='|' read -r model_sel size_sel <<< "$sel"
        bench_run_one "$model_sel" "$size_sel"
    done

    bench_print_summary
    bench_write_csv_report "$SELECTED_VRAM_GB"
}

# ==============================================================================
# Mode --perf : mesure précise latence/débit (API HTTP /api/generate, pas
# `ollama run`) sur la même sélection top-3/famille que --bench.
#
# `ollama run` ne donne que le temps total (chargement + prompt + génération
# mélangés) ; l'API JSON renvoie ces phases séparément (nanosecondes) :
#   load_duration, prompt_eval_count/_duration, eval_count/_duration
# → on peut calculer un vrai débit de génération (tokens/s) non pollué par le
# chargement disque, plutôt que chronométrer tout le process avec `date`.
# ==============================================================================

PERF_PROMPT="Explique en quelques phrases pourquoi le ciel est bleu, avec des mots simples."
PERF_NUM_PREDICT="${PERF_NUM_PREDICT:-200}"
PERF_TRIALS="${PERF_TRIALS:-3}"

PERF_RESULTS=()  # "model|status|tok_s_avg|tok_s_min|tok_s_max|prompt_tok_s|ttft_ms|load_ms|note"

# Extrait un champ numérique d'un JSON plat à une seule ligne — pas de dépendance
# à jq (pas garanti installé partout), les réponses d'Ollama tiennent sur une ligne.
json_num() {
    printf '%s' "$1" | grep -oE "\"$2\":[0-9.eE+-]+" | head -n1 | cut -d: -f2
}

perf_call() {
    local model="$1" num_predict="$2"
    curl -fsS -m "$RUN_TIMEOUT" "$OLLAMA_HOST/api/generate" \
        -d "{\"model\":\"$model\",\"prompt\":\"$PERF_PROMPT\",\"stream\":false,\"options\":{\"num_predict\":$num_predict}}" \
        2>/tmp/check-ollama-perf.log
}

perf_run_one() {
    local model="$1" size_gb="$2"
    local was_present avail json

    log "=== $model (~${size_gb} Go) ==="

    avail="$(free_disk_gb)"
    if awk -v a="$avail" -v s="$size_gb" 'BEGIN { exit !(a < s * 1.15) }'; then
        warn "Espace disque insuffisant (${avail} Go libres, ~${size_gb} Go requis) — on passe au suivant."
        PERF_RESULTS+=("$model|DISQUE INSUFFISANT|-|-|-|-|-|-|${avail} Go libres, ~${size_gb} Go requis")
        return
    fi

    was_present="false"
    model_already_present "$model" && was_present="true"

    log "Téléchargement (timeout ${PULL_TIMEOUT}s)..."
    if ! timeout "$PULL_TIMEOUT" ollama pull "$model" >/tmp/check-ollama-perf-pull.log 2>&1; then
        err "Échec du téléchargement (voir /tmp/check-ollama-perf-pull.log)."
        PERF_RESULTS+=("$model|ÉCHEC TÉLÉCHARGEMENT|-|-|-|-|-|-|$(tail -n1 /tmp/check-ollama-perf-pull.log 2>/dev/null)")
        return
    fi

    log "Warm-up (charge le modèle en VRAM, mesure le temps de chargement)..."
    json="$(perf_call "$model" 20)"
    if [ -z "$json" ]; then
        err "Échec de l'appel API (voir /tmp/check-ollama-perf.log)."
        PERF_RESULTS+=("$model|ÉCHEC|-|-|-|-|-|-|$(tail -n1 /tmp/check-ollama-perf.log 2>/dev/null)")
        [ "$was_present" = "false" ] && [ -z "$KEEP_MODELS" ] && ollama rm "$model" >/dev/null 2>&1
        return
    fi

    local load_ns prompt_eval_dur_ns load_ms ttft_ms
    load_ns="$(json_num "$json" load_duration)"
    prompt_eval_dur_ns="$(json_num "$json" prompt_eval_duration)"
    load_ms="$(awk -v n="${load_ns:-0}" 'BEGIN{printf "%.0f", n/1e6}')"
    ttft_ms="$(awk -v l="${load_ns:-0}" -v p="${prompt_eval_dur_ns:-0}" 'BEGIN{printf "%.0f", (l+p)/1e6}')"

    log "Chargement : ${load_ms}ms — TTFT (1er appel) : ${ttft_ms}ms — ${PERF_TRIALS} essais de mesure (num_predict=${PERF_NUM_PREDICT})..."

    local tok_speeds=() prompt_speeds=()
    local i eval_count eval_dur_ns peval_count peval_dur_ns speed pspeed
    for i in $(seq 1 "$PERF_TRIALS"); do
        json="$(perf_call "$model" "$PERF_NUM_PREDICT")"
        if [ -z "$json" ]; then
            warn "Essai $i échoué (voir /tmp/check-ollama-perf.log), ignoré."
            continue
        fi
        eval_count="$(json_num "$json" eval_count)"
        eval_dur_ns="$(json_num "$json" eval_duration)"
        peval_count="$(json_num "$json" prompt_eval_count)"
        peval_dur_ns="$(json_num "$json" prompt_eval_duration)"

        if [ -n "$eval_count" ] && [ -n "$eval_dur_ns" ] && [ "$eval_dur_ns" != "0" ]; then
            speed="$(awk -v c="$eval_count" -v d="$eval_dur_ns" 'BEGIN{printf "%.1f", c/(d/1e9)}')"
            tok_speeds+=("$speed")
        fi
        if [ -n "$peval_count" ] && [ -n "$peval_dur_ns" ] && [ "$peval_dur_ns" != "0" ]; then
            pspeed="$(awk -v c="$peval_count" -v d="$peval_dur_ns" 'BEGIN{printf "%.1f", c/(d/1e9)}')"
            prompt_speeds+=("$pspeed")
        fi
    done

    if [ "$was_present" = "false" ] && [ -z "$KEEP_MODELS" ]; then
        log "Nettoyage : suppression de $model téléchargé par ce script..."
        ollama rm "$model" >/dev/null 2>&1 || true
    fi

    if [ "${#tok_speeds[@]}" -eq 0 ]; then
        err "Aucun essai n'a abouti."
        PERF_RESULTS+=("$model|ÉCHEC|-|-|-|-|${ttft_ms}|${load_ms}|tous les essais ont échoué")
        return
    fi

    local avg min max prompt_avg
    avg="$(printf '%s\n' "${tok_speeds[@]}" | awk '{s+=$1; n++} END{printf "%.1f", s/n}')"
    min="$(printf '%s\n' "${tok_speeds[@]}" | sort -n | head -n1)"
    max="$(printf '%s\n' "${tok_speeds[@]}" | sort -n | tail -n1)"
    prompt_avg="-"
    [ "${#prompt_speeds[@]}" -gt 0 ] && prompt_avg="$(printf '%s\n' "${prompt_speeds[@]}" | awk '{s+=$1; n++} END{printf "%.1f", s/n}')"

    ok "${avg} tok/s (min ${min}, max ${max}) — prompt: ${prompt_avg} tok/s — TTFT: ${ttft_ms}ms — chargement: ${load_ms}ms"
    PERF_RESULTS+=("$model|OK|${avg}|${min}|${max}|${prompt_avg}|${ttft_ms}|${load_ms}|")
}

perf_print_summary() {
    echo
    log "=================== Résumé perf ==================="
    printf '%-20s %-10s %-10s %-10s %-10s %-13s %-10s %-10s %s\n' \
        "MODÈLE" "STATUT" "TOK/S avg" "min" "max" "PROMPT tok/s" "TTFT ms" "LOAD ms" "NOTE"
    local line model status avg min max pavg ttft load note
    for line in "${PERF_RESULTS[@]}"; do
        IFS='|' read -r model status avg min max pavg ttft load note <<< "$line"
        printf '%-20s %-10s %-10s %-10s %-10s %-13s %-10s %-10s %s\n' \
            "$model" "$status" "$avg" "$min" "$max" "$pavg" "$ttft" "$load" "$note"
    done
    echo "====================================================="
}

perf_write_csv_report() {
    local vram_gb="$1"
    local hostname_safe run_timestamp report_file
    hostname_safe="$(hostname 2>/dev/null | tr -d '\n' | tr -c 'A-Za-z0-9._-' '_')"
    [ -z "$hostname_safe" ] && hostname_safe="unknown-host"
    run_timestamp="$(date +%Y%m%d-%H%M%S)"
    report_file="${REPORT_DIR}/reports-ollama-perfbench-${hostname_safe}-${run_timestamp}.csv"

    mkdir -p "$REPORT_DIR"
    {
        echo "timestamp,hostname,vram_gb,model,status,tokens_per_sec_avg,tokens_per_sec_min,tokens_per_sec_max,prompt_tokens_per_sec,ttft_ms,load_ms,note"
        local line model status avg min max pavg ttft load note
        for line in "${PERF_RESULTS[@]}"; do
            IFS='|' read -r model status avg min max pavg ttft load note <<< "$line"
            printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
                "$(csv_field "$run_timestamp")" "$(csv_field "$hostname_safe")" "$(csv_field "$vram_gb")" \
                "$(csv_field "$model")" "$(csv_field "$status")" "$(csv_field "$avg")" "$(csv_field "$min")" \
                "$(csv_field "$max")" "$(csv_field "$pavg")" "$(csv_field "$ttft")" "$(csv_field "$load")" "$(csv_field "$note")"
        done
    } > "$report_file"

    ok "Résultats sauvegardés dans $report_file"
}

run_perf() {
    require_ollama_ready
    select_candidates --perf

    log "${PERF_TRIALS} essais de ${PERF_NUM_PREDICT} tokens par modèle."
    echo

    local sel model_sel size_sel
    for sel in "${SELECTED[@]}"; do
        IFS='|' read -r model_sel size_sel <<< "$sel"
        perf_run_one "$model_sel" "$size_sel"
    done

    perf_print_summary
    perf_write_csv_report "$SELECTED_VRAM_GB"
}

main() {
    if [ "${1:-}" = "--bench" ]; then
        run_bench
    elif [ "${1:-}" = "--perf" ]; then
        run_perf
    else
        run_check
    fi
}

main "$@"
