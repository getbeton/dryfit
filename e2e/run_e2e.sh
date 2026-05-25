#!/usr/bin/env bash
# One-command Beton E2E: generate synthetic data and fan it out to all three
# sinks, then trigger Mason and score against ground truth.
#
#   1. Supabase  — bootstrap the Inspector test workspace + data_sources
#                  (e2e/bootstrap_workspace.mjs)
#   2. PostHog   — generate dryfit events in-memory and ingest into Project B
#                  (e2e/dryfit_to_posthog.py)
#   3. Beton     — trigger Mason on the Railway e2e service, pull the report,
#                  and score it (e2e/run_matrix.py + e2e/score.py)
#
# Env: source your e2e env first (see e2e/.env.example). The mason-flash3 rig
# keeps these in ~/.claude/secrets/mason-flash3.env. Note the Supabase var
# remapping below: bootstrap_workspace.mjs reads SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY,
# while the rig stores them as SUPABASE_BRANCH_URL / SUPABASE_SERVICE_ROLE_KEY.
#
# Usage:
#   source ~/.claude/secrets/mason-flash3.env
#   MASON_REPO_DIR=/path/to/inspector-ml-backend ./e2e/run_e2e.sh
#   SCENARIO=posthog_freemium_to_paid_mvp ./e2e/run_e2e.sh
#   STAGE=posthog ./e2e/run_e2e.sh          # run a single stage: supabase|posthog|beton

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

: "${SCENARIO:=posthog_seat_based_mvp}"
: "${STAGE:=all}"
: "${POSTHOG_HOST:?POSTHOG_HOST must be set}"
: "${POSTHOG_PROJECT_API_KEY:?POSTHOG_PROJECT_API_KEY must be set (phc_…)}"

CONFIG="$REPO_DIR/configs/${SCENARIO}.yaml"
OUT_DIR="$SCRIPT_DIR/artifacts/${SCENARIO}"
mkdir -p "$OUT_DIR"
[[ -f "$CONFIG" ]] || { echo "ERROR: scenario config not found: $CONFIG" >&2; exit 1; }

run_supabase() {
  echo ">> [1/3] Supabase: bootstrap Inspector test workspace"
  # Remap rig var names → what bootstrap_workspace.mjs expects.
  SUPABASE_URL="${SUPABASE_URL:-${SUPABASE_BRANCH_URL:?set SUPABASE_BRANCH_URL or SUPABASE_URL}}" \
  SUPABASE_SERVICE_ROLE_KEY="${SUPABASE_SERVICE_ROLE_KEY:?set SUPABASE_SERVICE_ROLE_KEY}" \
    node "$SCRIPT_DIR/bootstrap_workspace.mjs" | tee "$OUT_DIR/workspace.json"
}

run_posthog() {
  echo ">> [2/3] PostHog: generate + ingest dryfit events into Project B"
  uv run --directory "$REPO_DIR" --with requests python "$SCRIPT_DIR/dryfit_to_posthog.py" \
    --config "$CONFIG" \
    --output-dir "$OUT_DIR" \
    --posthog-host "$POSTHOG_HOST" \
    --project-api-key "$POSTHOG_PROJECT_API_KEY"
}

run_beton() {
  echo ">> [3/3] Beton: trigger Mason on Railway + score"
  : "${MASON_REPO_DIR:?set MASON_REPO_DIR to the inspector-ml-backend checkout linked to the Railway e2e service}"
  python3 "$SCRIPT_DIR/run_matrix.py" \
    --output-dir "$OUT_DIR/matrix" \
    --repo-dir "$MASON_REPO_DIR"
}

case "$STAGE" in
  supabase) run_supabase ;;
  posthog)  run_posthog ;;
  beton)    run_beton ;;
  all)      run_supabase; run_posthog; run_beton ;;
  *) echo "ERROR: unknown STAGE=$STAGE (supabase|posthog|beton|all)" >&2; exit 2 ;;
esac

echo ">> done. artifacts under $OUT_DIR"
