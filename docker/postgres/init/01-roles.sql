connect beton_forge

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'beton_forge_writer') THEN
    CREATE ROLE beton_forge_writer LOGIN PASSWORD 'beton_forge_writer';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_reader') THEN
    CREATE ROLE grafana_reader LOGIN PASSWORD 'grafana_reader';
  END IF;
END
$$;

GRANT CONNECT, TEMPORARY ON DATABASE beton_forge TO beton_forge_writer;
GRANT CONNECT ON DATABASE beton_forge TO grafana_reader;

GRANT USAGE, CREATE ON SCHEMA public TO beton_forge_writer;
GRANT USAGE ON SCHEMA public TO grafana_reader;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_reader;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO grafana_reader;

ALTER DEFAULT PRIVILEGES FOR ROLE beton_forge_writer IN SCHEMA public
GRANT SELECT ON TABLES TO grafana_reader;

ALTER DEFAULT PRIVILEGES FOR ROLE beton_forge_writer IN SCHEMA public
GRANT USAGE, SELECT ON SEQUENCES TO grafana_reader;

ALTER ROLE grafana_reader SET default_transaction_read_only = on;
