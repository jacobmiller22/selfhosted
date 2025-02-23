FROM golang:1.24

RUN apt-get update && apt-get -y --no-install-recommends install cron tar wget build-essential sqlite3;

WORKDIR /app/staging

RUN wget --no-check-certificate "https://github.com/jacobmiller22/volback/archive/refs/tags/v0.0.1.tar.gz"

# Creates a volback-0.0.1 directory
RUN tar -xzf v0.0.1.tar.gz;

WORKDIR /app/staging/volback-0.0.1

RUN make build;

RUN cp bin/volume-backup /app/volback;

WORKDIR /app

COPY backup.sh /app/backup.sh
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod 0755 /app/backup.sh

ADD volbackcron /etc/cronjob
RUN crontab /etc/cronjob


ARG BACKUP_DEST_ENDPOINT 
ENV BACKUP_DEST_ENDPOINT=$BACKUP_DEST_ENDPOINT

ARG BACKUP_DEST_BUCKET
ENV BACKUP_DEST_BUCKET=$BACKUP_DEST_BUCKET

ARG BACKUP_DEST_ACCESS_KEY_ID
ENV BACKUP_DEST_ACCESS_KEY_ID=$BACKUP_DEST_ACCESS_KEY_ID

ARG BACKUP_DEST_SECRET_ACCESS_KEY
ENV BACKUP_DEST_SECRET_ACCESS_KEY=$BACKUP_DEST_SECRET_ACCESS_KEY

ARG BACKUP_ENCRYPTION_KEY
ENV BACKUP_ENCRYPTION_KEY=$BACKUP_ENCRYPTION_KEY

CMD ["/app/entrypoint.sh"]
