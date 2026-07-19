#!/usr/bin/env bash
# Deploy a git ref to the running instance. Invoked by the GitHub
# Actions workflow through SSM run-command (as root), or by hand from
# an SSM session:
#
#   sudo bash /opt/morseweb/app/deploy/deploy.sh v1.2.0   # or main
#
# Schema migrations run automatically on first request (storage.py
# applies missing columns/tables on connect), so deploy is:
# fetch -> checkout -> pip install -> restart -> health check.

set -euo pipefail

REF="${1:-main}"
APP_DIR=/opt/morseweb/app
VENV_DIR=/opt/morseweb/venv

echo "== deploying ${REF} =="
cd "$APP_DIR"
sudo -u morseweb git fetch --tags origin
sudo -u morseweb git checkout --force "$REF"
# A branch ref needs a pull to move; a tag checkout is already exact.
if sudo -u morseweb git show-ref --verify --quiet "refs/heads/${REF}"; then
    sudo -u morseweb git reset --hard "origin/${REF}"
fi

sudo -u morseweb "$VENV_DIR/bin/pip" install --quiet -r deploy/requirements-prod.txt

systemctl restart morseweb

echo "== health check =="
for _ in $(seq 1 15); do
    if curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then
        echo "deploy ok: $(sudo -u morseweb git rev-parse --short HEAD)"
        exit 0
    fi
    sleep 2
done

echo "deploy FAILED: /healthz never came up; check journalctl -u morseweb" >&2
exit 1
