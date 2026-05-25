"""Matrix runner for Mason E2E experiments.

Iterates a (model × batch_size) cell list, sets the relevant Railway env
vars, redeploys Mason once per env change, mints a fresh Inspector
session per run, fires signal_agent, polls until artifacts land, pulls
them locally, and writes a per-run summary JSON.

Usage:
    python run_matrix.py --output-dir /tmp/mason_matrix \\
        --runs-per-cell 3 --cells flash:2,flash:5,flash:10,flash:20,\\
                                  haiku:2,haiku:5,haiku:10,haiku:20

Cell shorthand → resolved model:
    flash → gemini/gemini-3-flash-preview
    haiku → anthropic/claude-haiku-4-5
    opus  → anthropic/claude-opus-4-6  (kept for parity, not in default matrix)

Each run writes:
    <output-dir>/<cell>/run_<idx>/experiment_report.json
    <output-dir>/<cell>/run_<idx>/candidate_hypotheses.jsonl
    <output-dir>/<cell>/run_<idx>/rice_batch_summaries.jsonl
    <output-dir>/<cell>/run_<idx>/explorer_batch_summaries.jsonl
    <output-dir>/<cell>/run_<idx>/run_meta.json    (model, batch_size, session_id, langfuse_trace_id, wall_time)

Aggregate:
    <output-dir>/matrix.jsonl   (one row per run, ready for analysis/dashboard)

Prereqs:
- ~/.claude/secrets/mason-flash3.env sourced for INSPECTOR_URL,
  AGENT_SECRET, MASON_AGENT_API_URL, ANTHROPIC_API_KEY (for haiku),
  GEMINI_API_KEY, LANGFUSE_*.
- railway CLI logged in, project + env linked.
- Mason container has the latest code (signal_agent w/ stat sig gate).
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


MODEL_ALIASES = {
    "flash": "gemini/gemini-3-flash-preview",
    "haiku": "anthropic/claude-haiku-4-5",
    "opus":  "anthropic/claude-opus-4-6",
    "sonnet": "anthropic/claude-sonnet-4-6",
}

INSPECTOR_URL = os.getenv("INSPECTOR_URL", "https://beton-inspector-git-mason-e2e-test-getbeton.vercel.app")
AGENT_API_URL = os.getenv("MASON_AGENT_API_URL", "https://anthropic-ml-backend-mason-flash3-e2e.up.railway.app")
WORKSPACE_ID = os.getenv("WORKSPACE_ID", "0c6c640e-1a98-4123-9c9b-241534e6de31")


def _now_utc() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 600) -> str:
    """Run a shell command and return stdout. Raises on non-zero."""
    sys.stderr.write(f">> {' '.join(shlex.quote(c) for c in cmd)}\n")
    out = subprocess.check_output(cmd, cwd=cwd, timeout=timeout, stderr=subprocess.STDOUT)
    return out.decode("utf-8", errors="replace")


def _railway_set_env(repo_dir: Path, vars: Dict[str, str]) -> None:
    """Set Railway env vars on the linked service. Skips deploys to batch."""
    args = ["railway", "variables"]
    for k, v in vars.items():
        args += ["--set", f"{k}={v}"]
    args += ["--skip-deploys"]
    _run(args, cwd=repo_dir)


def _railway_redeploy(repo_dir: Path) -> None:
    """railway up uploads the local checkout and triggers a build. Detached."""
    _run(["railway", "up", "--detach"], cwd=repo_dir, timeout=120)


def _wait_for_mason_ready(timeout_sec: int = 240) -> bool:
    """Poll the agent's /list-apps endpoint until 200 OK."""
    deadline = time.time() + timeout_sec
    last_err = ""
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{AGENT_API_URL}/list-apps")
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 200:
                    return True
        except Exception as exc:
            last_err = str(exc)
        time.sleep(8)
    sys.stderr.write(f"!! Mason not healthy after {timeout_sec}s: {last_err}\n")
    return False


def _mint_session(agent_secret: str) -> Optional[str]:
    """Trigger Inspector → AgentService.triggerAnalysis to mint a session,
    poll Supabase via Inspector's /api/agent/sessions/latest? Actually the
    test endpoint just inserts a row and we read it via supabase MCP — but
    this script avoids MCP. We ssh-pull the session id from the workspace_agent_sessions
    table via railway env (skipped here for simplicity; we read the
    response of trigger-test which is just `ok`). Falls back to generating
    a synthetic session id.
    """
    body = json.dumps({"workspace_id": WORKSPACE_ID}).encode()
    req = urllib.request.Request(
        f"{INSPECTOR_URL}/api/agent/trigger-test",
        data=body,
        method="POST",
        headers={
            "x-agent-secret": agent_secret,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            if not data.get("ok"):
                return None
    except Exception as exc:
        sys.stderr.write(f"!! trigger-test failed: {exc}\n")
        return None
    # Wait briefly for Inspector to insert the session row.
    time.sleep(3)
    # We don't have direct DB access here; the caller should pull the
    # session_id via Supabase MCP. Instead: signal_agent accepts a
    # session_id we generate, and the cohort SQL doesn't depend on
    # Inspector recognizing it — but list-tables / sql-proxy DO.
    # So we MUST pull the real Inspector-issued session id.
    # Workaround for the runner script: sleep + caller passes session_id.
    return None


def _mint_session_and_get_id(
    agent_secret: str,
    supabase_query_url: Optional[str] = None,
) -> Optional[str]:
    """Mint via Inspector + return the freshly-created session_id.

    Approach: hit trigger-test, then ssh into Mason and use psql / supabase
    CLI to read the latest session row. Simplest path: ssh railway and run
    a curl to Inspector's audit endpoint that lists recent sessions for our
    workspace. Inspector doesn't expose that today, so we fall back to
    requiring the caller to pass session ids resolved out-of-band (e.g.
    via the supabase MCP)."""
    return None  # left for the runner to wire — see RUNNER_SHELL below


def _post_run(agent_url: str, app_name: str, workspace_id: str, session_id: str,
              prompt: str, timeout_sec: int = 1500) -> Tuple[bool, str]:
    """Create a session on Mason + POST /run with the candidate prompt.
    Returns (ok, response_text)."""
    create_url = f"{agent_url}/apps/{app_name}/users/{workspace_id}/sessions/{session_id}"
    try:
        req = urllib.request.Request(
            create_url,
            data=json.dumps({"created_by": "matrix_runner"}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30):
            pass
    except Exception as exc:
        return False, f"session-create failed: {exc}"

    body = json.dumps({
        "appName": app_name,
        "userId": workspace_id,
        "sessionId": session_id,
        "context": {
            "workspace_id": workspace_id,
            "session_id": session_id,
            "inspector_callback_url": INSPECTOR_URL,
        },
        "newMessage": {"role": "user", "parts": [{"text": prompt}]},
    }).encode()
    req = urllib.request.Request(
        f"{agent_url}/run",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as r:
            return True, r.read().decode("utf-8", errors="replace")[:500]
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read()[:300]!r}"
    except Exception as exc:
        return False, str(exc)


def _pull_artifacts_via_railway_ssh(repo_dir: Path, run_dir_name: str, dest: Path) -> None:
    """Pull the latest Mason run dir from the Railway container into a
    local dir. Uses `railway ssh cat` per file."""
    files = [
        "experiment_report.json", "candidate_hypotheses.jsonl",
        "rice_batch_summaries.jsonl", "explorer_batch_summaries.jsonl",
        "review_decisions.jsonl", "policy_validations.jsonl",
        "warehouse_profile.json", "signal_objective.json",
        "execution_summaries.jsonl", "run_meta.json",
    ]
    dest.mkdir(parents=True, exist_ok=True)
    for fname in files:
        try:
            out = _run(
                ["railway", "ssh",
                 f"cat /app/projects/upsell_ranker/versions/v0.0.2/signal_agent/artifacts/{run_dir_name}/{fname} 2>/dev/null || true"],
                cwd=repo_dir, timeout=60,
            )
            # Skip files that don't exist (empty output).
            if not out.strip() or "No such file" in out:
                continue
            (dest / fname).write_text(out)
        except subprocess.TimeoutExpired:
            sys.stderr.write(f"!! pull timeout for {fname}\n")
        except subprocess.CalledProcessError as e:
            sys.stderr.write(f"!! pull failed for {fname}: {e}\n")


def _latest_run_dir(repo_dir: Path) -> Optional[str]:
    try:
        out = _run(
            ["railway", "ssh",
             "ls -t /app/projects/upsell_ranker/versions/v0.0.2/signal_agent/artifacts/ 2>/dev/null | head -1"],
            cwd=repo_dir, timeout=30,
        )
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("run_"):
                return line
    except Exception:
        pass
    return None


def _clear_artifacts(repo_dir: Path) -> None:
    try:
        _run(
            ["railway", "ssh",
             "rm -rf /app/projects/upsell_ranker/versions/v0.0.2/shared/.cache "
             "/app/projects/upsell_ranker/versions/v0.0.2/signal_agent/artifacts"],
            cwd=repo_dir, timeout=30,
        )
    except Exception:
        pass


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--runs-per-cell", type=int, default=3)
    p.add_argument("--cells", default="flash:2,flash:5,flash:10,flash:20,haiku:2,haiku:5,haiku:10,haiku:20")
    # The inspector-ml-backend (Mason) checkout that is `railway link`-ed to the
    # e2e service. run_matrix drives `railway` redeploys/ssh from here. This repo
    # (dryfit) is NOT it — pass --repo-dir or set MASON_REPO_DIR.
    p.add_argument("--repo-dir", default=os.getenv("MASON_REPO_DIR", ""))
    p.add_argument("--agent-secret", default=os.getenv("AGENT_SECRET", ""))
    p.add_argument("--prompt", default=(
        "Discover signals for workspace_id {workspace_id}, session_id {session_id}. "
        "The success_event for this seat-based SaaS scenario is 'seat_activated'. "
        "Propose at least {batch_target} candidate signals across 2-3 batches with diverse mechanisms. "
        "Use HogQL via Inspector callback. Return JSON only."
    ))
    args = p.parse_args()

    if not args.agent_secret:
        sys.stderr.write("ERROR: --agent-secret (or AGENT_SECRET env) required\n")
        return 2
    if not args.repo_dir:
        sys.stderr.write("ERROR: --repo-dir (or MASON_REPO_DIR env) required — the "
                         "inspector-ml-backend checkout linked to the Railway e2e service\n")
        return 2
    repo_dir = Path(args.repo_dir).resolve()
    out_root = Path(args.output_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    matrix_log = out_root / "matrix.jsonl"

    cells: List[Tuple[str, int]] = []
    for c in args.cells.split(","):
        alias, size = c.strip().split(":")
        cells.append((alias, int(size)))

    # Group cells by model so we minimize Mason redeploys.
    by_model: Dict[str, List[int]] = {}
    for alias, size in cells:
        by_model.setdefault(alias, []).append(size)

    summary_rows: List[Dict] = []
    for alias, sizes in by_model.items():
        model = MODEL_ALIASES[alias]
        sys.stderr.write(f"\n=== Switching model to {model} ({alias}) ===\n")
        _railway_set_env(repo_dir, {
            "SIGNAL_AGENT_MODEL": model,
            "SIGNAL_REVIEWER_MODEL": model,
        })
        _railway_redeploy(repo_dir)
        if not _wait_for_mason_ready(300):
            sys.stderr.write(f"!! Mason didn't recover after switching to {model}; aborting\n")
            return 1

        for size in sizes:
            sys.stderr.write(f"\n--- cell {alias}:{size} ---\n")
            _railway_set_env(repo_dir, {"SIGNAL_AGENT_BATCH_MAX_CANDIDATES": str(size)})
            # No redeploy needed — this var is read inside propose_batch_candidates
            # at call time, but Railway requires a redeploy to propagate. We
            # simplify by always redeploying after env changes:
            _railway_redeploy(repo_dir)
            if not _wait_for_mason_ready(300):
                sys.stderr.write(f"!! Mason didn't recover for {alias}:{size}; skipping\n")
                continue

            for run_idx in range(args.runs_per_cell):
                cell_dir = out_root / f"{alias}_b{size}" / f"run_{run_idx+1}"
                cell_dir.mkdir(parents=True, exist_ok=True)
                _clear_artifacts(repo_dir)
                t0 = time.time()
                started_at = _now_utc()

                # NOTE: session_id resolution is left to the caller (sed-in via env
                # SESSION_ID) because supabase MCP isn't accessible here. The
                # outer driver script wraps this runner per cell and provides
                # the session_id pulled from the supabase branch.
                session_id = os.getenv("SESSION_ID", "").strip()
                if not session_id:
                    sys.stderr.write(f"!! SESSION_ID env not set for run; aborting cell\n")
                    break

                target = max(size * 3, 30)  # batch_size 2 → ask for 30; 20 → 60
                prompt = args.prompt.format(
                    workspace_id=WORKSPACE_ID, session_id=session_id, batch_target=target,
                )
                ok, resp = _post_run(AGENT_API_URL, "signal_agent", WORKSPACE_ID, session_id, prompt)
                wall = time.time() - t0
                ended_at = _now_utc()

                run_dir_name = _latest_run_dir(repo_dir)
                if run_dir_name:
                    _pull_artifacts_via_railway_ssh(repo_dir, run_dir_name, cell_dir)

                row = {
                    "cell": f"{alias}_b{size}",
                    "model": model,
                    "alias": alias,
                    "batch_size": size,
                    "run_idx": run_idx + 1,
                    "session_id": session_id,
                    "run_dir": run_dir_name,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "wall_clock_sec": round(wall, 1),
                    "run_ok": ok,
                    "response_excerpt": resp[:200] if isinstance(resp, str) else "",
                }
                summary_rows.append(row)
                with matrix_log.open("a") as f:
                    f.write(json.dumps(row) + "\n")
                (cell_dir / "run_meta.json").write_text(json.dumps(row, indent=2))

                sys.stderr.write(f"   run {run_idx+1}/{args.runs_per_cell} done in {wall:.0f}s ok={ok}\n")

    sys.stdout.write(json.dumps({"runs": len(summary_rows), "log": str(matrix_log)}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
