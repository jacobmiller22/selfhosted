echo "Running backup!!"


echo "Backing up sqlite db!"
sqlite3 /tmp/vw-data/db.sqlite3 ".backup './vw-db-backup.sqlite3'"
echo "Backup created!"

echo "Saving backup to cloud!"
./volback \
	--path=/Users/jacobmiller22/Documents/bjorn-coolify.env \
	--dest.kind="s3" \
	--dest.prefix="backups/vw" \
	--dest.endpoint="${BACKUP_DEST_ENDPOINT}" \
	--dest.bucket="${BACKUP_DEST_BUCKET}" \
	--dest.access-key-id="${BACKUP_DEST_ACCESS_KEY_ID}" \
	--dest.secret-access-key="${BACKUP_DEST_SECRET_ACCESS_KEY}" \
	--enc.key="${BACKUP_ENCRYPTION_KEY}" 
echo "Backup saved to cloud!"

echo "Finished running backup!!"
