#!/usr/bin/env bash
# scripts/setup_ollama.sh
#
# Installe une version FIGÉE d'Ollama en local, démarre le serveur, puis délègue à
# scripts/check_ollama.sh les tests post-install (pull du modèle par défaut, prompt
# de test, vérification GPU via `ollama ps`).
#
# Compatible : Debian/Ubuntu (bare metal ou WSL2), macOS.
#   - Linux/WSL : script officiel Ollama, épinglé via OLLAMA_VERSION (installe le
#     service systemd comme d'habitude, juste la version demandée).
#   - macOS : pas de pin fiable via Homebrew (la formule suit toujours la dernière
#     version) → on télécharge directement le binaire universel de la release GitHub
#     correspondante, avec vérification du sha256.
#
# Variables d'env optionnelles (mêmes noms que berlue-draft/.env.example) :
#   BERLUE_OLLAMA_MODEL  (défaut: llama3.1:8b)
#   BERLUE_OLLAMA_HOST   (défaut: http://localhost:11434)
#
# Usage : ./scripts/setup_ollama.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Version testée et validée de bout en bout (install + serve + pull + prompt) sur
# Debian 13. À mettre à jour ici volontairement si besoin d'une version plus récente
# — jamais en suivant silencieusement le "latest" d'Ollama.
OLLAMA_PIN_VERSION="0.32.15"

OLLAMA_MODEL="${BERLUE_OLLAMA_MODEL:-llama3.1:8b}"
OLLAMA_HOST="${BERLUE_OLLAMA_HOST:-http://localhost:11434}"
MACOS_INSTALL_DIR="${HOME}/.ollama/versions/${OLLAMA_PIN_VERSION}"

# Résolu par install_ollama() : chemin (ou nom sur le PATH) du binaire à utiliser
# pour toute la suite du script.
OLLAMA_BIN="ollama"

log() { printf '\033[1;34m[setup-ollama]\033[0m %s\n' "$1"; }
err() { printf '\033[1;31m[setup-ollama]\033[0m %s\n' "$1" >&2; }

detect_os() {
    case "$(uname -s)" in
        Linux*)
            if grep -qi microsoft /proc/version 2>/dev/null; then
                echo "wsl"
            else
                echo "linux"
            fi
            ;;
        Darwin*) echo "macos" ;;
        *) echo "unknown" ;;
    esac
}

# Affiche juste le numéro de version (ex: 0.32.15) d'un binaire ollama, ou rien
# si indéterminable.
installed_version() {
    local bin="$1"
    "$bin" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1 || true
}

install_ollama_linux() {
    if command -v ollama >/dev/null 2>&1 && [ "$(installed_version ollama)" = "$OLLAMA_PIN_VERSION" ]; then
        log "Ollama $OLLAMA_PIN_VERSION déjà installé, pas de réinstallation."
        OLLAMA_BIN="ollama"
        return
    fi

    log "Installation d'Ollama $OLLAMA_PIN_VERSION (script officiel, version épinglée)..."
    curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION="$OLLAMA_PIN_VERSION" sh
    OLLAMA_BIN="ollama"
}

install_ollama_macos() {
    OLLAMA_BIN="$MACOS_INSTALL_DIR/ollama"

    if [ -x "$OLLAMA_BIN" ] && [ "$(installed_version "$OLLAMA_BIN")" = "$OLLAMA_PIN_VERSION" ]; then
        log "Ollama $OLLAMA_PIN_VERSION déjà installé dans $MACOS_INSTALL_DIR, pas de réinstallation."
        return
    fi

    local url="https://github.com/ollama/ollama/releases/download/v${OLLAMA_PIN_VERSION}/ollama-darwin.tgz"
    local sums_url="https://github.com/ollama/ollama/releases/download/v${OLLAMA_PIN_VERSION}/sha256sum.txt"
    local tmp_tgz
    tmp_tgz="$(mktemp)"

    log "Téléchargement d'Ollama $OLLAMA_PIN_VERSION (binaire universel macOS, release GitHub)..."
    curl -fsSL "$url" -o "$tmp_tgz"

    log "Vérification du sha256..."
    local expected actual
    expected="$(curl -fsSL "$sums_url" | grep 'ollama-darwin.tgz' | awk '{print $1}')"
    actual="$(shasum -a 256 "$tmp_tgz" | awk '{print $1}')"
    if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
        err "Somme de contrôle invalide pour ollama-darwin.tgz (attendu '$expected', obtenu '$actual')."
        rm -f "$tmp_tgz"
        exit 1
    fi

    mkdir -p "$MACOS_INSTALL_DIR"
    tar -xzf "$tmp_tgz" -C "$MACOS_INSTALL_DIR"
    rm -f "$tmp_tgz"
    chmod +x "$OLLAMA_BIN"

    # Pratique pour un usage interactif hors de ce script (facultatif : le script
    # lui-même n'en dépend jamais, il invoque toujours $OLLAMA_BIN en chemin absolu).
    if [ -w /usr/local/bin ]; then
        ln -sf "$OLLAMA_BIN" /usr/local/bin/ollama 2>/dev/null || true
    fi

    log "Ollama $OLLAMA_PIN_VERSION installé dans $MACOS_INSTALL_DIR."
}

install_ollama() {
    local os="$1"
    case "$os" in
        linux|wsl) install_ollama_linux ;;
        macos) install_ollama_macos ;;
        *)
            err "OS non reconnu par ce script. Installe Ollama $OLLAMA_PIN_VERSION manuellement : https://github.com/ollama/ollama/releases/tag/v${OLLAMA_PIN_VERSION}"
            exit 1
            ;;
    esac
}

is_ollama_up() {
    curl -fsS -m 3 "$OLLAMA_HOST/api/version" >/dev/null 2>&1
}

start_ollama() {
    if is_ollama_up; then
        log "Serveur Ollama déjà en écoute sur $OLLAMA_HOST."
        return
    fi

    log "Démarrage du serveur Ollama..."
    if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^ollama\.service'; then
        sudo systemctl enable --now ollama
    else
        nohup "$OLLAMA_BIN" serve >/tmp/ollama-serve.log 2>&1 &
        disown
    fi

    log "Attente que le serveur réponde (jusqu'à 30s)..."
    for _ in $(seq 1 30); do
        if is_ollama_up; then
            log "Serveur Ollama prêt."
            return
        fi
        sleep 1
    done

    err "Le serveur Ollama ne répond toujours pas après 30s sur $OLLAMA_HOST."
    err "Vérifie les logs (/tmp/ollama-serve.log ou 'journalctl -u ollama')."
    exit 1
}

main() {
    local os
    os="$(detect_os)"
    log "OS détecté : $os"

    install_ollama "$os"
    start_ollama

    log "Délégation des tests post-install à check_ollama.sh..."
    # PATH mis à jour avec le dossier de $OLLAMA_BIN : nécessaire sur macOS, où le
    # binaire vit dans ~/.ollama/versions/<pin>/ et n'est symlinké dans
    # /usr/local/bin que si ce dossier est inscriptible (facultatif).
    PATH="$(dirname "$OLLAMA_BIN"):$PATH" \
        BERLUE_OLLAMA_MODEL="$OLLAMA_MODEL" \
        BERLUE_OLLAMA_HOST="$OLLAMA_HOST" \
        "$SCRIPT_DIR/check_ollama.sh"
}

main "$@"
