from __future__ import annotations

from collections.abc import Sequence

from dryfit.models import EventRecord

SCHEMA_SQL = """
DROP TABLE IF EXISTS events;
CREATE TABLE events(
  event_id text PRIMARY KEY,
  ts timestamptz NOT NULL,
  scenario text NOT NULL,
  source_system text NOT NULL,
  entity_id text,
  entity_type text,
  actor_id text,
  account_id text,
  session_id text,
  event_name text NOT NULL,
  event_props jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_events_ts ON events (ts);
CREATE INDEX idx_events_event_name_ts ON events (event_name, ts);
CREATE INDEX idx_events_entity_ts ON events (entity_type, entity_id, ts);
CREATE INDEX idx_events_account_ts ON events (account_id, ts);
CREATE INDEX idx_events_actor_ts ON events (actor_id, ts);
CREATE INDEX idx_events_session_ts ON events (session_id, ts);
"""


def write_events(dsn: str, events: Sequence[EventRecord]) -> None:
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise RuntimeError("psycopg is required for PostgreSQL output") from exc

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(SCHEMA_SQL)
            rows = [
                (
                    event.event_id,
                    event.ts,
                    event.scenario,
                    event.source_system,
                    event.entity_id,
                    event.entity_type,
                    event.actor_id,
                    event.account_id,
                    event.session_id,
                    event.event_name,
                    Jsonb(event.event_props),
                )
                for event in events
            ]
            if rows:
                cursor.executemany(
                    """
                    INSERT INTO events (
                      event_id, ts, scenario, source_system, entity_id, entity_type,
                      actor_id, account_id, session_id, event_name, event_props
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    rows,
                )
