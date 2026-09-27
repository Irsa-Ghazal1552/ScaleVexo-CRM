#!/bin/sh
set -e

# Wait for PostgreSQL
if [ "${DB_ENGINE:-postgres}" = "postgres" ]; then
  echo "Waiting for database at ${POSTGRES_HOST:-db}..."
  i=0
  until pg_isready -h "${POSTGRES_HOST:-db}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-scalevexo}" >/dev/null 2>&1; do
    i=$((i+1)); [ $i -gt 60 ] && echo "Database not reachable" && exit 1
    sleep 1
  done
fi

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  # Migrations are committed in apps/api/modules/*/migrations. Warn if the models have drifted from them.
  python manage.py makemigrations --check --dry-run >/dev/null 2>&1 \
    || echo "WARNING: model changes without migrations - run 'python manage.py makemigrations' and commit the result"
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput >/dev/null
  python manage.py bootstrap_workspace || echo "Workspace not created yet: set OWNER_EMAIL and OWNER_PASSWORD in .env"
  if [ "${SEED_DEMO:-false}" = "true" ]; then
    python manage.py seed_demo
  fi
fi

exec "$@"
