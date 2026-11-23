#!/usr/bin/env bash
# Load Observability Cloud tokens from secret files (if needed) and run the emitter.
# Never echo token values. Always exit 0 so a scheduler does not page on a single blip.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SECRETS="${GROKBOT_O11Y_SECRETS_DIR:-${HOME}/.config/grokbot-splunk-o11y/secrets}"

load_secret() {
  # $1 = env var name, $2 = filename under the secrets directory
  local var="$1"
  local file="$2"
  if [[ -n "${!var:-}" ]]; then
    return 0
  fi
  if [[ -r "$file" ]]; then
    # Read and trim whitespace without printing the value.
    printf -v "$var" '%s' "$(tr -d '[:space:]' < "$file")"
    export "$var"
  fi
}

load_secret SPLUNK_O11Y_REALM "${SECRETS}/REALM"
load_secret SPLUNK_O11Y_INGEST_TOKEN "${SECRETS}/INGEST_TOKEN"
# Alternate filenames some people prefer:
load_secret SPLUNK_O11Y_INGEST_TOKEN "${SECRETS}/SPLUNK_O11Y_INGEST_TOKEN"
load_secret SPLUNK_O11Y_API_TOKEN "${SECRETS}/API_TOKEN"
load_secret SPLUNK_O11Y_API_TOKEN "${SECRETS}/SPLUNK_O11Y_API_TOKEN"

if [[ -z "${SPLUNK_O11Y_INGEST_TOKEN:-}" ]]; then
  echo "o11y emit: ingest=err points=0 mts~0 ms=0 sources_fail=secrets err=missing_ingest_token alert=no" >&2
  exit 0
fi
if [[ -z "${SPLUNK_O11Y_REALM:-}" ]]; then
  echo "o11y emit: ingest=err points=0 mts~0 ms=0 sources_fail=config err=missing_realm alert=no" >&2
  exit 0
fi

# Prefer the repo's virtualenv python if a user later adds one; otherwise system python3.
PYTHON="${GROKBOT_PYTHON:-python3}"
cd "$ROOT"
exec "$PYTHON" "$ROOT/bin/emit.py" "$@"
