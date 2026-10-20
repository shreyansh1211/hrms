#!/usr/bin/env bash
# One-time VPS preparation for Infisetu MIS (Ubuntu 22.04/24.04 or Debian 12). Safe to re-run.
#   sudo bash deploy/setup-vps.sh
# Installs Docker, Caddy, a 2 GB swap file, and a firewall that exposes only SSH/HTTP/HTTPS.
# It does NOT install the tracker (see deploy/DEPLOY_CHECKLIST.md step 5) or start the HRMS.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)"; exit 1; }
export DEBIAN_FRONTEND=noninteractive

echo "==> Packages"
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg ufw fail2ban unattended-upgrades \
    debian-keyring debian-archive-keyring apt-transport-https >/dev/null

echo "==> Docker"
if ! command -v docker >/dev/null; then
    curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null

echo "==> Caddy"
if ! command -v caddy >/dev/null; then
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq; apt-get install -y -qq caddy >/dev/null
fi

echo "==> Swap (2 GB safety net)"
if ! swapon --show | grep -q .; then
    fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl -w vm.swappiness=10 >/dev/null
    echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
fi

echo "==> Firewall (22, 80, 443 only)"
ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
# NOTE: published Docker ports bypass ufw, which is why compose binds db/redis to 127.0.0.1 only.

systemctl enable --now fail2ban >/dev/null 2>&1 || true
echo "Done. Next: DEPLOY_CHECKLIST.md step 3."
