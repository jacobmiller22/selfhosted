echo "Running backup!!"

echo "Sourcing secrets"
source /run/secrets/env_vars

echo "Environment: "
echo "$(env)"
echo "Backing up sqlite db!"
mkdir -p "/app/backups/"
sqlite3 /tmp/vw-data/db.sqlite3 ".backup '/app/backups/vw-db-backup.sqlite3'"
chmod 755 "/app/backups/vw-db-backup.sqlite3"
echo "Backup created!"

echo "$(pwd)"
echo "$(ls)"
echo "Saving backup to cloud!"
/app/volback \
	--path="/app/backups/vw-db-backup.sqlite3" \
	--dest.kind="s3" \
	--dest.prefix="backups/vw" \
	--dest.endpoint="${BACKUP_DEST_ENDPOINT}" \
	--dest.bucket="${BACKUP_DEST_BUCKET}" \
	--dest.access-key-id="${BACKUP_DEST_ACCESS_KEY_ID}" \
	--dest.secret-access-key="${BACKUP_DEST_SECRET_ACCESS_KEY}" \
	--enc.key="${BACKUP_ENCRYPTION_KEY}" 
echo "Backup saved to cloud!"

echo "Cleaning up!"
rm "/app/backups/vw-db-backup.sqlite3"

echo "Finished running backup!!"
