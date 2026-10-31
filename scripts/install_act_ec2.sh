#!/bin/bash

sudo dnf update -y
sudo dnf install git -y
sudo dnf install -y 'dnf-command(config-manager)'
sudo dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo
sudo dnf install -y gh
#gh auth login
#ssh-keygen -t ed25519 -C "ec2-act-box"
#cat ~/.ssh/id_ed25519.pub
#Copy the output into GitHub: Settings → SSH and GPG keys → New SSH key. Then test it:
#ssh -T git@github.com
#Update clone from https to SSH if needed
#git remote set-url origin git@github.com:glennmcd/commitment-tracker-ai.git
#git remote set-url origin git@github.com:glennmcd/terminal-commands.git

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
