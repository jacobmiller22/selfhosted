set -e

mkdir -p /run/secrets
# Write only the secrets you need into a file
cat <<EOF > /run/secrets/env_vars
BACKUP_DEST_ENDPOINT=${BACKUP_DEST_ENDPOINT}
BACKUP_DEST_BUCKET=${BACKUP_DEST_BUCKET}
BACKUP_DEST_ACCESS_KEY_ID=${BACKUP_DEST_ACCESS_KEY_ID}
BACKUP_DEST_SECRET_ACCESS_KEY=${BACKUP_DEST_SECRET_ACCESS_KEY}
BACKUP_ENCRYPTION_KEY=${BACKUP_ENCRYPTION_KEY}
EOF

# Optionally, secure the file permissions
chmod 600 /run/secrets/env_vars

cron -f
