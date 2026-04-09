#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="${SCRIPT_DIR}/dumps"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DUMP_FILE="${BACKUP_DIR}/testbrotr_${TIMESTAMP}.sql.gz"
source "${SCRIPT_DIR}/.env"

mkdir -p "${BACKUP_DIR}"

docker exec -e PGPASSWORD="${DB_ADMIN_PASSWORD}" testbrotr-postgres \
  pg_dump -U admin -d testbrotr \
    --no-owner --no-privileges \
    -Z 6 \
  > "${DUMP_FILE}"

ls -t "${BACKUP_DIR}"/testbrotr_*.sql.gz | tail -n +8 | xargs -r rm

echo "[$(date)] Backup completed: ${DUMP_FILE} ($(du -h "${DUMP_FILE}" | cut -f1))"
