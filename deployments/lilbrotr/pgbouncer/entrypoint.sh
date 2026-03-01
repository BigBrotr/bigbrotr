#!/bin/sh
# Generate PgBouncer userlist from environment variables and start PgBouncer.
# Userlist includes admin (for pool management) + writer/reader/refresher application roles.
# Role names are derived from POSTGRES_DB environment variable.

set -eu

WRITER_ROLE="${POSTGRES_DB}_writer"
READER_ROLE="${POSTGRES_DB}_reader"
REFRESHER_ROLE="${POSTGRES_DB}_refresher"

mkdir -p /tmp/pgbouncer
cat > /tmp/pgbouncer/userlist.txt <<EOF
"admin" "${DB_ADMIN_PASSWORD}"
"${WRITER_ROLE}" "${DB_WRITER_PASSWORD}"
"${READER_ROLE}" "${DB_READER_PASSWORD}"
"${REFRESHER_ROLE}" "${DB_REFRESHER_PASSWORD}"
EOF
chmod 600 /tmp/pgbouncer/userlist.txt

exec pgbouncer /etc/pgbouncer/pgbouncer.ini
