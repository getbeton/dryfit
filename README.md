# dryfit

`dryfit` generates synthetic analytics event data plus hidden benchmark truth so agents can be tested on signal discovery tasks.

> 📚 Browse every scenario with config breakdowns, signal paths, and docker quickstarts on [getbeton.ai/oss-tools/dryfit](https://www.getbeton.ai/oss-tools/dryfit/).

## Status

The current repo shape is:

- one scenario per run
- one backend: PostgreSQL
- one physical table: `events`
- two baseline scenarios: [`posthog_web`](https://www.getbeton.ai/oss-tools/dryfit/scenarios/posthog-web/), [`telegram_chat`](https://www.getbeton.ai/oss-tools/dryfit/scenarios/telegram-chat/)
- thirteen PostHog business-model variants — see [full scenario catalog](https://www.getbeton.ai/oss-tools/dryfit/scenarios/)
- two signal kinds: `positive_path`, `negative_path`
- truth documents reference actual generated `event_id` values

## Requirements

- Python 3.12
- `uv`
- PostgreSQL server and client tools

On Debian or Ubuntu Linux:

```bash
sudo apt update
sudo apt install uv
sudo apt install postgresql postgresql-client
```

`postgresql-client-common` alone is not enough. You need the actual server package and at least one versioned client package, which `postgresql` and `postgresql-client` install for you.

## Python Setup

Install the Python dependencies with:

```bash
uv sync
```

## Local PostgreSQL Workflow

The sample configs use a local Unix-socket DSN:

```yaml
backend:
  kind: postgres
  dsn: postgresql:///dryfit
```

That avoids assuming a TCP listener on `127.0.0.1:5432` and works well for a local Linux install.

### One-time local database setup

These scripts assume a Debian or Ubuntu style PostgreSQL install and may prompt for `sudo` when starting or initializing the local server.

```bash
./scripts/postgres-local-start
./scripts/postgres-local-init
./scripts/postgres-local-status
```

What `postgres-local-init` does:

- starts PostgreSQL if needed
- waits until the server is ready
- creates a PostgreSQL role matching your current Linux username if needed
- grants that role `CREATEDB`
- creates the `dryfit` database if needed

### Generate data into the local database

Use the wrapper if you want the repo to start and initialize the local database before generation:

```bash
./scripts/generate-local -c configs/posthog_mvp.yaml --print-summary
./scripts/generate-local -c configs/telegram_mvp.yaml --output-dir ./artifacts/telegram
```

If you already started the database yourself, the direct CLI is:

```bash
uv run dryfit -c configs/posthog_mvp.yaml --print-summary
uv run dryfit -c configs/telegram_mvp.yaml --output-dir ./artifacts/telegram
```

Helpful flags:

- `--dry-run`
- `--output-dir`
- `--skip-db-write`
- `--print-summary`

If you want to generate artifacts without touching PostgreSQL:

```bash
uv run dryfit -c configs/posthog_mvp.yaml --skip-db-write --print-summary
```

### Inspect or manage the local database

Open a `psql` shell:

```bash
./scripts/postgres-local-shell
```

Check service state:

```bash
./scripts/postgres-local-status
```

Stop the local PostgreSQL service:

```bash
./scripts/postgres-local-stop
```

## Docker Inspection Workflow

For visual inspection in Grafana, the repo now includes a Docker Compose stack with:

- PostgreSQL on `127.0.0.1:54329`
- Grafana on `http://127.0.0.1:3000`
- a provisioned PostgreSQL datasource
- a provisioned dashboard: `Generated Event Inspection`

Start the full inspection stack with:

```bash
docker compose up -d
```

Local-only credentials used by the stack:

- PostgreSQL writer: `dryfit_writer` / `dryfit_writer`
- PostgreSQL Grafana reader: `grafana_reader` / `grafana_reader`
- Grafana admin: `admin` / `admin`

Generate data into the Dockerized PostgreSQL without editing the checked-in config:

```bash
uv run dryfit \
  -c configs/posthog_mvp.yaml \
  --dsn postgresql://dryfit_writer:dryfit_writer@127.0.0.1:54329/dryfit \
  --print-summary
```

You can do the same with the Telegram config:

```bash
uv run dryfit \
  -c configs/telegram_mvp.yaml \
  --dsn postgresql://dryfit_writer:dryfit_writer@127.0.0.1:54329/dryfit \
  --print-summary
```

Then open Grafana:

```bash
open http://127.0.0.1:3000
```

If `open` is not available on your machine, use your browser directly. The provisioned home dashboard lets you:

- inspect event counts over time
- filter by `identity_id` (`entity_id` in the database)
- filter by `event_id`
- inspect raw rows including `event_props`

To iterate on generation, change the config, rerun the generator with the same `--dsn`, and refresh Grafana. The dashboard and datasource stay in place because they are provisioned from files in this repo.

### Dump and restore the database

Dump the local database to a portable SQL file:

```bash
./scripts/postgres-local-dump
```

By default this writes to `db_dumps/<database>_<timestamp>/database.sql`.

Restore that dump on another machine after PostgreSQL is installed:

```bash
./scripts/postgres-local-restore ./db_dumps/dryfit_YYYYMMDD_HHMMSS/database.sql
```

For a full dataset handoff, copy both:

- the SQL dump from `db_dumps/`
- the matching artifacts directory from `artifacts/<dataset_id>/`

## Config Shape

Config is the main authoring surface. Each run selects exactly one scenario and one PostgreSQL target.

Key sections:

- `scenario.kind`
- `scale`
- `success`
- `signals.positive`
- `signals.negative`
- `noise`
- `faker`

Positive paths must end with the scenario success event. Negative paths must not.

Template `entity_type` is optional. If omitted, `success.entity_type` is used as the default binding target.

## Output

Each non-dry run writes:

- a PostgreSQL `events` table
- `ground_truth.json`
- `manifest.json`

Artifacts default to `artifacts/<dataset_id>/`.

The PostgreSQL writer replaces the target `events` table each run. This keeps benchmark datasets isolated and reproducible.

## Business Model Scenarios

The repo now includes additional PostHog DWH scenarios based directly on the business-model research mapping: value metric -> target events -> proxy signal patterns. These configs still use the current path-based signal engine, so the implemented "signals" are sequence proxies for the researched business metrics rather than true MoM or quota-style aggregations.

Each section below links to a detail page with the full config breakdown, signal-path visualization, noise parameters, and a per-scenario quickstart. [Browse all scenarios →](https://www.getbeton.ai/oss-tools/dryfit/scenarios/)

### [Seat-based SaaS](https://www.getbeton.ai/oss-tools/dryfit/scenarios/posthog-seat-based/)

- Config: `configs/posthog_seat_based_mvp.yaml`
- Value metric: active seats / users
- Target events: `invite_sent`, `user_signed_up`, `$identify`, `role_assigned`, `seat_activated`, `seat_deactivated`
- Success event: `seat_activated`
- Positive signals: `invite_sent -> user_signed_up -> seat_activated`, `role_assigned -> seat_activated`
- Negative signals: `invite_sent -> user_signed_up`, `seat_activated -> seat_deactivated`
- Research metrics this proxies: seat growth %, active/total seat ratio, invite-to-activation rate

### [Usage-based (metered)](https://www.getbeton.ai/oss-tools/dryfit/scenarios/posthog-usage-based/)

- Config: `configs/posthog_usage_based_mvp.yaml`
- Value metric: API calls, compute hours, messages, requests
- Target events: `api_request`, `job_completed`, `message_sent`, `compute_hours_used`
- Success event: `job_completed`
- Positive signals: `api_request -> job_completed`, `message_sent -> compute_hours_used -> job_completed`
- Negative signals: `api_request -> compute_hours_used`, `message_sent -> message_sent`
- Research metrics this proxies: usage velocity, quota consumption, usage acceleration

### [Transaction / volume-based](https://www.getbeton.ai/oss-tools/dryfit/scenarios/posthog-transaction-volume/)

- Config: `configs/posthog_transaction_volume_mvp.yaml`
- Value metric: transactions processed, GMV, payments
- Target events: `payment_completed`, `order_created`, `invoice_generated`, `refund_issued`
- Success event: `payment_completed`
- Positive signals: `order_created -> payment_completed`, `order_created -> invoice_generated -> payment_completed`
- Negative signals: `order_created -> invoice_generated`, `payment_completed -> refund_issued`
- Research metrics this proxies: transaction volume trend, avg transaction value growth, transaction frequency per account

### [Storage-based](https://www.getbeton.ai/oss-tools/dryfit/scenarios/posthog-storage-based/)

- Config: `configs/posthog_storage_based_mvp.yaml`
- Value metric: GB stored, records managed, files hosted
- Target events: `file_uploaded`, `record_created`, `storage_warning_shown`
- Success event: `file_uploaded`
- Positive signals: `record_created -> file_uploaded`, `file_uploaded -> file_uploaded`
- Negative signals: `file_uploaded -> storage_warning_shown`, `storage_warning_shown -> storage_warning_shown`
- Research metrics this proxies: storage growth rate, days-to-tier-limit, upload frequency trend

### [Contact / record-based](https://www.getbeton.ai/oss-tools/dryfit/scenarios/posthog-contact-record/)

- Config: `configs/posthog_contact_record_mvp.yaml`
- Value metric: contacts, leads, subscribers, accounts managed
- Target events: `contact_created`, `list_imported`, `enrichment_completed`, `segment_created`
- Success event: `contact_created`
- Positive signals: `list_imported -> contact_created`, `contact_created -> enrichment_completed -> contact_created`
- Negative signals: `list_imported -> segment_created`, `contact_created -> segment_created`
- Research metrics this proxies: contact growth rate, % of contact limit used, import frequency

### [Feature-gated (tiered)](https://www.getbeton.ai/oss-tools/dryfit/scenarios/posthog-feature-gated/)

- Config: `configs/posthog_feature_gated_mvp.yaml`
- Value metric: plan tier / feature access level
- Target events: `feature_gate_shown`, `upgrade_clicked`, `advanced_feature_attempted`, `downgrade`
- Success event: `upgrade_clicked`
- Positive signals: `feature_gate_shown -> upgrade_clicked`, `advanced_feature_attempted -> feature_gate_shown -> upgrade_clicked`
- Negative signals: `advanced_feature_attempted -> feature_gate_shown`, `upgrade_clicked -> downgrade`
- Research metrics this proxies: gate-hit frequency, advanced-feature attempt rate, time between gate hits

### [Platform / marketplace](https://www.getbeton.ai/oss-tools/dryfit/scenarios/posthog-marketplace/)

- Config: `configs/posthog_marketplace_mvp.yaml`
- Value metric: listings, storefronts, connected accounts, integrations
- Target events: `listing_published`, `storefront_activated`, `account_connected`, `integration_enabled`
- Success event: `listing_published`
- Positive signals: `account_connected -> storefront_activated -> listing_published`, `integration_enabled -> listing_published`
- Negative signals: `account_connected -> storefront_activated`, `integration_enabled -> account_connected`
- Research metrics this proxies: active listing growth, seller/buyer activation rate, marketplace liquidity ratio

### [Revenue-share / take-rate](https://www.getbeton.ai/oss-tools/dryfit/scenarios/posthog-revenue-share/)

- Config: `configs/posthog_revenue_share_mvp.yaml`
- Value metric: revenue processed, bookings, GMV through platform
- Target events: `booking_completed`, `payout_processed`, `commission_calculated`
- Success event: `commission_calculated`
- Positive signals: `booking_completed -> commission_calculated`, `booking_completed -> payout_processed -> commission_calculated`
- Negative signals: `booking_completed -> payout_processed`, `payout_processed -> payout_processed`
- Research metrics this proxies: GMV growth trend, take-rate stability, payout frequency

### [Credits / token-based](https://www.getbeton.ai/oss-tools/dryfit/scenarios/posthog-credits-token/)

- Config: `configs/posthog_credits_token_mvp.yaml`
- Value metric: credits consumed, tokens used, compute units
- Target events: `credits_purchased`, `credits_used`, `low_balance_warning`, `auto_refill_triggered`
- Success event: `credits_purchased`
- Positive signals: `low_balance_warning -> credits_purchased`, `low_balance_warning -> auto_refill_triggered -> credits_purchased`
- Negative signals: `credits_used -> low_balance_warning`, `low_balance_warning -> low_balance_warning`
- Research metrics this proxies: burn rate, days-to-zero, top-up frequency, auto-refill adoption

### [Hybrid (seat + usage)](https://www.getbeton.ai/oss-tools/dryfit/scenarios/posthog-hybrid-seat-usage/)

- Config: `configs/posthog_hybrid_seat_usage_mvp.yaml`
- Value metric: seats plus usage overage
- Target events: `invite_sent`, `user_signed_up`, `seat_activated`, `api_request`, `job_completed`, `compute_hours_used`
- Success event: `compute_hours_used`
- Positive signals: `invite_sent -> user_signed_up -> seat_activated -> api_request -> compute_hours_used`, `seat_activated -> api_request -> job_completed -> compute_hours_used`
- Negative signals: `invite_sent -> user_signed_up -> seat_activated`, `api_request -> job_completed`
- Research metrics this proxies: seat growth plus usage acceleration, overage frequency

### [Freemium-to-paid](https://www.getbeton.ai/oss-tools/dryfit/scenarios/posthog-freemium-to-paid/)

- Config: `configs/posthog_freemium_to_paid_mvp.yaml`
- Value metric: active usage hitting free-tier limits
- Target events: `limit_reached`, `upgrade_modal_shown`, `feature_blocked`, `trial_started`
- Success event: `trial_started`
- Positive signals: `limit_reached -> upgrade_modal_shown -> trial_started`, `feature_blocked -> upgrade_modal_shown -> trial_started`
- Negative signals: `limit_reached -> upgrade_modal_shown`, `feature_blocked -> feature_blocked`
- Research metrics this proxies: time-to-limit, limit-hit frequency, conversion funnel drop-off

### [Event-volume SaaS](https://www.getbeton.ai/oss-tools/dryfit/scenarios/posthog-event-volume/)

- Config: `configs/posthog_event_volume_mvp.yaml`
- Value metric: events tracked, data points ingested, log lines
- Target events: `$pageview`, `$autocapture`, `custom_event_tracked`, `source_connected`, `schema_changed`
- Success event: `custom_event_tracked`
- Positive signals: `source_connected -> $pageview -> custom_event_tracked`, `schema_changed -> custom_event_tracked`
- Negative signals: `source_connected -> $pageview`, `schema_changed -> schema_changed`
- Research metrics this proxies: ingestion volume trend, event-type diversity, new-source activation rate

### [Combined coverage scenario](https://www.getbeton.ai/oss-tools/dryfit/scenarios/posthog-combined-coverage/)

- Config: `configs/posthog_business_models_combined_mvp.yaml`
- Purpose: generate one PostHog-style dataset containing the union of all researched business-model event types
- Success event: `upgrade_clicked`
- Positive signals: coverage-oriented mixed paths such as `limit_reached -> upgrade_modal_shown -> upgrade_clicked`
- Negative signals: mixed cross-model paths such as `credits_used -> low_balance_warning`
- Use this when you want one dataset that exercises all supported event names in Grafana or PostgreSQL inspection

## Generating a Fresh PostgreSQL Events Table

Any non-dry run replaces the PostgreSQL `events` table with the rows from the selected config.

For the local Linux PostgreSQL workflow:

```bash
uv run dryfit -c configs/posthog_seat_based_mvp.yaml --print-summary
```

You can swap in any of the new configs, for example:

```bash
uv run dryfit -c configs/posthog_usage_based_mvp.yaml --print-summary
uv run dryfit -c configs/posthog_business_models_combined_mvp.yaml --print-summary
```

For the Dockerized PostgreSQL inspection stack:

```bash
uv run dryfit \
  -c configs/posthog_feature_gated_mvp.yaml \
  --dsn postgresql://dryfit_writer:dryfit_writer@127.0.0.1:54329/dryfit \
  --print-summary
```

To regenerate with a different scenario, rerun the same command with a different config path. The `events` table is recreated each run, so Grafana will show the new dataset after a refresh.

## Development Notes

- Faker is used for human-like metadata, not for core signal logic.
- Noise never mutates rows referenced by ground truth.
- The architecture is centered on scenario and signal modularity; PostgreSQL is a thin materializer layer.


---

## About

`dryfit` is part of [Beton](https://www.getbeton.ai/), open-source revenue intelligence. We detect buying signals in product usage data and route them to your CRM. Other open-source tools we maintain:

- [Inspector](https://www.getbeton.ai/) — the flagship signal-discovery agent
- [openclaw-gtm-skills](https://www.getbeton.ai/oss-tools/openclaw-gtm-skills/) — company research pipeline for OpenClaw
- [seqd](https://www.getbeton.ai/oss-tools/seqd/) — self-hosted email sequencer

Browse [all open-source tools by Beton →](https://www.getbeton.ai/oss-tools/)
