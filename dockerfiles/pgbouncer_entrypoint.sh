#!/bin/sh
set -e

# For SCRAM authentication with auth_query, we need the admin user credentials
# in plain text format for auth_user to work
echo "\"${POSTGRES_USER}\" \"${POSTGRES_PASSWORD}\"" > /etc/pgbouncer/userlist.txt

# Also add admin user if different
if [ -n "${PGBOUNCER_ADMIN_USER}" ] && [ "${PGBOUNCER_ADMIN_USER}" != "${POSTGRES_USER}" ]; then
    echo "\"${PGBOUNCER_ADMIN_USER}\" \"${PGBOUNCER_ADMIN_PASSWORD}\"" >> /etc/pgbouncer/userlist.txt
fi

echo "✅ PgBouncer userlist.txt generated successfully"
echo "Userlist created with ${POSTGRES_USER}"

# Start PgBouncer
exec pgbouncer /etc/pgbouncer/pgbouncer.ini

