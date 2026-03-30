#!/bin/bash
# Cloudflare Tunnel Credentials Validator
#
# Purpose: Validate that cloudflared credentials file has all required fields
# including the Endpoint field which causes issues when empty.
#
# This script runs BEFORE starting the cloudflared service.

set -e

CREDS_FILE="${1:-./config/cloudflared-credentials.json}"
LOG_PREFIX="[CLOUDFLARE-VALIDATOR]"

if [ ! -f "$CREDS_FILE" ]; then
    echo "$LOG_PREFIX ERROR: Credentials file not found: $CREDS_FILE"
    exit 1
fi

# Validate JSON format
if ! jq empty "$CREDS_FILE" 2>/dev/null; then
    echo "$LOG_PREFIX ERROR: Credentials file is not valid JSON: $CREDS_FILE"
    exit 1
fi

# Check required fields
REQUIRED_FIELDS=("AccountTag" "TunnelSecret" "TunnelID" "Endpoint")
for field in "${REQUIRED_FIELDS[@]}"; do
    value=$(jq -r ".$field // empty" "$CREDS_FILE")

    if [ -z "$value" ]; then
        echo "$LOG_PREFIX ERROR: Required field '$field' is missing or empty"
        echo "$LOG_PREFIX"
        echo "$LOG_PREFIX The Endpoint field cannot be empty. This causes tunnel connection failures."
        echo "$LOG_PREFIX"
        echo "$LOG_PREFIX To fix, regenerate tunnel credentials:"
        echo "$LOG_PREFIX   cloudflared tunnel delete papyrus-tunnel"
        echo "$LOG_PREFIX   cloudflared tunnel create papyrus-tunnel"
        echo "$LOG_PREFIX   cp ~/.cloudflared/<tunnel-id>.json $CREDS_FILE"
        echo "$LOG_PREFIX   # Then manually add: \"Endpoint\": \"https://tunnel.cloudflare.com\""
        echo "$LOG_PREFIX"
        exit 1
    fi

    echo "$LOG_PREFIX ✓ $field: ${value:0:30}..."
done

# Extra validation: Endpoint should be a valid URL
endpoint=$(jq -r '.Endpoint' "$CREDS_FILE")
if [[ ! "$endpoint" =~ ^https:// ]]; then
    echo "$LOG_PREFIX ERROR: Endpoint is not a valid HTTPS URL: $endpoint"
    exit 1
fi

echo "$LOG_PREFIX ✅ All credentials validated successfully"
echo "$LOG_PREFIX Tunnel ID: $(jq -r '.TunnelID' "$CREDS_FILE")"
echo "$LOG_PREFIX Endpoint: $endpoint"
