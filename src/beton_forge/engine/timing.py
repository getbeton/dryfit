from __future__ import annotations

from datetime import UTC, datetime, timedelta


def bounded_datetime(rng, duration_days: int) -> datetime:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    minute_offset = rng.randint(0, max(1, duration_days * 24 * 60) - 1)
    second_offset = rng.randint(0, 59)
    return base + timedelta(minutes=minute_offset, seconds=second_offset)


def random_jitter_seconds(rng) -> int:
    return rng.randint(-120, 120)
