FROM golang:1.24

RUN apt-get update && apt-get -y --no-install-recommends install cron tar wget build-essential sqlite3;

WORKDIR /app/staging

ARG VOLBACK_VERSION=0.1.0

RUN wget --no-check-certificate "https://github.com/jacobmiller22/volback/archive/refs/tags/v${VOLBACK_VERSION}.tar.gz"

# Creates a volback-0.1.0 directory
RUN tar -xzf "v${VOLBACK_VERSION}.tar.gz";

WORKDIR "/app/staging/volback-${VOLBACK_VERSION}"

RUN make build;

RUN cp bin/volback /app/volback;

WORKDIR /app

# Clean up staging area
RUN rm -rf /app/staging 

COPY backup.sh /app/backup.sh
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod 0755 /app/backup.sh
RUN chmod 0755 /app/entrypoint.sh

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

CMD ["/bin/bash", "/app/entrypoint.sh"]
