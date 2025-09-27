#!/bin/bash

echo "Running backup!!"

echo "Sourcing secrets"
source /run/secrets/env_vars

target_path="/tmp/actual-data"
backup_dirname="actual-data-backup-$(date +'%Y-%m-%d_%H-%M-%S')"
destination_path="backups/actual/data-backup.zip.enc"

backup_path="/app/backups/${backup_dirname}"
backup_parent_path=$(dirname "$backup_path")

echo "Backing up directory at ${target_path} to ${backup_path}"

mkdir -p $backup_parent_path

cp -r $target_path "$backup_path"
chmod 777 "$backup_path"

echo "Backup created!"

echo "Saving backup to cloud!"
/app/volback \
	--src.kind="fs" \
	--src.path="$backup_path" \
	--enc.key="${BACKUP_ENCRYPTION_KEY}"  \
	--dst.kind="b2" \
	--dst.path="${destination_path}" \
	--dst.b2-endpoint="${BACKUP_DEST_ENDPOINT}" \
	--dst.b2-bucket="${BACKUP_DEST_BUCKET}" \
	--dst.b2-application-key-id="${BACKUP_DEST_ACCESS_KEY_ID}" \
	--dst.b2-application--key="${BACKUP_DEST_SECRET_ACCESS_KEY}" \

echo "Backup saved to cloud!"

echo "Cleaning up!"
rm -rf $backup_path

echo "Finished running backup!"
