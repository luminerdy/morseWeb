#!/usr/bin/env bash
# One-time provisioning for the morseWeb EC2 instance.
#
# Run as root (via an SSM session) on a fresh Ubuntu 24.04 arm64
# t4g.small after setting the three variables below. Idempotent enough
# to re-run after a partial failure.
#
#   sudo DOMAIN=morse.example.com BUCKET=my-morseweb-backups \
#        REPO=https://github.com/luminerdy/morseWeb.git \
#        bash setup_server.sh
#
# After it finishes: point DNS at this instance, then run
#   certbot --nginx -d $DOMAIN
# and finally scripts/make_admin.py (see docs/DEPLOY.md).

set -euo pipefail

DOMAIN="${DOMAIN:?set DOMAIN=your.domain}"
BUCKET="${BUCKET:?set BUCKET=your-s3-bucket}"
REPO="${REPO:-https://github.com/luminerdy/morseWeb.git}"

APP_DIR=/opt/morseweb/app
VENV_DIR=/opt/morseweb/venv
LITESTREAM_VERSION=0.3.13

echo "== packages =="
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3-venv python3-pip nginx certbot python3-certbot-nginx \
    sqlite3 git curl unzip

if ! command -v aws &>/dev/null; then
    curl -fsSL -o /tmp/awscliv2.zip "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip"
    unzip -q /tmp/awscliv2.zip -d /tmp
    /tmp/aws/install
fi

echo "== app user and directories =="
id -u morseweb &>/dev/null || useradd --system --create-home --shell /usr/sbin/nologin morseweb
mkdir -p /opt/morseweb
if [ ! -d "$APP_DIR/.git" ]; then
    git clone "$REPO" "$APP_DIR"
fi
mkdir -p "$APP_DIR/data"
chown -R morseweb:morseweb /opt/morseweb

echo "== python environment =="
[ -d "$VENV_DIR" ] || sudo -u morseweb python3 -m venv "$VENV_DIR"
sudo -u morseweb "$VENV_DIR/bin/pip" install --upgrade pip
sudo -u morseweb "$VENV_DIR/bin/pip" install -r "$APP_DIR/deploy/requirements-prod.txt"

echo "== app environment file =="
mkdir -p /etc/morseweb
if [ ! -f /etc/morseweb/env ]; then
    cat > /etc/morseweb/env <<EOF
MORSEWEB_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
MORSEWEB_SECURE_COOKIES=1
MORSEWEB_BEHIND_PROXY=1
MORSEWEB_EMAIL_BACKEND=ses
MORSEWEB_EMAIL_FROM=morseweb@${DOMAIN}
EOF
    chmod 600 /etc/morseweb/env
    echo "wrote /etc/morseweb/env (new secret key generated)"
else
    echo "/etc/morseweb/env already exists; leaving it alone"
fi

echo "== litestream =="
if ! command -v litestream &>/dev/null; then
    curl -fsSL -o /tmp/litestream.deb \
        "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-arm64.deb"
    dpkg -i /tmp/litestream.deb
fi
sed "s/YOUR_BUCKET/${BUCKET}/g" "$APP_DIR/deploy/litestream.yml" > /etc/litestream.yml

echo "== systemd units =="
cp "$APP_DIR/deploy/morseweb.service" /etc/systemd/system/morseweb.service
cp "$APP_DIR/deploy/morseweb-backup.service" /etc/systemd/system/morseweb-backup.service
cp "$APP_DIR/deploy/morseweb-backup.timer" /etc/systemd/system/morseweb-backup.timer
echo "BUCKET=${BUCKET}" > /etc/morseweb/backup-env
systemctl daemon-reload
systemctl enable --now morseweb litestream morseweb-backup.timer

echo "== nginx =="
sed "s/YOUR_DOMAIN/${DOMAIN}/g" "$APP_DIR/deploy/nginx-morseweb.conf" \
    > /etc/nginx/sites-available/morseweb
ln -sf /etc/nginx/sites-available/morseweb /etc/nginx/sites-enabled/morseweb
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "== done =="
echo "Next: point ${DOMAIN} DNS here, then run: certbot --nginx -d ${DOMAIN}"
echo "Health check: curl -s http://127.0.0.1:8000/healthz"
