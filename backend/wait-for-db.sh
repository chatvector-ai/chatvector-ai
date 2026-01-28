#!/bin/sh
# Wait for Postgres to be ready before starting the API
set -e

host="$1"
shift
cmd="$@"

echo "Waiting for Postgres at $host:5432..."

until pg_isready -h "$host" -p 5432 -U "postgres"; do
  sleep 1
done

echo "Postgres is ready — executing command"
exec $cmd
