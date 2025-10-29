#!/bin/sh
set -e

# Generate md5 password hash for PgBouncer
# Format: md5 + md5(password + username)
PASSWORD_HASH=$(echo -n "${POSTGRES_PASSWORD}${POSTGRES_USER}" | md5sum | cut -d' ' -f1)
echo "\"${POSTGRES_USER}\" \"md5${PASSWORD_HASH}\"" > /etc/pgbouncer/userlist.txt

# Also add admin user if different
if [ -n "${PGBOUNCER_ADMIN_USER}" ] && [ "${PGBOUNCER_ADMIN_USER}" != "${POSTGRES_USER}" ]; then
    ADMIN_PASSWORD_HASH=$(echo -n "${PGBOUNCER_ADMIN_PASSWORD}${PGBOUNCER_ADMIN_USER}" | md5sum | cut -d' ' -f1)
    echo "\"${PGBOUNCER_ADMIN_USER}\" \"md5${ADMIN_PASSWORD_HASH}\"" >> /etc/pgbouncer/userlist.txt
fi

echo "✅ PgBouncer userlist.txt generated successfully"
cat /etc/pgbouncer/userlist.txt

# Start PgBouncer
exec pgbouncer /etc/pgbouncer/pgbouncer.ini

