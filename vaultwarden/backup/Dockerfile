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


RUN rm -rf /app/staging

COPY backup.sh /app/backup.sh
ADD volbackcron /etc/cronjob

RUN chmod 0644 /etc/cron.d/volbackcron;

RUN crontab /etc/cronjob

CMD ["cron", "-f"]
