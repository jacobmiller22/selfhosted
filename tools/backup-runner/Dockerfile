FROM alpine:3.21

# Install runtime dependencies for standardized backup runner:
# - bash: for strict error handling and scripts
# - curl: for Discord webhooks and Healthchecks.io pings
# - openssl: for AES-256-CBC PBKDF2 encryption matching RESTORE.md
# - sqlite: for live database snapshotting via sqlite3 .backup API
# - tar: for staging archive creation
# - rclone: for fast, robust S3/B2 cloud upload
# - ca-certificates & tzdata: for TLS certs and accurate timestamps
RUN apk add --no-cache \
    bash \
    curl \
    openssl \
    sqlite \
    tar \
    rclone \
    ca-certificates \
    tzdata

WORKDIR /app

# Configure secret isolation directory with restricted permissions
RUN mkdir -p /run/secrets && chmod 700 /run/secrets

COPY backup-engine.sh /app/backup-engine.sh
COPY entrypoint.sh /app/entrypoint.sh

# Install scripts and ensure PATH availability
RUN chmod 0755 /app/backup-engine.sh /app/entrypoint.sh && \
    ln -s /app/backup-engine.sh /usr/local/bin/backup-engine && \
    ln -s /app/backup-engine.sh /app/backup.sh

ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]
