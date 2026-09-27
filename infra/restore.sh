#!/usr/bin/env bash
# Restore the latest (or a chosen) restic snapshot into PostgreSQL.
#   ./infra/restore.sh            -> latest snapshot
#   ./infra/restore.sh 1a2b3c4d   -> specific snapshot id
# The CRM must be restored and checked in a staffed test before live use (G1 exit criterion).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

SNAPSHOT=${1:-latest}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

restic restore "$SNAPSHOT" --tag scalevexo-db --target "$WORK"
DUMP=$(find "$WORK" -name '*.dump' | sort | tail -n 1)
[ -n "$DUMP" ] || { echo "No dump found in snapshot"; exit 1; }

read -r -p "This REPLACES the current database with $(basename "$DUMP"). Type RESTORE to continue: " ok
[ "$ok" = "RESTORE" ] || { echo "Cancelled"; exit 1; }

docker compose stop api worker
docker compose exec -T db pg_restore -U "${POSTGRES_USER:-scalevexo}" -d "${POSTGRES_DB:-scalevexo}" --clean --if-exists --no-owner < "$DUMP"
docker compose start api worker
echo "Restore finished. Sign in and check a full customer journey (lead -> deal -> project -> ticket)."
