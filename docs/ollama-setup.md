# Ollama en local

## Prérequis

- Linux (Debian/Ubuntu), WSL2, ou macOS
- `bash`, `curl`
- GPU recommandé (NVIDIA, ou AMD/ROCm sur Linux, ou Apple Silicon) — fonctionne
  aussi sur CPU seul mais bien plus lentement

## Installation

```bash
make ollama_setup
```

Installe une version figée d'Ollama, démarre le serveur, et lance un premier
check automatique.

## Tester

Trois façons de vérifier que ça tourne, du plus rapide au plus complet :

```bash
# Charge un modèle, envoie un prompt de test, vérifie qu'il tourne bien sur
# GPU (et pas seulement CPU)
# Temps estimé : ~30s (si le modèle est déjà téléchargé)
make ollama_check

# Détecte la VRAM disponible et compare les 3 meilleurs modèles par famille
# (Llama, Qwen2.5, Gemma, Mistral) tenant dedans
# Temps estimé : ~15–30 min (télécharge les modèles pas encore présents)
make ollama_bench

# Même sélection que ollama_bench, mais mesure précisément latence et débit
# (tokens/s) via plusieurs essais par modèle
# Temps estimé : ~30–45 min
make ollama_perf
```

`ollama_bench` et `ollama_perf` écrivent chacun un rapport CSV dans `logs/`.

## Configuration d'Ollama sur la machine

Pas de fichier de config (YAML/JSON) : tout passe par des variables
d'environnement lues par `ollama serve` au démarrage.

### Emplacements (Linux, install via `ollama_setup`)

| Élément | Emplacement |
|---|---|
| Unité systemd générée par l'installeur | `/etc/systemd/system/ollama.service` |
| Override propre (à créer, ne pas toucher le fichier généré) | `/etc/systemd/system/ollama.service.d/override.conf` |
| Binaire | `/usr/local/bin/ollama` |
| Données (modèles, cache, clé de signature) | `/usr/share/ollama/.ollama/` (utilisateur système `ollama`, pas l'utilisateur courant) |

Sur WSL2 sans systemd / macOS, pas d'emplacement dédié : les données vont dans
`~/.ollama/` de l'utilisateur qui lance `ollama serve`.

**Linux** (service systemd) — pour changer un réglage :

```bash
sudo systemctl edit ollama
# [Service]
# Environment="VAR=valeur"
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

**WSL2 sans systemd / macOS** — pas de service, les variables se passent en
préfixant la commande :

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

### Variables les plus utiles

| Variable | Rôle |
|---|---|
| `OLLAMA_HOST` | Adresse/port d'écoute (défaut `127.0.0.1:11434`) |
| `OLLAMA_MODELS` | Dossier de stockage des modèles |
| `OLLAMA_KEEP_ALIVE` | Durée de rétention d'un modèle en mémoire après usage |
| `OLLAMA_NUM_PARALLEL` | Nombre de requêtes traitées en parallèle |
| `OLLAMA_MAX_LOADED_MODELS` | Nombre max de modèles chargés simultanément |
