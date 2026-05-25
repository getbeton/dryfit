"""Read dryfit-generated events from local Postgres and POST them to PostHog.

dryfit writes synthetic events to a local Postgres `events` table and emits
ground_truth.json + manifest.json to an output dir. This script bridges the
gap to PostHog: it scans the events table chronologically and posts to
`{POSTHOG_HOST}/batch/` in chunks. PostHog's ingest pipeline indexes events
by `distinct_id` + `timestamp`, so we map:

    dryfit.actor_id   -> PostHog distinct_id
    dryfit.account_id -> PostHog $group_0 (group_type=account) and property
    dryfit.session_id -> PostHog $session_id
    dryfit.entity_id  -> PostHog property entity_id
    dryfit.event_props.* -> PostHog properties (merged)

Notes:
- Anonymous actors (actor_id=null) get distinct_id="anonymous_<event_id>" so
  PostHog still ingests them but doesn't merge unrelated anon events.
- Timestamps are sent as RFC3339 strings; PostHog respects historical timestamps
  for events sent within `historical_migration` semantics.
- We do NOT use the historical_migration flag — we rely on PostHog's normal
  ingest path, which preserves event timestamps when supplied.

Usage:
    python posthog_ingest.py \\
        --dsn postgresql:///dryfit \\
        --posthog-host https://us.posthog.com \\
        --project-api-key phc_... \\
        --batch-size 100 \\
        [--limit 1000] [--dry-run]

Env vars (alternative to flags):
    DRYFIT_PG_DSN, POSTHOG_HOST, POSTHOG_PROJECT_API_KEY
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import psycopg
except ImportError:
    sys.stderr.write("ERROR: psycopg is required. `pip install psycopg[binary]` or use uv.\n")
    sys.exit(2)

import urllib.request
import urllib.error


def _build_event_payload(row: Dict[str, Any], project_api_key: str) -> Dict[str, Any]:
    actor_id = row.get("actor_id")
    distinct_id = actor_id or f"anonymous_{row.get('event_id')}"
    ts: datetime = row["ts"]
    timestamp = ts.isoformat().replace("+00:00", "Z") if ts else None

    properties: Dict[str, Any] = {}
    raw_props = row.get("event_props") or {}
    if isinstance(raw_props, dict):
        properties.update(raw_props)

    if row.get("session_id"):
        properties["$session_id"] = row["session_id"]
    if row.get("account_id"):
        properties["account_id"] = row["account_id"]
        properties["$group_0"] = row["account_id"]
        properties["$groups"] = {"account": row["account_id"]}
    if row.get("entity_id"):
        properties["entity_id"] = row["entity_id"]
    if row.get("entity_type"):
        properties["entity_type"] = row["entity_type"]
    if row.get("scenario"):
        properties["scenario"] = row["scenario"]
    if row.get("source_system"):
        properties["source_system"] = row["source_system"]
    properties["dryfit_event_id"] = row["event_id"]

    return {
        "event": row["event_name"],
        "distinct_id": distinct_id,
        "properties": properties,
        "timestamp": timestamp,
    }


def _post_batch(
    host: str,
    project_api_key: str,
    events: List[Dict[str, Any]],
    timeout: int = 30,
) -> None:
    url = f"{host.rstrip('/')}/batch/"
    body = json.dumps({
        "api_key": project_api_key,
        "historical_migration": True,
        "batch": events,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"PostHog /batch failed with HTTP {resp.status}: {resp.read()[:500]!r}")


def ingest(
    dsn: str,
    posthog_host: str,
    project_api_key: str,
    batch_size: int = 100,
    limit: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    sql = "SELECT event_id, ts, scenario, source_system, entity_id, entity_type, actor_id, account_id, session_id, event_name, event_props FROM events ORDER BY ts ASC"
    if limit:
        sql += f" LIMIT {int(limit)}"

    sent = 0
    skipped = 0
    batches = 0
    started = time.time()
    with psycopg.connect(dsn) as conn:
        with conn.cursor(name="dryfit_ingest", row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql)
            buffer: List[Dict[str, Any]] = []
            for row in cur:
                try:
                    payload = _build_event_payload(row, project_api_key)
                except Exception as exc:
                    skipped += 1
                    sys.stderr.write(f"skip event {row.get('event_id')}: {exc}\n")
                    continue
                buffer.append(payload)
                if len(buffer) >= batch_size:
                    if not dry_run:
                        _post_batch(posthog_host, project_api_key, buffer)
                    sent += len(buffer)
                    batches += 1
                    buffer = []
                    if batches % 10 == 0:
                        sys.stderr.write(f"  ingested {sent} events in {batches} batches…\n")
            if buffer:
                if not dry_run:
                    _post_batch(posthog_host, project_api_key, buffer)
                sent += len(buffer)
                batches += 1

    elapsed = time.time() - started
    return {
        "sent": sent,
        "skipped": skipped,
        "batches": batches,
        "elapsed_sec": round(elapsed, 2),
        "dry_run": dry_run,
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dsn", default=os.getenv("DRYFIT_PG_DSN", "postgresql:///dryfit"))
    p.add_argument("--posthog-host", default=os.getenv("POSTHOG_HOST", "https://us.posthog.com"))
    p.add_argument("--project-api-key", default=os.getenv("POSTHOG_PROJECT_API_KEY", ""))
    p.add_argument("--batch-size", type=int, default=100)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.project_api_key:
        sys.stderr.write("ERROR: --project-api-key (or POSTHOG_PROJECT_API_KEY env) required.\n")
        return 2
    summary = ingest(
        dsn=args.dsn,
        posthog_host=args.posthog_host,
        project_api_key=args.project_api_key,
        batch_size=args.batch_size,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
