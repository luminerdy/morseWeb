#!/usr/bin/env bash
# Nightly SQLite snapshot to S3 (belt to Litestream's suspenders).
# Adapted from morsePi's backup script. Run by morseweb-backup.timer;
# reads BUCKET from /etc/morseweb/backup-env.
#
# Snapshots land at s3://$BUCKET/snapshots/morseweb-YYYY-MM-DD.sqlite3;
# add an S3 lifecycle rule to expire them (30 days is plenty).

set -euo pipefail

source /etc/morseweb/backup-env
DB=/opt/morseweb/app/data/morseweb.sqlite3
SNAPSHOT=$(mktemp /tmp/morseweb-backup.XXXXXX.sqlite3)
trap 'rm -f "$SNAPSHOT"' EXIT

# .backup takes a consistent copy even while the app is writing (WAL).
sqlite3 "$DB" ".backup '$SNAPSHOT'"
aws s3 cp "$SNAPSHOT" "s3://${BUCKET}/snapshots/morseweb-$(date -u +%F).sqlite3" --only-show-errors
echo "backup ok: morseweb-$(date -u +%F).sqlite3"
