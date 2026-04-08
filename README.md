# beton-forge

`beton-forge` generates synthetic analytics event data plus hidden benchmark truth so agents can be tested on signal discovery tasks.

## Status

The current repo shape is:

- one scenario per run
- one backend: PostgreSQL
- one physical table: `events`
- two scenarios: `posthog_web`, `telegram_chat`
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
  dsn: postgresql:///beton_forge
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
- creates the `beton_forge` database if needed

### Generate data into the local database

Use the wrapper if you want the repo to start and initialize the local database before generation:

```bash
./scripts/generate-local -c configs/posthog_mvp.yaml --print-summary
./scripts/generate-local -c configs/telegram_mvp.yaml --output-dir ./artifacts/telegram
```

If you already started the database yourself, the direct CLI is:

```bash
uv run beton-forge -c configs/posthog_mvp.yaml --print-summary
uv run beton-forge -c configs/telegram_mvp.yaml --output-dir ./artifacts/telegram
```

Helpful flags:

- `--dry-run`
- `--output-dir`
- `--skip-db-write`
- `--print-summary`

If you want to generate artifacts without touching PostgreSQL:

```bash
uv run beton-forge -c configs/posthog_mvp.yaml --skip-db-write --print-summary
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

### Dump and restore the database

Dump the local database to a portable SQL file:

```bash
./scripts/postgres-local-dump
```

By default this writes to `db_dumps/<database>_<timestamp>/database.sql`.

Restore that dump on another machine after PostgreSQL is installed:

```bash
./scripts/postgres-local-restore ./db_dumps/beton_forge_YYYYMMDD_HHMMSS/database.sql
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

## Development Notes

- Faker is used for human-like metadata, not for core signal logic.
- Noise never mutates rows referenced by ground truth.
- The architecture is centered on scenario and signal modularity; PostgreSQL is a thin materializer layer.
