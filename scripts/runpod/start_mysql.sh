#!/usr/bin/env bash
# Start a PiCare-only MySQL instance on a RunPod persistent volume.
# Run from the repository root after creating .env from .env.example.
set -euo pipefail

PICARE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -f "${PICARE_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${PICARE_ROOT}/.env"
  set +a
fi

MYSQL_DATABASE="${MYSQL_DATABASE:-picare}"
MYSQL_USER="${MYSQL_USER:-picare_app}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:?Set MYSQL_PASSWORD in .env before starting MySQL.}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_DATA_DIR="${PICARE_MYSQL_DATA_DIR:-/workspace/picare-mysql}"
MYSQL_SOCKET="${MYSQL_DATA_DIR}/mysql.sock"
MYSQL_PID_FILE="${MYSQL_DATA_DIR}/mysql.pid"
MYSQL_LOG_FILE="${MYSQL_DATA_DIR}/mysql.log"

if ! [[ "${MYSQL_DATABASE}" =~ ^[A-Za-z0-9_]+$ && "${MYSQL_USER}" =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "MYSQL_DATABASE and MYSQL_USER may contain only letters, numbers, and underscores." >&2
  exit 1
fi

if ! command -v mysqld >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y mysql-server
fi

if ! id mysql >/dev/null 2>&1; then
  useradd --system --home "${MYSQL_DATA_DIR}" --shell /usr/sbin/nologin mysql
fi
install -d -m 750 -o mysql -g mysql "${MYSQL_DATA_DIR}"

if [[ ! -d "${MYSQL_DATA_DIR}/mysql" ]]; then
  mysqld --initialize-insecure --user=mysql --datadir="${MYSQL_DATA_DIR}"
fi

if [[ -f "${MYSQL_PID_FILE}" ]] && kill -0 "$(cat "${MYSQL_PID_FILE}")" 2>/dev/null; then
  echo "PiCare MySQL is already running."
else
  nohup mysqld \
    --user=mysql \
    --datadir="${MYSQL_DATA_DIR}" \
    --socket="${MYSQL_SOCKET}" \
    --pid-file="${MYSQL_PID_FILE}" \
    --log-error="${MYSQL_LOG_FILE}" \
    --bind-address=127.0.0.1 \
    --port="${MYSQL_PORT}" \
    >/dev/null 2>&1 &
fi

for _ in {1..30}; do
  if mysqladmin --protocol=socket --socket="${MYSQL_SOCKET}" -uroot ping --silent; then
    break
  fi
  sleep 1
done
mysqladmin --protocol=socket --socket="${MYSQL_SOCKET}" -uroot ping --silent

sql_escape() { printf '%s' "$1" | sed "s/'/''/g"; }
DATABASE_SQL="$(sql_escape "${MYSQL_DATABASE}")"
USER_SQL="$(sql_escape "${MYSQL_USER}")"
PASSWORD_SQL="$(sql_escape "${MYSQL_PASSWORD}")"

mysql --protocol=socket --socket="${MYSQL_SOCKET}" -uroot <<SQL
CREATE DATABASE IF NOT EXISTS \`${DATABASE_SQL}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${USER_SQL}'@'127.0.0.1' IDENTIFIED BY '${PASSWORD_SQL}';
ALTER USER '${USER_SQL}'@'127.0.0.1' IDENTIFIED BY '${PASSWORD_SQL}';
GRANT ALL PRIVILEGES ON \`${DATABASE_SQL}\`.* TO '${USER_SQL}'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL

echo "PiCare MySQL is ready at 127.0.0.1:${MYSQL_PORT}; data: ${MYSQL_DATA_DIR}"
