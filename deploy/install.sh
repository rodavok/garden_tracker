#!/usr/bin/env bash
# One-shot installer to run INSIDE the Debian/Ubuntu LXC, as root.
# Assumes this repo is already present at /opt/garden (see README).
set -euo pipefail

APP_DIR=/opt/garden
SVC_USER=garden

echo "==> Installing OS packages"
apt-get update
# avahi-daemon publishes <hostname>.local on the LAN via mDNS, so the app is
# reachable at http://garden.local once the container hostname is 'garden'.
apt-get install -y python3 python3-venv python3-pip ca-certificates curl avahi-daemon

echo "==> Creating service user '$SVC_USER'"
if ! id "$SVC_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /usr/sbin/nologin "$SVC_USER"
fi

echo "==> Python venv + dependencies"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Seeding the database from data/seed/garden_produce.csv (skips rows already present)"
sudo -u "$SVC_USER" "$APP_DIR/venv/bin/python" -m app.seed || true

echo "==> Ownership"
chown -R "$SVC_USER":"$SVC_USER" "$APP_DIR"

echo "==> systemd unit + env file"
install -m 644 "$APP_DIR/deploy/garden.service" /etc/systemd/system/garden.service
mkdir -p /etc/garden
if [ ! -f /etc/garden/garden.env ]; then
  install -m 600 "$APP_DIR/deploy/garden.env.example" /etc/garden/garden.env
  chown "$SVC_USER":"$SVC_USER" /etc/garden/garden.env
fi
systemctl daemon-reload
systemctl enable --now avahi-daemon

if [ "$(hostname)" != "garden" ]; then
  echo
  echo "!! Container hostname is '$(hostname)', not 'garden'. For http://garden.local either:"
  echo "   - set the hostname in Proxmox (Options > Hostname) and reboot the container, or"
  echo "   - run:  hostnamectl set-hostname garden && systemctl restart avahi-daemon"
fi

cat <<MSG

==> Done. Next:
  systemctl enable --now garden
  systemctl status garden
  # then open http://garden.local  (or http://<container-ip>)

Optional nightly backup (as the $SVC_USER user):
  crontab -u $SVC_USER -e
  15 3 * * * GARDEN_BACKUP_DIR=/mnt/backups/garden $APP_DIR/deploy/backup.sh
MSG
