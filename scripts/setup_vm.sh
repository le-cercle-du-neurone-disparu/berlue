#!/bin/bash

# Retrieve variables passed as arguments
PYTHON_VERSION=$1
VENV_NAME=$2

if [ -z "$PYTHON_VERSION" ] || [ -z "$VENV_NAME" ]; then
    echo "❌ ERROR: Missing arguments."
    echo "👉 Usage: bash setup_vm.sh <PYTHON_VERSION> <VENV_NAME>"
    exit 1
fi

echo "🚀 Starting installation process..."

# 1. Update and install Python dependencies (unattended mode with -y)
sudo apt-get update
sudo apt-get install -y make build-essential libssl-dev zlib1g-dev \
libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm \
libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev \
python3-dev zsh git

# 2. Install ZSH & Oh My Zsh (without blocking the script)
if [ ! -d "$HOME/.oh-my-zsh" ]; then
    sh -c "$(curl -fsSL https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended
fi

# 3. Install Pyenv and Pyenv-virtualenv
if [ ! -d "$HOME/.pyenv" ]; then
    git clone https://github.com/pyenv/pyenv.git ~/.pyenv
    git clone https://github.com/pyenv/pyenv-virtualenv.git ~/.pyenv/plugins/pyenv-virtualenv
fi

# 4. Configure ZSH files
sed -i 's/plugins=(git)/plugins=(git pyenv ssh-agent direnv)/' ~/.zshrc

cat << 'EOF' > ~/.zprofile
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init --path)"
EOF

# 5. Activate Pyenv immediately for the rest of the script
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init --path)"

# 6. Install Python (this takes about 5 minutes)
echo "🐍 Installing Python ${PYTHON_VERSION} (please wait)..."
pyenv install -s ${PYTHON_VERSION}
pyenv virtualenv ${PYTHON_VERSION} ${VENV_NAME}
pyenv global ${VENV_NAME}

# 7. Install Python packages for GCP
echo "📦 Installing GCP libraries..."
pip install -U pip
pip install google-cloud-storage google-cloud-bigquery

echo "✅ Installation completed successfully!"
