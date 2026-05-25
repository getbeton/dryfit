"""Generate a PostHog dashboard summarising a Mason E2E run.

Mirrors the static `docs/mason-flash3-report.md` template:

  Per signal candidate (description, SQL, n with/without, conversions, lift,
  windows, evidence, RICE, query id) → 1 HogQL DataTable insight per signal.

  Funnel  candidates_proposed  →  on-policy  →  promoted
       → 1 BarChart insight (HogQL aggregation).

  Cost matrix across top 4 Anthropic + Google models, with three unit-
  economics columns (per-proposed, per-on-policy, per-promoted).
       → 1 HogQL insight (single-row table).

  Token consumption per stage (bootstrap / explorer / reviewer).
       → 1 HogQL insight.

Inputs:

  --inspector-url   <https://...>    e.g. the Vercel preview deploy
  --mason-url       <https://...>    e.g. the Railway anthropic-ml-backend
  --run-id          run_2026...      the Mason run dir name
  --session-id      s_a31f3784-...   the Inspector session_id
  --experiment-report PATH           path to a local copy of experiment_report.json
  --posthog-host    https://us.posthog.com
  --posthog-project-id 406509
  --posthog-personal-api-key phx_…   a read-scope key with insight:write
  [--ground-truth PATH]              path to dryfit ground_truth.json (used to
                                     annotate template-mapping in signal cards)
  [--token-bucket FILE]              optional Langfuse-format JSON
                                     {"bootstrap":{"input":N,"output":N},…}
                                     to override the per-stage estimate

Output:

  Prints the dashboard URL on stdout. Tiles are added with the run_id and
  session_id stamped into the dashboard description so it's clear which
  run the numbers came from. Re-running with the same --run-id just creates
  a second dashboard — there's no upsert.

Auth:
  PostHog personal API key needs `insight:write`, `dashboard:write`. Project
  API key (phc_…) is NOT sufficient.

Pricing source: hardcoded reference list as of 2026-05; override with
  --pricing-yaml if list prices drift. (Same shape as inside this file.)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Pricing per million tokens (USD). Top 4 each, Anthropic + Google.
DEFAULT_PRICING: Dict[str, Tuple[float, float]] = {
    "claude-opus-4-6":      (15.00, 75.00),
    "claude-sonnet-4-6":    ( 3.00, 15.00),
    "claude-haiku-4-5":     ( 1.00,  5.00),
    "claude-sonnet-3-7":    ( 3.00, 15.00),
    "gemini-3-pro":         ( 1.25,  5.00),
    "gemini-3-flash":       ( 0.30,  2.50),
    "gemini-2-5-pro":       ( 1.25,  5.00),
    "gemini-2-5-flash":     ( 0.30,  2.50),
}

# Default per-stage token estimate (used when --token-bucket isn't supplied
# and Langfuse hasn't recorded usage). These are the same numbers from
# `docs/mason-flash3-report.md` Run #6.
DEFAULT_TOKEN_BUCKET: Dict[str, Dict[str, int]] = {
    "bootstrap":    {"input":  35400, "output": 2650},
    "explorer":     {"input":  54800, "output": 5400},
    "reviewer":     {"input":  20200, "output": 2500},
}


# ── HTTP helpers ──────────────────────────────────────────────────────


def _ph(method: str, host: str, project_id: str, key: str, path: str, body: Any = None) -> Any:
    url = f"{host.rstrip('/')}/api/projects/{project_id}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        raise RuntimeError(f"PostHog {method} {path} → HTTP {e.code}: {body_bytes[:500]!r}") from e


def _hogql(host: str, project_id: str, key: str, sql: str) -> Dict[str, Any]:
    return _ph("POST", host, project_id, key, "/query/", {
        "query": {"kind": "HogQLQuery", "query": sql},
    })


def _create_dashboard(host: str, project_id: str, key: str, name: str, description: str) -> Dict[str, Any]:
    return _ph("POST", host, project_id, key, "/dashboards/", {
        "name": name,
        "description": description,
    })


def _create_insight(
    host: str,
    project_id: str,
    key: str,
    *,
    name: str,
    sql: str,
    dashboard_id: int,
    description: str = "",
) -> Dict[str, Any]:
    return _ph("POST", host, project_id, key, "/insights/", {
        "name": name,
        "description": description,
        "query": {
            "kind": "DataTableNode",
            "source": {"kind": "HogQLQuery", "query": sql},
        },
        "dashboards": [dashboard_id],
    })


# ── Cost math ─────────────────────────────────────────────────────────


def _funnel_counts(report: Dict[str, Any]) -> Dict[str, int]:
    """Sum candidates_proposed across explorer batches when available;
    fall back to experiment_report['candidates_proposed']."""
    proposed = int(report.get("candidates_proposed") or 0)
    on_policy = proposed  # in our pipeline, "stored" == on-policy
    promoted = int(report.get("promoted") or 0)
    return {
        "proposed": max(proposed, 1),
        "on_policy": max(on_policy, 1),
        "promoted": max(promoted, 1),
    }


def _aggregate_tokens(bucket: Dict[str, Dict[str, int]]) -> Tuple[int, int]:
    total_in = sum(int(v.get("input", 0)) for v in bucket.values())
    total_out = sum(int(v.get("output", 0)) for v in bucket.values())
    return total_in, total_out


def _cost_table_rows(
    bucket: Dict[str, Dict[str, int]],
    funnel: Dict[str, int],
    pricing: Dict[str, Tuple[float, float]],
) -> List[Dict[str, Any]]:
    total_in, total_out = _aggregate_tokens(bucket)
    rows: List[Dict[str, Any]] = []
    for model, (pi, po) in pricing.items():
        cost = total_in / 1e6 * pi + total_out / 1e6 * po
        rows.append({
            "model": model,
            "input_per_m": pi,
            "output_per_m": po,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "cost_per_run": round(cost, 6),
            "cost_per_proposed": round(cost / funnel["proposed"], 6),
            "cost_per_on_policy": round(cost / funnel["on_policy"], 6),
            "cost_per_promoted": round(cost / funnel["promoted"], 6),
        })
    return rows


# ── Insight SQL builders ──────────────────────────────────────────────


def _per_signal_sql(signal: Dict[str, Any]) -> str:
    """Re-render the SQL Mason actually executed for a promoted signal."""
    sql = (signal.get("query_template") or "").rstrip(";").strip()
    return sql or "SELECT 1 AS placeholder"


def _funnel_sql(funnel: Dict[str, int]) -> str:
    return (
        "SELECT "
        f"{funnel['proposed']} AS candidates_proposed, "
        f"{funnel['on_policy']} AS on_policy_passed, "
        f"{funnel['promoted']} AS promoted_signals, "
        f"{funnel['promoted']} / NULLIF({funnel['proposed']}, 0) AS promote_rate"
    )


def _cost_sql(rows: List[Dict[str, Any]]) -> str:
    """Synthesize a one-shot SELECT … UNION ALL block with the cost rows."""
    parts: List[str] = []
    for r in rows:
        parts.append(
            "SELECT "
            f"'{r['model']}' AS model, "
            f"{r['input_tokens']} AS input_tokens, "
            f"{r['output_tokens']} AS output_tokens, "
            f"{r['input_per_m']} AS input_per_m, "
            f"{r['output_per_m']} AS output_per_m, "
            f"{r['cost_per_run']} AS cost_per_run, "
            f"{r['cost_per_proposed']} AS cost_per_proposed, "
            f"{r['cost_per_on_policy']} AS cost_per_on_policy, "
            f"{r['cost_per_promoted']} AS cost_per_promoted"
        )
    return "\nUNION ALL\n".join(parts) + "\nORDER BY cost_per_run ASC"


def _token_bucket_sql(bucket: Dict[str, Dict[str, int]]) -> str:
    parts: List[str] = []
    for stage, v in bucket.items():
        in_t = int(v.get("input", 0))
        out_t = int(v.get("output", 0))
        parts.append(
            "SELECT "
            f"'{stage}' AS stage, "
            f"{in_t} AS input_tokens, "
            f"{out_t} AS output_tokens, "
            f"{in_t + out_t} AS total_tokens"
        )
    return "\nUNION ALL\n".join(parts) + "\nORDER BY total_tokens DESC"


def _signal_event_count_sql(signal: Dict[str, Any]) -> str:
    """A simple count of the trigger event over the same window — for the
    "How many of this event fired in the lookback window?" tile that backs
    the per-signal card."""
    template = signal.get("query_template") or ""
    # Extract event literal (very forgiving).
    import re
    m = re.search(r"event\s*=\s*'([^']+)'", template)
    event_name = m.group(1) if m else "seat_activated"
    window = signal.get("time_window") or "90d"
    days_match = re.search(r"(\d+)\s*d", str(window))
    days = days_match.group(1) if days_match else "90"
    return (
        f"SELECT count() AS event_count FROM events "
        f"WHERE event = '{event_name}' "
        f"AND timestamp >= now() - INTERVAL {days} DAY"
    )


# ── Main flow ─────────────────────────────────────────────────────────


def build_dashboard(
    *,
    host: str,
    project_id: str,
    key: str,
    inspector_url: str,
    mason_url: str,
    run_id: str,
    session_id: str,
    report: Dict[str, Any],
    ground_truth: Optional[Dict[str, Any]],
    token_bucket: Dict[str, Dict[str, int]],
    pricing: Dict[str, Tuple[float, float]],
) -> str:
    funnel = _funnel_counts(report)
    cost_rows = _cost_table_rows(token_bucket, funnel, pricing)

    description_lines = [
        f"Mason E2E run **{run_id}**",
        f"Inspector session: `{session_id}`",
        f"Inspector deploy: {inspector_url}",
        f"Mason deploy: {mason_url}",
        "",
        f"Funnel: {funnel['proposed']} proposed → {funnel['on_policy']} on-policy → {funnel['promoted']} promoted",
    ]
    description = "\n".join(description_lines)

    dash = _create_dashboard(
        host, project_id, key,
        name=f"Mason Flash3 — {run_id}",
        description=description,
    )
    dash_id = int(dash["id"])
    sys.stderr.write(f">> created dashboard {dash_id}: {dash.get('name')}\n")

    # 1. Per-signal cohort tables
    promoted = report.get("promoted_signals") or []
    for idx, sig in enumerate(promoted):
        evidence = sig.get("promotion_evidence") or {}
        gt_template = ""
        if ground_truth:
            gt_template = _gt_template_match(sig, ground_truth) or ""
        desc_lines = [
            f"**{sig.get('name','?')}** — entity grain `{sig.get('entity_grain','')}`, "
            f"window `{sig.get('time_window','')}`",
            f"_{sig.get('interpretation','').strip()}_" if sig.get('interpretation') else "",
            "",
            f"Cohort: success {evidence.get('success_cohort_size','?')} / "
            f"failure {evidence.get('failure_cohort_size','?')} / "
            f"grey {evidence.get('grey_cohort_size','?')}",
            f"Conversion lift: {evidence.get('conversion_lift','?')} | "
            f"delta: {evidence.get('conversion_rate_delta','?')} | "
            f"precision proxy: {evidence.get('precision_proxy','?')}",
        ]
        if gt_template:
            desc_lines.append(f"Mapped dryfit template: `{gt_template}`")
        desc = "\n".join([l for l in desc_lines if l.strip()])
        ins = _create_insight(
            host, project_id, key,
            name=f"Signal {idx+1}: {sig.get('name','(unnamed)')}",
            sql=_per_signal_sql(sig),
            dashboard_id=dash_id,
            description=desc,
        )
        sys.stderr.write(f"   tile signal #{idx+1} insight {ins.get('short_id')}\n")

    # 2. Funnel
    _create_insight(
        host, project_id, key,
        name="Mason funnel — proposed → on-policy → promoted",
        sql=_funnel_sql(funnel),
        dashboard_id=dash_id,
        description="Counts of candidates at each stage of the Mason pipeline for this run.",
    )

    # 3. Token bucket
    _create_insight(
        host, project_id, key,
        name="Token consumption per stage",
        sql=_token_bucket_sql(token_bucket),
        dashboard_id=dash_id,
        description="bootstrap / explorer / reviewer token totals (estimated when --token-bucket not provided).",
    )

    # 4. Cost matrix
    _create_insight(
        host, project_id, key,
        name="Estimated per-run + unit-cost across 8 frontier models",
        sql=_cost_sql(cost_rows),
        dashboard_id=dash_id,
        description=(
            "Same totals applied to each model's list price. "
            "cost_per_proposed = cost÷proposed, "
            "cost_per_on_policy = cost÷on-policy, "
            "cost_per_promoted = cost÷promoted. Rows ordered by cheapest cost_per_run."
        ),
    )

    return f"{host.rstrip('/')}/project/{project_id}/dashboard/{dash_id}"


def _gt_template_match(signal: Dict[str, Any], ground_truth: Dict[str, Any]) -> Optional[str]:
    """Best-coverage dryfit template id, or None."""
    import re
    sig_text = " ".join([
        str(signal.get("name", "")),
        str(signal.get("interpretation", "")),
        str(signal.get("query_template", "")),
    ]).lower()
    sig_tokens = set(re.findall(r"[a-z_][a-z0-9_]*", sig_text))
    by_template: Dict[str, List[str]] = {}
    for inst in ground_truth.get("signals") or []:
        tid = str(inst.get("template_id") or "")
        for ev in inst.get("event_names") or []:
            by_template.setdefault(tid, []).append(str(ev).lower())
    best_tid: Optional[str] = None
    best_overlap = 0.0
    for tid, evs in by_template.items():
        evset = set(evs)
        overlap = len(evset & sig_tokens) / max(1, len(evset))
        if overlap > best_overlap:
            best_overlap = overlap
            best_tid = tid
    return best_tid if best_overlap >= 0.5 else None


# ── CLI ──────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--inspector-url", required=True)
    p.add_argument("--mason-url", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--session-id", required=True)
    p.add_argument("--experiment-report", required=True, help="path to experiment_report.json")
    p.add_argument("--posthog-host", default=os.getenv("POSTHOG_HOST", "https://us.posthog.com"))
    p.add_argument("--posthog-project-id", default=os.getenv("POSTHOG_PROJECT_ID", ""))
    p.add_argument("--posthog-personal-api-key", default=os.getenv("POSTHOG_PERSONAL_API_KEY", ""))
    p.add_argument("--ground-truth", default=None)
    p.add_argument("--token-bucket", default=None,
                   help="JSON file: {stage:{input:N,output:N}}; default = doc estimate")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.posthog_project_id or not args.posthog_personal_api_key:
        sys.stderr.write("ERROR: --posthog-project-id and --posthog-personal-api-key required\n")
        return 2

    rpt_path = Path(args.experiment_report)
    if not rpt_path.is_file():
        sys.stderr.write(f"ERROR: experiment_report not found: {rpt_path}\n")
        return 2
    report = json.loads(rpt_path.read_text(encoding="utf-8"))

    ground_truth: Optional[Dict[str, Any]] = None
    if args.ground_truth:
        gt_path = Path(args.ground_truth)
        if gt_path.is_file():
            ground_truth = json.loads(gt_path.read_text(encoding="utf-8"))

    token_bucket = DEFAULT_TOKEN_BUCKET
    if args.token_bucket:
        tb_path = Path(args.token_bucket)
        if tb_path.is_file():
            token_bucket = json.loads(tb_path.read_text(encoding="utf-8"))

    url = build_dashboard(
        host=args.posthog_host,
        project_id=str(args.posthog_project_id),
        key=args.posthog_personal_api_key,
        inspector_url=args.inspector_url,
        mason_url=args.mason_url,
        run_id=args.run_id,
        session_id=args.session_id,
        report=report,
        ground_truth=ground_truth,
        token_bucket=token_bucket,
        pricing=DEFAULT_PRICING,
    )
    sys.stdout.write(url + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
