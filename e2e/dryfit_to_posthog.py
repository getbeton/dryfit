"""Generate dryfit synthetic events in-memory and POST them straight to PostHog.

Runs dryfit's engine programmatically (no Postgres dependency), captures the
event list, writes ground_truth.json + manifest.json to disk, and ingests
events into PostHog Project B via /batch.

Field mapping:
    dryfit.actor_id   -> PostHog distinct_id   (anon → "anon_<event_id>")
    dryfit.account_id -> PostHog $group_0      + property account_id
    dryfit.session_id -> PostHog $session_id
    dryfit.entity_id  -> PostHog property entity_id
    dryfit.event_props.* -> PostHog properties (merged)
    + property dryfit_event_id, scenario, source_system, entity_type

Notes:
- Uses `historical_migration: true` so PostHog respects the synthetic timestamps
  (events span 364 days back from now per the seat-based scenario).
- Adapts `backend.kind: postgres` to a no-op by patching the engine's writer
  before generation — we never touch a real DB.

Usage:
    uv run --with-requirements <(echo "requests") python dryfit_to_posthog.py \\
        --config /path/to/dryfit/configs/posthog_seat_based_mvp.yaml \\
        --output-dir ./artifacts/dryfit_e2e/posthog_seat_based_mvp \\
        --posthog-host https://us.posthog.com \\
        --project-api-key phc_... \\
        [--limit 10000] [--dry-run] [--batch-size 100]

Or simpler from the dryfit checkout (uv-managed deps):
    cd $DRYFIT_DIR && uv sync
    uv run --directory $DRYFIT_DIR python /path/to/this/dryfit_to_posthog.py ...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid as uuidlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _deterministic_uuid(seed: str) -> str:
    """SHA-256(seed) → UUIDv4-shaped hex; PostHog dedupes on `uuid` per project."""
    h = hashlib.sha256(seed.encode("utf-8")).digest()[:16]
    return str(uuidlib.UUID(bytes=h, version=4))


def _build_event_payload(event: Any) -> Dict[str, Any]:
    actor_id = getattr(event, "actor_id", None)
    distinct_id = actor_id or f"anon_{getattr(event, 'event_id', '')}"
    ts: datetime = getattr(event, "ts", None)
    timestamp = ts.isoformat().replace("+00:00", "Z") if ts else None

    properties: Dict[str, Any] = {}
    raw_props = getattr(event, "event_props", {}) or {}
    if isinstance(raw_props, dict):
        properties.update(raw_props)

    if getattr(event, "session_id", None):
        properties["$session_id"] = event.session_id
    if getattr(event, "account_id", None):
        properties["account_id"] = event.account_id
        properties["$group_0"] = event.account_id
        properties["$groups"] = {"account": event.account_id}
    if getattr(event, "entity_id", None):
        properties["entity_id"] = event.entity_id
    if getattr(event, "entity_type", None):
        properties["entity_type"] = event.entity_type
    if getattr(event, "scenario", None):
        properties["scenario"] = event.scenario
    if getattr(event, "source_system", None):
        properties["source_system"] = event.source_system
    properties["dryfit_event_id"] = getattr(event, "event_id", "")

    event_id = getattr(event, "event_id", "")
    return {
        "event": getattr(event, "event_name", ""),
        "distinct_id": distinct_id,
        "properties": properties,
        "timestamp": timestamp,
        "uuid": _deterministic_uuid(f"dryfit:{event_id}"),
    }


def _post_batch(
    host: str,
    project_api_key: str,
    events: List[Dict[str, Any]],
    timeout: int = 60,
    historical: bool = True,
    max_retries: int = 5,
) -> None:
    url = f"{host.rstrip('/')}/batch/"
    body_obj: Dict[str, Any] = {
        "api_key": project_api_key,
        "batch": events,
    }
    if historical:
        body_obj["historical_migration"] = True
    body = json.dumps(body_obj).encode("utf-8")
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status >= 300:
                    raise RuntimeError(f"PostHog /batch failed HTTP {resp.status}: {resp.read()[:500]!r}")
                return
        except urllib.error.HTTPError as e:
            body_excerpt = e.read()[:500].decode("utf-8", errors="replace")
            if 400 <= e.code < 500 and e.code != 429:
                raise RuntimeError(f"PostHog /batch failed HTTP {e.code}: {body_excerpt}") from e
            last_exc = e
        except Exception as e:
            last_exc = e
        sleep_s = (2 ** attempt) + (0.1 * attempt)
        sys.stderr.write(f"  warn: batch retry {attempt + 1}/{max_retries} after {type(last_exc).__name__}: {last_exc} (sleep {sleep_s:.1f}s)\n")
        time.sleep(sleep_s)
    raise RuntimeError(f"PostHog /batch failed after {max_retries} retries: {last_exc}")


def _disable_postgres_writer() -> None:
    """Patch dryfit.postgres.write_events to a no-op so we never touch a DB."""
    import dryfit.postgres
    dryfit.postgres.write_events = lambda *a, **k: None  # type: ignore[assignment]


def _generate_in_memory(config_path: Path, output_dir: Path) -> Any:
    _disable_postgres_writer()
    from dryfit.engine.generator import generate_dataset  # type: ignore[import-not-found]

    output_dir.mkdir(parents=True, exist_ok=True)
    return generate_dataset(
        config_path,
        output_dir=str(output_dir),
        dry_run=False,
        skip_db_write=True,
    )


def _ingest(
    events: List[Any],
    posthog_host: str,
    project_api_key: str,
    batch_size: int,
    limit: Optional[int],
    dry_run: bool,
    historical: bool,
) -> Dict[str, Any]:
    sent = 0
    skipped = 0
    batches = 0
    started = time.time()
    buffer: List[Dict[str, Any]] = []

    iterator = events if limit is None else events[: int(limit)]
    for event in iterator:
        try:
            payload = _build_event_payload(event)
        except Exception as exc:
            skipped += 1
            sys.stderr.write(f"skip event {getattr(event, 'event_id', '?')}: {exc}\n")
            continue
        buffer.append(payload)
        if len(buffer) >= batch_size:
            if not dry_run:
                _post_batch(posthog_host, project_api_key, buffer, historical=historical)
            sent += len(buffer)
            batches += 1
            buffer = []
            if batches % 25 == 0:
                sys.stderr.write(f"  ingested {sent} events in {batches} batches…\n")
    if buffer:
        if not dry_run:
            _post_batch(posthog_host, project_api_key, buffer, historical=historical)
        sent += len(buffer)
        batches += 1

    return {
        "sent": sent,
        "skipped": skipped,
        "batches": batches,
        "elapsed_sec": round(time.time() - started, 2),
        "dry_run": dry_run,
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", required=True, help="path to a dryfit YAML config")
    p.add_argument("--output-dir", required=True, help="dir to write ground_truth.json + manifest.json")
    p.add_argument("--posthog-host", default=os.getenv("POSTHOG_HOST", "https://us.posthog.com"))
    p.add_argument("--project-api-key", default=os.getenv("POSTHOG_PROJECT_API_KEY", ""))
    p.add_argument("--batch-size", type=int, default=100)
    p.add_argument("--limit", type=int, default=None, help="cap events sent (debug)")
    p.add_argument("--dry-run", action="store_true", help="generate but don't POST to PostHog")
    p.add_argument("--no-historical", action="store_true", help="omit historical_migration flag")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.dry_run and not args.project_api_key:
        sys.stderr.write("ERROR: --project-api-key (or POSTHOG_PROJECT_API_KEY env) required.\n")
        return 2

    config_path = Path(args.config).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not config_path.is_file():
        sys.stderr.write(f"ERROR: config not found: {config_path}\n")
        return 2

    sys.stderr.write(f">> generating from {config_path.name} (in-memory)…\n")
    started = time.time()
    result = _generate_in_memory(config_path, output_dir)
    events = list(getattr(result, "events", []))
    truth = getattr(result, "truth", None)
    manifest = getattr(result, "manifest", None)
    sys.stderr.write(
        f"   generated {len(events)} events, "
        f"{getattr(manifest, 'signal_instance_count', '?')} signals, "
        f"{round(time.time() - started, 2)}s\n"
    )

    sys.stderr.write(
        f">> posting to PostHog {args.posthog_host} (batch_size={args.batch_size}, dry_run={args.dry_run})\n"
    )
    summary = _ingest(
        events=events,
        posthog_host=args.posthog_host,
        project_api_key=args.project_api_key,
        batch_size=args.batch_size,
        limit=args.limit,
        dry_run=args.dry_run,
        historical=not args.no_historical,
    )
    summary["dataset_id"] = getattr(manifest, "dataset_id", "")
    summary["scenario"] = getattr(manifest, "scenario", "")
    summary["row_count"] = getattr(manifest, "row_count", len(events))
    summary["signal_instance_count"] = getattr(manifest, "signal_instance_count", 0)
    summary["ground_truth_path"] = str(output_dir / "ground_truth.json")
    summary["manifest_path"] = str(output_dir / "manifest.json")
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
