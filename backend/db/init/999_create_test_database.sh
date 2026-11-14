#!/bin/bash
# After the primary database is initialized, create the isolated pytest database.
set -euo pipefail

TEST_DB="${CHATVECTOR_TEST_DATABASE:-chatvector_test}"
INIT_DIR="/docker-entrypoint-initdb.d"

psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <<-EOSQL
SELECT 'CREATE DATABASE ${TEST_DB}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${TEST_DB}')\gexec
EOSQL

for f in $(ls "${INIT_DIR}"/*.sql 2>/dev/null | sort); do
  psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${TEST_DB}" -f "$f"
done