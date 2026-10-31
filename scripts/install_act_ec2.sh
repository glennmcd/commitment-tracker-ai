#!/bin/bash

sudo dnf update -y
sudo dnf install git -y

sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker          # or log out and back in
docker run --rm hello-world

curl --proto '=https' --tlsv1.2 -sSf https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash -s -- -b /usr/local/bin
act --version

git clone https://github.com/glennmcd/commitment-tracker-ai.git commitment-tracker-ai
git clone https://github.com/glennmcd/terminal-commands.git terminal-commands
cd terminal-commands
. ./install.sh
cd ../commitment-tracker-ai

actlog() {
  mkdir -p ~/act-logs
  local f=~/act-logs/act-$(date +%Y%m%d-%H%M%S).log
  local start=$SECONDS
  act "$@" 2>&1 | tee "$f"
  local rc=${PIPESTATUS[0]}
  local elapsed=$((SECONDS - start))
  printf 'Elapsed: %dm %02ds\n' $((elapsed / 60)) $((elapsed % 60)) | tee -a "$f"
  echo "Log saved to $f"
  return $rc
}

actlog
