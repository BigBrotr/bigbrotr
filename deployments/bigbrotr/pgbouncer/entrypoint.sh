#!/bin/sh
# Generate PgBouncer userlist from environment variables and start PgBouncer.
# Userlist includes admin (for pool management) + writer/reader/refresher application roles.

set -eu

WRITER_ROLE="writer"
READER_ROLE="reader"
REFRESHER_ROLE="refresher"

mkdir -p /tmp/pgbouncer
cat > /tmp/pgbouncer/userlist.txt <<EOF
"admin" "${DB_ADMIN_PASSWORD}"
"${WRITER_ROLE}" "${DB_WRITER_PASSWORD}"
"${READER_ROLE}" "${DB_READER_PASSWORD}"
"${REFRESHER_ROLE}" "${DB_REFRESHER_PASSWORD}"
EOF
chmod 600 /tmp/pgbouncer/userlist.txt

exec pgbouncer /etc/pgbouncer/pgbouncer.ini
