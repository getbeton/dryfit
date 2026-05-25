"""Score Mason's promoted signals against the dryfit ground-truth manifest.

Mason produces an `experiment_report.json` artifact with `promoted_signals`
(name + query_template + parameter_set + promotion_evidence). dryfit produces
`ground_truth.json` listing each planted signal as a path of event names tied
to a specific entity.

We can't expect Mason's discovered signals to be 1:1 with dryfit templates —
Mason emits HogQL aggregates over event paths, not the path templates
themselves. So we score on coverage: how many dryfit signal templates does
Mason's promoted set "cover" by referencing all of the template's events in
its query_template + name + interpretation? This is a coarse but honest
proxy for recall.

Outputs:
  scoring_<run_id>.json — per-template coverage + per-promoted-signal match
  scoring_<run_id>.md   — human-readable summary

Usage:
    python score.py \\
      --experiment-report path/to/experiment_report.json \\
      --ground-truth path/to/ground_truth.json \\
      --output-dir ./scoring
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", " ", str(text or "").lower()).strip()


def _candidate_event_mentions(signal: Dict[str, Any]) -> Set[str]:
    """Collect plausible event-name mentions in a Mason signal."""
    haystack = " ".join(
        [
            str(signal.get("name") or ""),
            str(signal.get("interpretation") or ""),
            str(signal.get("query_template") or ""),
            str(signal.get("entity_grain") or ""),
        ]
    )
    norm = _normalize(haystack)
    tokens = norm.split()
    # also collect "event = '<name>'" style literals
    quoted = re.findall(r"['\"]([a-zA-Z_][a-zA-Z0-9_]+)['\"]", str(signal.get("query_template") or ""))
    return set(tokens) | {q.lower() for q in quoted}


def _template_event_set(template_signals: List[Dict[str, Any]]) -> Set[str]:
    events: Set[str] = set()
    for sig in template_signals:
        for name in sig.get("event_names") or []:
            if isinstance(name, str) and name.strip():
                events.add(name.strip().lower())
    return events


def score(
    experiment_report: Dict[str, Any],
    ground_truth: Dict[str, Any],
) -> Dict[str, Any]:
    promoted = experiment_report.get("promoted_signals") or []
    success_event = str(ground_truth.get("success_event") or "").lower()

    # group ground-truth signal instances by template
    by_template: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for inst in ground_truth.get("signals") or []:
        tid = str(inst.get("template_id") or "")
        if tid:
            by_template[tid].append(inst)

    template_meta: Dict[str, Dict[str, Any]] = {}
    for tid, instances in by_template.items():
        events = _template_event_set(instances)
        kind = str(instances[0].get("kind") if instances else "")
        template_meta[tid] = {
            "kind": kind,
            "instance_count": len(instances),
            "event_set": sorted(events),
        }

    # for each promoted signal, find the best-matching template by coverage
    promoted_matches: List[Dict[str, Any]] = []
    template_hits: Dict[str, int] = defaultdict(int)
    template_best_overlap: Dict[str, float] = defaultdict(float)

    for signal in promoted:
        mentions = _candidate_event_mentions(signal)
        best_tid = None
        best_overlap = 0.0
        best_overlap_count = 0
        best_required_count = 0
        for tid, meta in template_meta.items():
            event_set = set(meta["event_set"])
            if not event_set:
                continue
            overlap = event_set & mentions
            overlap_count = len(overlap)
            if overlap_count == 0:
                continue
            ratio = overlap_count / max(1, len(event_set))
            if ratio > best_overlap or (ratio == best_overlap and overlap_count > best_overlap_count):
                best_overlap = ratio
                best_overlap_count = overlap_count
                best_required_count = len(event_set)
                best_tid = tid
        promoted_matches.append({
            "name": signal.get("name") or "",
            "best_template_id": best_tid,
            "coverage_ratio": round(best_overlap, 3),
            "events_overlapped": best_overlap_count,
            "events_required": best_required_count,
            "mentions_success_event": success_event in mentions,
        })
        if best_tid and best_overlap >= 0.5:
            template_hits[best_tid] += 1
            template_best_overlap[best_tid] = max(template_best_overlap[best_tid], best_overlap)

    # recall: fraction of templates with ≥1 signal at coverage_ratio≥0.5
    total_templates = len(by_template)
    templates_covered = sum(1 for tid in by_template if template_hits.get(tid, 0) >= 1)
    recall = templates_covered / total_templates if total_templates else 0.0

    # precision: fraction of promoted signals that hit any template at coverage≥0.5
    promoted_count = len(promoted)
    hits = sum(1 for m in promoted_matches if m["coverage_ratio"] >= 0.5)
    precision = hits / promoted_count if promoted_count else 0.0

    return {
        "run_id": experiment_report.get("run_id", ""),
        "dataset_id": ground_truth.get("dataset_id", ""),
        "success_event": ground_truth.get("success_event", ""),
        "scenario": ground_truth.get("scenario", ""),
        "metrics": {
            "promoted_signals_count": promoted_count,
            "ground_truth_templates": total_templates,
            "templates_covered": templates_covered,
            "promoted_hits": hits,
            "recall": round(recall, 3),
            "precision": round(precision, 3),
        },
        "promoted_signals": promoted_matches,
        "templates": [
            {
                "template_id": tid,
                "kind": meta["kind"],
                "instance_count": meta["instance_count"],
                "event_set": meta["event_set"],
                "promoted_hit_count": template_hits.get(tid, 0),
                "best_coverage": round(template_best_overlap.get(tid, 0.0), 3),
            }
            for tid, meta in template_meta.items()
        ],
    }


def _summary_md(payload: Dict[str, Any]) -> str:
    m = payload["metrics"]
    lines = [
        f"# Mason vs dryfit scoring — {payload.get('dataset_id', '?')}",
        "",
        f"- run_id: `{payload.get('run_id', '?')}`",
        f"- scenario: `{payload.get('scenario', '?')}`",
        f"- success_event: `{payload.get('success_event', '?')}`",
        "",
        "## Metrics",
        "",
        f"- promoted signals: **{m['promoted_signals_count']}**",
        f"- ground-truth templates: **{m['ground_truth_templates']}**",
        f"- templates covered (≥0.5 event overlap): **{m['templates_covered']}**",
        f"- promoted-signal hits (coverage ≥0.5): **{m['promoted_hits']}**",
        f"- **recall**: {m['recall']}",
        f"- **precision**: {m['precision']}",
        "",
        "## Promoted signals",
        "",
    ]
    for s in payload["promoted_signals"]:
        flag = "✓" if s["coverage_ratio"] >= 0.5 else "✗"
        lines.append(
            f"- {flag} `{s['name']}` → template `{s['best_template_id']}` "
            f"(coverage {s['coverage_ratio']}, {s['events_overlapped']}/{s['events_required']})"
        )
    lines += ["", "## Templates", ""]
    for t in payload["templates"]:
        flag = "✓" if t["promoted_hit_count"] >= 1 else "✗"
        events = ", ".join(t["event_set"][:6]) + ("…" if len(t["event_set"]) > 6 else "")
        lines.append(
            f"- {flag} `{t['template_id']}` ({t['kind']}, {t['instance_count']}× planted) "
            f"events=[{events}] best_cov={t['best_coverage']}"
        )
    lines.append("")
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--experiment-report", required=True, help="path to Mason experiment_report.json")
    p.add_argument("--ground-truth", required=True, help="path to dryfit ground_truth.json")
    p.add_argument("--output-dir", default=".", help="dir to write scoring_<run_id>.{json,md}")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    report_path = Path(args.experiment_report)
    truth_path = Path(args.ground_truth)
    if not report_path.is_file():
        sys.stderr.write(f"ERROR: experiment_report not found: {report_path}\n")
        return 2
    if not truth_path.is_file():
        sys.stderr.write(f"ERROR: ground_truth not found: {truth_path}\n")
        return 2

    experiment_report = json.loads(report_path.read_text(encoding="utf-8"))
    ground_truth = json.loads(truth_path.read_text(encoding="utf-8"))
    payload = score(experiment_report, ground_truth)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = payload.get("run_id", "unknown")
    json_path = out_dir / f"scoring_{run_id}.json"
    md_path = out_dir / f"scoring_{run_id}.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(_summary_md(payload), encoding="utf-8")
    sys.stdout.write(json.dumps(payload["metrics"], indent=2) + "\n")
    sys.stderr.write(f">> wrote {json_path}\n>> wrote {md_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
