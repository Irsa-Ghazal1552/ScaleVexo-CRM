#!/usr/bin/env bash
# Encrypted off-server backup of the PostgreSQL database with restic (CRM13).
# Schedule daily with cron on the server, e.g.:
#   15 2 * * *  cd /opt/scalevexo-crm && ./infra/backup.sh >> /var/log/scalevexo-backup.log 2>&1
#
# Needs in .env: RESTIC_REPOSITORY (e.g. s3:https://s3.eu-central-1.amazonaws.com/bucket/crm or b2:bucket:crm)
#                RESTIC_PASSWORD  (keep a copy somewhere safe - backups cannot be restored without it)
# plus the storage provider credentials restic needs (AWS_ACCESS_KEY_ID / B2_ACCOUNT_ID ...).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DUMP_DIR=$(mktemp -d)
trap 'rm -rf "$DUMP_DIR"' EXIT

echo "[$STAMP] dumping database"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-scalevexo}" -d "${POSTGRES_DB:-scalevexo}" --format=custom > "$DUMP_DIR/scalevexo-$STAMP.dump"

echo "[$STAMP] uploading encrypted snapshot"
restic snapshots >/dev/null 2>&1 || restic init
restic backup "$DUMP_DIR" --tag scalevexo-db

# Retention: 7 daily, 4 weekly, 6 monthly. Audit history lives inside these dumps.
restic forget --tag scalevexo-db --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
echo "[$STAMP] backup complete"
