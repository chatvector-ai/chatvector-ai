#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="docker-compose.prod.yml"
BASE_URL="${BASE_URL:-http://localhost:8000}"
PYTHON="${PYTHON:-python3}"

TENANT_ID="ci-smoke-tenant-$(date +%s)"
TENANT_NAME="CI Smoke Tenant"

FIXTURE_DIR="/tmp/chatvector-e2e"
FIXTURE_FILE="${FIXTURE_DIR}/fixture.txt"

cleanup() {
    echo
    echo "==> Cleaning up"

    docker compose -f "$COMPOSE_FILE" down -v --remove-orphans
}

trap cleanup EXIT

echo "==> Starting production stack"

docker compose -f "$COMPOSE_FILE" up -d --build

echo "==> Waiting for API"

for i in $(seq 1 60); do
    if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
        echo "API is healthy"
        break
    fi

    if [ "$i" -eq 60 ]; then
        echo "ERROR: API did not become healthy"

        docker compose -f "$COMPOSE_FILE" ps

        echo
        echo "==> API logs"
        docker compose -f "$COMPOSE_FILE" logs api

        exit 1
    fi

    sleep 2
done

echo "==> Creating fixture"

mkdir -p "$FIXTURE_DIR"

cat > "$FIXTURE_FILE" <<'EOF'
ChatVector production smoke test.

This document exists to verify that the production Docker Compose
stack can upload a document, process it through the Redis-backed
ingestion queue, and answer an authenticated question about it.

The expected result is a completed document with at least one chunk.
EOF

echo "==> Creating tenant and API key"

CLI_OUTPUT="$(
    docker compose -f "$COMPOSE_FILE" run --rm api \
        python -m cli create-tenant-key \
        --tenant "$TENANT_NAME" \
        --tenant-id "$TENANT_ID"
)"

echo "$CLI_OUTPUT"

API_KEY="$(
    printf '%s\n' "$CLI_OUTPUT" |
        grep -Eo 'cv_live_[A-Za-z0-9_.-]+' |
        head -1
)"

if [ -z "$API_KEY" ]; then
    echo "ERROR: failed to extract generated API key"
    exit 1
fi

echo "==> Tenant and API key generated"

echo "==> Uploading fixture"

UPLOAD_RESPONSE="$(
    curl -fsS \
        -X POST \
        -H "Authorization: Bearer ${API_KEY}" \
        -F "file=@${FIXTURE_FILE}" \
        "${BASE_URL}/upload"
)"

echo "$UPLOAD_RESPONSE"

DOC_ID="$(
    printf '%s\n' "$UPLOAD_RESPONSE" |
        "$PYTHON" -c '
import json
import sys

data = json.load(sys.stdin)

document_id = data.get("document_id")

if not document_id:
    raise SystemExit("Upload response did not contain document_id")

print(document_id)
'
)"

echo "Document ID: $DOC_ID"

echo "==> Waiting for document ingestion"

for i in $(seq 1 60); do
    STATUS_RESPONSE="$(
        curl -fsS \
            -H "Authorization: Bearer ${API_KEY}" \
            "${BASE_URL}/documents/${DOC_ID}/status"
    )"

    STATUS="$(
        printf '%s\n' "$STATUS_RESPONSE" |
            "$PYTHON" -c '
import json
import sys

data = json.load(sys.stdin)
print(data.get("status", "unknown"))
'
    )"

    echo "Attempt ${i}: status=${STATUS}"

    if [ "$STATUS" = "completed" ]; then
        echo "$STATUS_RESPONSE"
        break
    fi

    if [ "$STATUS" = "failed" ]; then
        echo "ERROR: document ingestion failed"
        echo "$STATUS_RESPONSE"

        echo
        echo "==> API logs"
        docker compose -f "$COMPOSE_FILE" logs --tail=200 api

        exit 1
    fi

    if [ "$i" -eq 60 ]; then
        echo "ERROR: document ingestion timed out"
        echo "$STATUS_RESPONSE"

        echo
        echo "==> API logs"
        docker compose -f "$COMPOSE_FILE" logs --tail=200 api

        exit 1
    fi

    sleep 2
done

echo "==> Sending authenticated chat request"

CHAT_RESPONSE="$(
    curl -fsS \
        -X POST \
        -H "Authorization: Bearer ${API_KEY}" \
        -H "Content-Type: application/json" \
        -d "{
            \"question\": \"What is this document about?\",
            \"doc_id\": \"${DOC_ID}\"
        }" \
        "${BASE_URL}/chat"
)"

echo
echo "Chat response:"
echo "$CHAT_RESPONSE"

echo
echo "==> Validating chat response"

printf '%s\n' "$CHAT_RESPONSE" |
    "$PYTHON" -c '
import json
import sys

data = json.load(sys.stdin)

if not isinstance(data, dict):
    raise SystemExit("Chat response is not a JSON object")

if not data:
    raise SystemExit("Chat response is empty")

print("Chat response fields:", ", ".join(data.keys()))

status = data.get("status")

# The ChatVector API returns "ok" for a successful chat request.
if status != "ok":
    error = data.get("error")

    print()
    print("ERROR: Chat request failed")
    print("Status:", status)
    print("Error:", error)

    raise SystemExit(1)

answer = data.get("answer")

if not isinstance(answer, str) or not answer.strip():
    raise SystemExit("Chat response contains no answer")

sources = data.get("sources")

if not isinstance(sources, list) or not sources:
    raise SystemExit("Chat response contains no sources")

print("Chat response status: ok")
print("Answer:", answer)
print("Sources:", len(sources))
'

echo
echo "========================================="
echo "Production E2E smoke test PASSED"
echo "========================================="
