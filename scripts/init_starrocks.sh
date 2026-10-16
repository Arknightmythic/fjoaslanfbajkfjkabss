#!/bin/bash
set -eu

DB_NAME="${DB_NAME:-synchrono}"
DB_USER="${DB_USER:-synchrono_readonly}"
STARROCKS_HOST="${STARROCKS_HOST:-starrocks}"
STARROCKS_PORT="${STARROCKS_PORT:-9030}"

if [ -z "${DB_PASSWORD:-}" ]; then
  echo "Error: DB_PASSWORD is required but not set." >&2
  exit 1
fi

# ponytail: ceiling is strict alnum identifiers and URL-safe passwords; upgrade path is SQL-escaping literals and quoting parser if arbitrary characters needed
case "$DB_NAME" in
  *[!a-zA-Z0-9_]*|"")
    echo "Error: Invalid DB_NAME: only alphanumeric and underscore allowed" >&2
    exit 1
    ;;
esac

case "$DB_USER" in
  *[!a-zA-Z0-9_]*|"")
    echo "Error: Invalid DB_USER: only alphanumeric and underscore allowed" >&2
    exit 1
    ;;
esac

case "$DB_PASSWORD" in
  *[!a-zA-Z0-9_.~-]*|"")
    echo "Error: Invalid DB_PASSWORD: only URL-safe characters allowed" >&2
    exit 1
    ;;
esac

case "$STARROCKS_PORT" in
  *[!0-9]*|"")
    echo "Error: Invalid STARROCKS_PORT: must be numeric" >&2
    exit 1
    ;;
esac

MAX_RETRIES=30
RETRY_COUNT=0
export MYSQL_PWD=""

until mysql -h "$STARROCKS_HOST" -P "$STARROCKS_PORT" -u root -e "SELECT 1;" >/dev/null 2>&1; do
  RETRY_COUNT=$((RETRY_COUNT + 1))
  if [ "$RETRY_COUNT" -ge "$MAX_RETRIES" ]; then
    echo "Error: StarRocks did not become ready after ${MAX_RETRIES} attempts." >&2
    exit 1
  fi
  sleep 2
done

mysql -h "$STARROCKS_HOST" -P "$STARROCKS_PORT" -u root <<EOSQL
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\`;
CREATE USER IF NOT EXISTS '${DB_USER}'@'%' IDENTIFIED BY '${DB_PASSWORD}';
ALTER USER '${DB_USER}'@'%' IDENTIFIED BY '${DB_PASSWORD}';
GRANT SELECT ON ALL TABLES IN DATABASE \`${DB_NAME}\` TO USER '${DB_USER}'@'%';
EOSQL

echo "StarRocks initialized database '${DB_NAME}' and read-only user '${DB_USER}' successfully."
