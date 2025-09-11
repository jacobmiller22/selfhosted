#!/bin/bash

echo "Running backup!!"

echo "Sourcing secrets"
source /run/secrets/env_vars

target_path="/tmp/actual-data"
backup_dirname="actual-data-backup-$(date +'%Y-%m-%d_%H-%M-%S')"
destination_path="backups/actual/data-backup.zip.enc"

backup_path="/app/backups/${backup_dirname}"
backup_parent_path=$(dirname "$backup_path")

echo "Backing up sqlite db at ${target_path} to ${backup_path}"

mkdir -p $backup_parent_path

cp -r $target_path "$backup_path"
chmod 777 "$backup_path"

echo "Backup created!"

echo "Saving backup to cloud!"
/app/volback \
	--src.kind="fs" \
	--src.path="$backup_path" \
	--enc.key="${BACKUP_ENCRYPTION_KEY}"  \
	--dst.kind="s3" \
	--dst.path="${destination_path}" \
	--dst.s3-endpoint="${BACKUP_DEST_ENDPOINT}" \
	--dst.s3-bucket="${BACKUP_DEST_BUCKET}" \
	--dst.s3-access-key-id="${BACKUP_DEST_ACCESS_KEY_ID}" \
	--dst.s3-secret-access-key="${BACKUP_DEST_SECRET_ACCESS_KEY}" \
	--dst.s3-region="us-east-1" 

echo "Backup saved to cloud!"

echo "Cleaning up!"
rm $backup_path

echo "Finished running backup!"
