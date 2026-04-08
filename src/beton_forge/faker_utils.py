from __future__ import annotations

from faker import Faker


def build_faker(locales: list[str], seed: int) -> Faker:
    fake = Faker(locales)
    fake.seed_instance(seed)
    return fake
