#!/usr/bin/env bash
# CampusEvent one-shot deploy script for Ubuntu 22.04 / 24.04
# Run as root:  bash deploy.sh
set -euo pipefail

APP_DIR=/opt/CampusEvent
DATA_DIR=/var/lib/campusevent
SVC_USER=www-data
SVC=campusevent

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root (sudo bash deploy.sh)"
  exit 1
fi

if [ ! -f "$APP_DIR/wsgi.py" ]; then
  echo "ERROR: $APP_DIR/wsgi.py not found. Upload the code to $APP_DIR first."
  exit 1
fi

echo "==> 1/7 install system packages"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip nginx

echo "==> 2/7 prepare data dir"
mkdir -p "$DATA_DIR"

echo "==> 3/7 create venv and install deps"
cd "$APP_DIR"
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip -q
./.venv/bin/pip install -r requirements.txt -q

echo "==> 4/7 run tests (fail fast)"
./.venv/bin/python -m pytest -q

echo "==> 5/7 seed database if missing"
if [ ! -f "$DATA_DIR/campusevent.sqlite3" ]; then
  DATABASE_PATH="$DATA_DIR/campusevent.sqlite3" ./.venv/bin/python seed.py
else
  echo "    database exists, skip seeding"
fi

echo "==> 6/7 fix permissions and install units"
chown -R "$SVC_USER:$SVC_USER" "$APP_DIR" "$DATA_DIR"
install -m 644 "$APP_DIR/deploy/$SVC.service" "/etc/systemd/system/$SVC.service"
install -m 644 "$APP_DIR/deploy/nginx-campusevent.conf" "/etc/nginx/sites-available/$SVC.conf"
ln -sf "/etc/nginx/sites-available/$SVC.conf" "/etc/nginx/sites-enabled/$SVC.conf"
rm -f /etc/nginx/sites-enabled/default

echo "==> 7/7 enable and restart services"
systemctl daemon-reload
systemctl enable --now "$SVC"
nginx -t
systemctl reload nginx

echo
echo "Deployed. Check with:"
echo "  systemctl status $SVC"
echo "  journalctl -u $SVC -n 50 --no-pager"
echo "  curl -I http://127.0.0.1/"
echo
echo "Remember: open port 80 in the Tencent Cloud security group."
