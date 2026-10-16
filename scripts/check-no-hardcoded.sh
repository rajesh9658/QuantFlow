#!/usr/bin/env bash
# ==============================================================================
# QuantFlow CI Check: Verify Zero Hardcoded Values in Frontend
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SRC_DIR="${REPO_ROOT}/dashboard/src"

if [ ! -d "${SRC_DIR}" ]; then
    echo "Error: Dashboard src directory not found at ${SRC_DIR}"
    exit 1
fi

echo "Running Zero Hardcoded Values check on ${SRC_DIR}..."
FAILED=0

# 1. Check for literal URLs (http://, https://, ws://, wss://) outside src/config/ and src/test/
URL_MATCHES=$(grep -rnE "(https?|wss?)://" "${SRC_DIR}" \
    --exclude-dir=config \
    --exclude-dir=test \
    --exclude-dir=types || true)

if [ -n "${URL_MATCHES}" ]; then
    echo "FAILED: Found hardcoded URL outside src/config/:"
    echo "${URL_MATCHES}"
    FAILED=1
fi

# 2. Check for localhost or IP addresses outside src/config/ and src/test/
HOST_MATCHES=$(grep -rnE "(localhost|127\.0\.0\.1)" "${SRC_DIR}" \
    --exclude-dir=config \
    --exclude-dir=test || true)

if [ -n "${HOST_MATCHES}" ]; then
    echo "FAILED: Found hardcoded host/IP address outside src/config/:"
    echo "${HOST_MATCHES}"
    FAILED=1
fi

# 3. Check for literal API route strings (/api/v1) outside src/config/endpoints.ts and src/test/
API_MATCHES=$(grep -rn "/api/v1" "${SRC_DIR}" \
    --exclude="endpoints.ts" \
    --exclude-dir=test || true)

if [ -n "${API_MATCHES}" ]; then
    echo "FAILED: Found literal API route string outside src/config/endpoints.ts:"
    echo "${API_MATCHES}"
    FAILED=1
fi

# 4. Check for process.env or import.meta.env outside src/config/env.ts
ENV_MATCHES=$(grep -rnE "(process\.env|import\.meta\.env)" "${SRC_DIR}" \
    --exclude="env.ts" \
    --exclude-dir=test || true)

if [ -n "${ENV_MATCHES}" ]; then
    echo "FAILED: Found environment variable access outside src/config/env.ts:"
    echo "${ENV_MATCHES}"
    FAILED=1
fi

if [ ${FAILED} -ne 0 ]; then
    echo "Zero Hardcoded Values check FAILED."
    exit 1
fi

echo "Zero Hardcoded Values check PASSED."
exit 0
