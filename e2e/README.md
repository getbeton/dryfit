# Beton E2E harness

End-to-end test rig for the Beton **Mason** signal-discovery pipeline
(`getbeton/inspector-ml-backend`). It generates dryfit synthetic data and fans
it out to three sinks, then triggers Mason and scores its promoted signals
against dryfit's hidden ground truth.

```
dryfit generate ──┬──▶ PostHog Project B        (synthetic events, HogQL-queryable)
                  ├──▶ Supabase branch          (Inspector workspace + data_sources)
                  └──▶ Beton / Mason on Railway (onboarding trigger → signal run)
                                                      │
                                            promoted signals
                                                      │
                                            score.py vs ground_truth.json
```

This was previously vendored inside `inspector-ml-backend` under
`scripts/dryfit_e2e/` + `scripts/test_env/`. It lives here now so the synthetic
data and its sinks travel with dryfit.

## Layout

| File | Sink / role |
|------|-------------|
| `dryfit_to_posthog.py` | **PostHog sink.** Runs dryfit's engine in-memory (no Postgres) and POSTs events to Project B `/batch`. Writes `ground_truth.json` + `manifest.json`. |
| `posthog_ingest.py` | PostHog sink, Postgres variant — reads a dryfit `events` table and posts to PostHog. Use with `generate.sh`. |
| `bootstrap_workspace.mjs` | **Supabase sink.** Idempotently creates the Inspector test user, workspace, membership, and PostHog `integration_configs` / `posthog_workspace_config` rows (API key AES-256-GCM-encrypted to match Inspector). |
| `run_matrix.py` | **Beton sink (Railway).** Switches the Mason model via `railway`, triggers `/api/agent/trigger-test`, pulls `experiment_report.json` off the container via `railway ssh`, runs a model×batch-size matrix. |
| `run.sh` | Single-scenario **local-Mason** driver (onboarding-complete → poll → score). |
| `generate.sh` | Postgres generate + `posthog_ingest.py`. |
| `score.py` | Coverage-based recall/precision of promoted signals vs ground truth. |
| `posthog_dashboard.py` | Builds a PostHog dashboard summarising a run. |
| `run_e2e.sh` | **Orchestrator** — chains the three sinks (`STAGE=supabase|posthog|beton|all`). |

## Quickstart (Railway flow)

```bash
cd dryfit
uv sync
source ~/.claude/secrets/mason-flash3.env       # or fill in e2e/.env.example
MASON_REPO_DIR=/path/to/inspector-ml-backend ./e2e/run_e2e.sh
```

Single stage, default scenario `posthog_seat_based_mvp`:

```bash
STAGE=posthog ./e2e/run_e2e.sh
SCENARIO=posthog_freemium_to_paid_mvp STAGE=posthog ./e2e/run_e2e.sh
```

Artifacts (ground truth, manifest, workspace.json, scoring, matrix) land under
`e2e/artifacts/<scenario>/` and are gitignored.

## Prerequisites

- `uv` (dryfit deps) and Node.js ≥ 18 (stdlib only — no `npm install`).
- A separate PostHog **Project B**, a Supabase **branch** off the Inspector
  project, and the Mason service deployed to its own **Railway** environment.
  IDs/keys go in `e2e/.env.example`.
- For the Beton stage: a local `inspector-ml-backend` checkout that is
  `railway link`-ed to the e2e service (`MASON_REPO_DIR`), since `run_matrix.py`
  drives `railway` redeploys/ssh from there.

## Notes

- `dryfit_to_posthog.py` sends `historical_migration: true` so PostHog honors
  the synthetic timestamps (events span ~364 days back).
- `bootstrap_workspace.mjs` reads `SUPABASE_URL`; the rig stores it as
  `SUPABASE_BRANCH_URL` and `run_e2e.sh` remaps it.
- No production Inspector / Supabase / PostHog / Mason instance is touched —
  everything points at the dedicated test projects.
