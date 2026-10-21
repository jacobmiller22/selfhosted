FROM rust:1-bookworm AS builder

ARG GITHUB_TOKEN=""
ARG BTCUPDOWN_REPO="github.com/jacobmiller22/btcupdown.git"
ARG BTCUPDOWN_REF="main"

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    pkg-config \
    libsqlite3-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN if [ -n "${GITHUB_TOKEN}" ]; then \
      git clone --depth 1 --branch "${BTCUPDOWN_REF}" \
        "https://x-access-token:${GITHUB_TOKEN}@${BTCUPDOWN_REPO}" /app/src; \
    else \
      git clone --depth 1 --branch "${BTCUPDOWN_REF}" \
        "https://${BTCUPDOWN_REPO}" /app/src; \
    fi

WORKDIR /app/src
RUN cargo build --release --bin data-broker --bin vixxy-poller

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libsqlite3-0 \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/src/target/release/data-broker /usr/local/bin/data-broker
COPY --from=builder /app/src/target/release/vixxy-poller /usr/local/bin/vixxy-poller
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /data
VOLUME ["/data"]
EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
