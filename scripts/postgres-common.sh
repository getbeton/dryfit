#!/usr/bin/env bash

set -euo pipefail

BF_DB_NAME="${BF_DB_NAME:-beton_forge}"
BF_DB_USER="${BF_DB_USER:-$USER}"
BF_DB_HOST="${BF_DB_HOST:-/var/run/postgresql}"
BF_DB_PORT="${BF_DB_PORT:-5432}"
BF_DSN="${BF_DSN:-postgresql:///${BF_DB_NAME}}"

postgres_cluster() {
  if ! command -v pg_lsclusters >/dev/null 2>&1; then
    return 1
  fi

  local cluster
  cluster="$(pg_lsclusters --no-header 2>/dev/null | awk 'NR==1 {print $1 ":" $2}')"
  if [[ -z "${cluster}" ]]; then
    return 1
  fi

  printf '%s\n' "${cluster}"
}

run_cluster_ctl() {
  local action="$1"
  local cluster

  cluster="$(postgres_cluster)" || return 1

  local version="${cluster%%:*}"
  local name="${cluster##*:}"
  sudo pg_ctlcluster "${version}" "${name}" "${action}"
}

start_postgres_service() {
  if run_cluster_ctl start; then
    return 0
  fi

  if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl start postgresql
    return 0
  fi

  if command -v service >/dev/null 2>&1; then
    sudo service postgresql start
    return 0
  fi

  echo "Could not find a supported way to start PostgreSQL on this machine." >&2
  exit 1
}

stop_postgres_service() {
  if run_cluster_ctl stop; then
    return 0
  fi

  if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl stop postgresql
    return 0
  fi

  if command -v service >/dev/null 2>&1; then
    sudo service postgresql stop
    return 0
  fi

  echo "Could not find a supported way to stop PostgreSQL on this machine." >&2
  exit 1
}

postgres_service_status() {
  if command -v pg_lsclusters >/dev/null 2>&1; then
    pg_lsclusters
    return 0
  fi

  if command -v systemctl >/dev/null 2>&1; then
    systemctl status postgresql --no-pager
    return 0
  fi

  if command -v service >/dev/null 2>&1; then
    service postgresql status
    return 0
  fi

  echo "No supported PostgreSQL status command found." >&2
  exit 1
}

wait_for_postgres() {
  local attempts="${1:-20}"
  local sleep_seconds="${2:-1}"
  local i

  for ((i = 1; i <= attempts; i += 1)); do
    if pg_isready -h "${BF_DB_HOST}" -p "${BF_DB_PORT}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${sleep_seconds}"
  done

  echo "PostgreSQL is not ready on ${BF_DB_HOST}:${BF_DB_PORT}." >&2
  exit 1
}

ensure_local_role() {
  local role_exists
  role_exists="$(sudo -u postgres psql postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname = '${BF_DB_USER}'")"
  if [[ "${role_exists}" != "1" ]]; then
    sudo -u postgres createuser --createdb "${BF_DB_USER}"
    return
  fi

  sudo -u postgres psql postgres -c "ALTER ROLE \"${BF_DB_USER}\" CREATEDB;"
}

ensure_local_database() {
  local db_exists
  db_exists="$(sudo -u postgres psql postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '${BF_DB_NAME}'")"
  if [[ "${db_exists}" != "1" ]]; then
    sudo -u postgres createdb -O "${BF_DB_USER}" "${BF_DB_NAME}"
  fi
}

ensure_postgres_prereqs() {
  local missing=()

  for cmd in pg_isready psql pg_dump; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
      missing+=("${cmd}")
    fi
  done

  if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "Missing PostgreSQL client commands: ${missing[*]}" >&2
    echo "Install PostgreSQL server and client packages first, for example: sudo apt install postgresql postgresql-client" >&2
    exit 1
  fi
}
