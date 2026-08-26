#!/bin/bash

# Récupère les variables passées en arguments
PYTHON_VERSION=$1
VENV_NAME=$2

if [ -z "$PYTHON_VERSION" ] || [ -z "$VENV_NAME" ]; then
    echo "❌ ERREUR : arguments manquants."
    echo "👉 Usage : bash setup_vm.sh <PYTHON_VERSION> <VENV_NAME>"
    exit 1
fi

echo "🚀 Démarrage du processus d'installation..."

# 1. Met à jour et installe les dépendances Python (mode non interactif avec -y)
sudo apt-get update
sudo apt-get install -y make build-essential libssl-dev zlib1g-dev \
libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm \
libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev \
python3-dev zsh git

# 2. Installe ZSH & Oh My Zsh (sans bloquer le script)
if [ ! -d "$HOME/.oh-my-zsh" ]; then
    sh -c "$(curl -fsSL https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended
fi

# 3. Installe Pyenv et Pyenv-virtualenv
if [ ! -d "$HOME/.pyenv" ]; then
    git clone https://github.com/pyenv/pyenv.git ~/.pyenv
    git clone https://github.com/pyenv/pyenv-virtualenv.git ~/.pyenv/plugins/pyenv-virtualenv
fi

# 4. Configure les fichiers ZSH
sed -i 's/plugins=(git)/plugins=(git pyenv ssh-agent direnv)/' ~/.zshrc

cat << 'EOF' > ~/.zprofile
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init --path)"
EOF

# 5. Active Pyenv immédiatement pour la suite du script
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init --path)"

# 6. Installe Python (prend environ 5 minutes)
echo "🐍 Installation de Python ${PYTHON_VERSION} (patientez)..."
pyenv install -s "${PYTHON_VERSION}"
pyenv virtualenv "${PYTHON_VERSION}" "${VENV_NAME}"
pyenv global "${VENV_NAME}"

# 7. Installe les packages Python pour GCP
echo "📦 Installation des librairies GCP..."
pip install -U pip
pip install google-cloud-storage google-cloud-bigquery

echo "✅ Installation terminée avec succès !"
