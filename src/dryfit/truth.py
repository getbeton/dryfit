from __future__ import annotations

import json
from pathlib import Path

from dryfit.models import GroundTruthDocument, ManifestDocument


def write_ground_truth(document: GroundTruthDocument, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document.to_dict(), indent=2), encoding="utf-8")


def write_manifest(document: ManifestDocument, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document.to_dict(), indent=2), encoding="utf-8")
