#!/usr/bin/env bash
# Generate dryfit synthetic events into local Postgres + ingest into PostHog Project B.
#
# Prereqs:
#   - dryfit cloned somewhere; pass DRYFIT_DIR env var (default ~/code/dryfit).
#   - Local Postgres reachable at $DRYFIT_PG_DSN (default postgresql:///dryfit).
#     dryfit's own scripts (postgres-local-init, postgres-local-start) handle setup.
#   - PostHog Project B keys + host loaded into env (source ~/.claude/secrets/mason-flash3.env).
#
# Outputs:
#   ./artifacts/<dataset_id>/manifest.json
#   ./artifacts/<dataset_id>/ground_truth.json
#   stdout: ingest summary JSON {sent, skipped, batches, elapsed_sec}.
#
# Usage:
#   ./generate.sh                                 # default scenario: posthog_seat_based_mvp
#   ./generate.sh posthog_freemium_to_paid_mvp    # override scenario
#   DRYFIT_DIR=/path/to/dryfit ./generate.sh
#   ./generate.sh --dry-run                       # generate but don't post to PostHog

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Args ───────────────────────────────────────────────────────────────
SCENARIO="${1:-posthog_seat_based_mvp}"
EXTRA_FLAGS=()
DRY_RUN=""
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN="--dry-run"; shift ;;
    *) EXTRA_FLAGS+=("$1"); shift ;;
  esac
done

# ── Env ────────────────────────────────────────────────────────────────
# dryfit now lives in this same repo; default to the checkout this script is in.
: "${DRYFIT_DIR:=$REPO_DIR}"
: "${DRYFIT_PG_DSN:=postgresql:///dryfit}"
: "${POSTHOG_HOST:?POSTHOG_HOST must be set (e.g. https://us.posthog.com)}"
: "${POSTHOG_PROJECT_API_KEY:?POSTHOG_PROJECT_API_KEY must be set (phc_...)}"

if [[ ! -d "$DRYFIT_DIR" ]]; then
  echo "ERROR: DRYFIT_DIR=$DRYFIT_DIR not found." >&2
  echo "Clone with: gh repo clone getbeton/dryfit $DRYFIT_DIR" >&2
  exit 1
fi

CONFIG="$DRYFIT_DIR/configs/${SCENARIO}.yaml"
if [[ ! -f "$CONFIG" ]]; then
  echo "ERROR: scenario config not found: $CONFIG" >&2
  echo "Available scenarios:" >&2
  ls "$DRYFIT_DIR/configs/" 2>/dev/null | sed 's/\.yaml$//' | sed 's/^/  - /' >&2
  exit 1
fi

OUT_DIR="$SCRIPT_DIR/artifacts/${SCENARIO}"
mkdir -p "$OUT_DIR"

# ── Generate (writes to local Postgres + emits ground_truth.json) ──────
echo ">> dryfit generate scenario=${SCENARIO} → ${OUT_DIR}"
(
  cd "$DRYFIT_DIR"
  uv run dryfit -c "$CONFIG" --output-dir "$OUT_DIR" --print-summary "${EXTRA_FLAGS[@]}"
)

# ── Ingest into PostHog ────────────────────────────────────────────────
echo ">> ingest dryfit events into PostHog ${POSTHOG_HOST} project_api_key=${POSTHOG_PROJECT_API_KEY:0:8}…"
python3 "$SCRIPT_DIR/posthog_ingest.py" \
  --dsn "$DRYFIT_PG_DSN" \
  --posthog-host "$POSTHOG_HOST" \
  --project-api-key "$POSTHOG_PROJECT_API_KEY" \
  --batch-size 100 \
  $DRY_RUN

# ── Summary ────────────────────────────────────────────────────────────
echo ""
echo ">> manifest:     $OUT_DIR/manifest.json"
echo ">> ground truth: $OUT_DIR/ground_truth.json"
echo ">> events written to Postgres ($DRYFIT_PG_DSN) AND posted to PostHog $POSTHOG_HOST"
echo ">> done."
