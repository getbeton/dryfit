#!/usr/bin/env bash
# End-to-end: trigger a Mason run against the test workspace and score it.
#
# Assumes the test rig is already set up:
#   1. dryfit synthetic data already ingested into PostHog Project B
#      (run ./generate.sh first if not).
#   2. Inspector dev server running on $INSPECTOR_URL (default http://localhost:3000)
#      with AGENT_API_URL=http://localhost:8000.
#   3. Mason ADK server running on $AGENT_API_URL (default http://localhost:8000)
#      against the v0.0.2 app, with BATCH_HYPOTHESES=true and Langfuse env loaded.
#   4. The test workspace bootstrapped (run bootstrap_workspace.sh first) and
#      authenticated cookie/JWT available in $INSPECTOR_AUTH_COOKIE.
#
# Steps:
#   a. POST /api/onboarding/complete on Inspector → triggers AgentService.triggerAnalysis
#      → spawns Mason session pointed at PostHog Project B.
#   b. Poll Inspector workspace_agent_sessions until status=completed|failed.
#   c. Locate Mason's experiment_report.json artifact (latest run).
#   d. Score against dryfit ground_truth.json. Write summary.
#
# Usage:
#   ./run.sh
#   SCENARIO=posthog_seat_based_mvp ./run.sh
#   POLL_TIMEOUT_SEC=600 ./run.sh

set -euo pipefail

# NOTE: this is the single-scenario, LOCAL-Mason variant — it locates Mason's
# experiment_report.json on the local filesystem ($SIGNAL_AGENT_ARTIFACT_DIR).
# For the Railway-deployed Mason flow, use run_matrix.py, which pulls the report
# off the container via `railway ssh`.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Config (env-driven) ────────────────────────────────────────────────
: "${SCENARIO:=posthog_seat_based_mvp}"
: "${INSPECTOR_URL:=http://localhost:3000}"
: "${AGENT_API_URL:=http://localhost:8000}"
: "${POLL_INTERVAL_SEC:=10}"
: "${POLL_TIMEOUT_SEC:=900}"
: "${INSPECTOR_AUTH_COOKIE:?INSPECTOR_AUTH_COOKIE must be set (Supabase auth cookie for vlad@getbeton.info)}"

ARTIFACTS_DIR="$SCRIPT_DIR/artifacts"
GROUND_TRUTH="$ARTIFACTS_DIR/${SCENARIO}/ground_truth.json"
OUT_DIR="$ARTIFACTS_DIR/${SCENARIO}/scoring"
mkdir -p "$OUT_DIR"

if [[ ! -f "$GROUND_TRUTH" ]]; then
  echo "ERROR: ground truth not found at $GROUND_TRUTH" >&2
  echo "Run ./generate.sh first." >&2
  exit 1
fi

# ── Health checks ──────────────────────────────────────────────────────
echo ">> health-check Inspector $INSPECTOR_URL"
curl -fsS "$INSPECTOR_URL/api/healthcheck" >/dev/null 2>&1 || \
  curl -fsS "$INSPECTOR_URL" -o /dev/null || {
    echo "ERROR: Inspector not reachable at $INSPECTOR_URL" >&2
    exit 1
  }

echo ">> health-check Mason ADK $AGENT_API_URL"
curl -fsS "$AGENT_API_URL/list-apps" >/dev/null 2>&1 || \
  curl -fsS "$AGENT_API_URL" -o /dev/null || {
    echo "ERROR: Mason ADK server not reachable at $AGENT_API_URL" >&2
    echo "Start with: adk api_server --host 0.0.0.0 --port 8000 <path-to-inspector-ml-backend>/projects/upsell_ranker/versions/v0.0.2" >&2
    exit 1
  }

# ── Trigger ────────────────────────────────────────────────────────────
echo ">> POST $INSPECTOR_URL/api/onboarding/complete"
TRIGGER_RESP="$(curl -fsS -X POST \
  -H "Cookie: $INSPECTOR_AUTH_COOKIE" \
  -H "Content-Type: application/json" \
  "$INSPECTOR_URL/api/onboarding/complete")"
echo "   response: $TRIGGER_RESP"

# Onboarding-complete schedules trigger via after(). Give Inspector a moment to
# create the session row before we poll for it.
sleep 5

# ── Poll the latest workspace_agent_sessions row ───────────────────────
echo ">> polling Mason session status (timeout=${POLL_TIMEOUT_SEC}s, interval=${POLL_INTERVAL_SEC}s)"
DEADLINE=$(( $(date +%s) + POLL_TIMEOUT_SEC ))
SESSION_ID=""
SESSION_STATUS=""
while [[ $(date +%s) -lt $DEADLINE ]]; do
  RESP="$(curl -fsS \
    -H "Cookie: $INSPECTOR_AUTH_COOKIE" \
    "$INSPECTOR_URL/api/agent/sessions/latest" 2>/dev/null || true)"
  if [[ -n "$RESP" ]]; then
    SESSION_ID="$(echo "$RESP" | python3 -c 'import json,sys;d=json.load(sys.stdin); print(d.get("session_id",""))' 2>/dev/null || true)"
    SESSION_STATUS="$(echo "$RESP" | python3 -c 'import json,sys;d=json.load(sys.stdin); print(d.get("status",""))' 2>/dev/null || true)"
    echo "   session=$SESSION_ID status=$SESSION_STATUS"
    if [[ "$SESSION_STATUS" == "completed" || "$SESSION_STATUS" == "failed" ]]; then
      break
    fi
  fi
  sleep "$POLL_INTERVAL_SEC"
done

if [[ "$SESSION_STATUS" != "completed" ]]; then
  echo "WARN: session did not reach 'completed' (last status: $SESSION_STATUS). Continuing to score whatever Mason produced." >&2
fi

# ── Locate latest experiment report ────────────────────────────────────
SIGNAL_AGENT_ARTIFACTS="${SIGNAL_AGENT_ARTIFACT_DIR:?set SIGNAL_AGENT_ARTIFACT_DIR to the local Mason signal_agent/artifacts dir}"
LATEST_RUN="$(ls -1dt "$SIGNAL_AGENT_ARTIFACTS"/run_* 2>/dev/null | head -1 || true)"
if [[ -z "$LATEST_RUN" ]]; then
  echo "ERROR: no Mason runs found under $SIGNAL_AGENT_ARTIFACTS" >&2
  exit 1
fi
REPORT="$LATEST_RUN/experiment_report.json"
if [[ ! -f "$REPORT" ]]; then
  # finalize_experiment_report writes the report to state, not always to a
  # standalone file. Try to find any report-shaped artifact.
  REPORT="$(ls -1t "$LATEST_RUN"/*.json 2>/dev/null | head -1 || true)"
fi
if [[ -z "$REPORT" || ! -f "$REPORT" ]]; then
  echo "ERROR: no experiment_report.json found in $LATEST_RUN" >&2
  exit 1
fi
echo ">> scoring against report=$REPORT"

# ── Score ──────────────────────────────────────────────────────────────
python3 "$SCRIPT_DIR/score.py" \
  --experiment-report "$REPORT" \
  --ground-truth "$GROUND_TRUTH" \
  --output-dir "$OUT_DIR"

echo ""
echo ">> done. session=$SESSION_ID status=$SESSION_STATUS"
echo ">> scoring written to $OUT_DIR"
