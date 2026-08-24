# scripts/lib/gpu_detect.sh
#
# Détection VRAM/RAM partagée entre tous les scripts Ollama (setup_ollama.sh,
# bench_llama_sizes.sh, bench_model_families.sh) — à sourcer, pas à exécuter :
#   source "$(dirname "${BASH_SOURCE[0]}")/lib/gpu_detect.sh"
#
# Objectif : que chaque script puisse vérifier la VRAM disponible avant de charger
# un modèle, pour éviter de la faire "exploser" (dépassement massif, machine qui
# rame/gèle) — cohérent avec ce qui a déjà été validé pour bench_model_families.sh.

# Détecte la VRAM disponible en Go (nombre décimal, ex: "12.0"). Vide si
# indéterminable — dans ce cas, laisser l'appelant décider (avertir, forcer via
# BENCH_VRAM_GB, ou refuser).
#   - NVIDIA (nvidia-smi)
#   - AMD sur Linux avec ROCm (rocm-smi) — pas de support ROCm sous WSL2 ni macOS
#   - macOS Apple Silicon uniquement (mémoire unifiée, uname -m = arm64) —
#     heuristique 70% de la RAM système. Les Mac Intel à GPU AMD dédié (uname -m =
#     x86_64) ne sont PAS couverts ici : leur VRAM réelle est bien plus petite que
#     la RAM système, donc on ne devine pas et on retombe sur indéterminable.
detect_vram_gb() {
    if [ -n "${BENCH_VRAM_GB:-}" ]; then
        echo "$BENCH_VRAM_GB"
        return
    fi

    if command -v nvidia-smi >/dev/null 2>&1; then
        local mib
        mib="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -n1)"
        if [ -n "$mib" ]; then
            awk -v m="$mib" 'BEGIN { printf "%.1f", m / 1024 }'
            return
        fi
    fi

    if command -v rocm-smi >/dev/null 2>&1; then
        local vram_bytes
        vram_bytes="$(rocm-smi --showmeminfo vram --csv 2>/dev/null | awk -F',' 'NR==2 { print $3 }')"
        if [ -n "$vram_bytes" ]; then
            awk -v b="$vram_bytes" 'BEGIN { printf "%.1f", b / 1024 / 1024 / 1024 }'
            return
        fi
    fi

    if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
        local mem_bytes
        mem_bytes="$(sysctl -n hw.memsize 2>/dev/null)"
        if [ -n "$mem_bytes" ]; then
            awk -v b="$mem_bytes" 'BEGIN { printf "%.1f", (b / 1024 / 1024 / 1024) * 0.7 }'
            return
        fi
    fi

    echo ""
}

# Détecte la RAM système totale en Go (nombre décimal). Vide si indéterminable.
# Utile pour estimer si un modèle peut au moins charger (VRAM + RAM combinées,
# avec offload CPU automatique d'Ollama), même s'il ne tiendra pas 100% en VRAM.
detect_ram_gb() {
    if command -v free >/dev/null 2>&1; then
        free -b 2>/dev/null | awk '/^Mem:/ { printf "%.1f", $2 / 1024 / 1024 / 1024 }'
        return
    fi

    if [ "$(uname -s)" = "Darwin" ]; then
        local mem_bytes
        mem_bytes="$(sysctl -n hw.memsize 2>/dev/null)"
        if [ -n "$mem_bytes" ]; then
            awk -v b="$mem_bytes" 'BEGIN { printf "%.1f", b / 1024 / 1024 / 1024 }'
            return
        fi
    fi

    echo ""
}
