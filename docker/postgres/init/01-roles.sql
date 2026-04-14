connect dryfit

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dryfit_writer') THEN
    CREATE ROLE dryfit_writer LOGIN PASSWORD 'dryfit_writer';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_reader') THEN
    CREATE ROLE grafana_reader LOGIN PASSWORD 'grafana_reader';
  END IF;
END
$$;

GRANT CONNECT, TEMPORARY ON DATABASE dryfit TO dryfit_writer;
GRANT CONNECT ON DATABASE dryfit TO grafana_reader;

GRANT USAGE, CREATE ON SCHEMA public TO dryfit_writer;
GRANT USAGE ON SCHEMA public TO grafana_reader;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_reader;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO grafana_reader;

ALTER DEFAULT PRIVILEGES FOR ROLE dryfit_writer IN SCHEMA public
GRANT SELECT ON TABLES TO grafana_reader;

ALTER DEFAULT PRIVILEGES FOR ROLE dryfit_writer IN SCHEMA public
GRANT USAGE, SELECT ON SEQUENCES TO grafana_reader;

ALTER ROLE grafana_reader SET default_transaction_read_only = on;
