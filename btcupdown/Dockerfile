FROM rust:1-bookworm AS builder

ARG GITHUB_TOKEN=""
ARG BTCUPDOWN_REPO="github.com/jacobmiller22/btcupdown.git"
ARG BTCUPDOWN_REF="main"
ARG BTCUPDOWN_COMMIT="317776b"

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    pkg-config \
    libsqlite3-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN echo "Cloning ${BTCUPDOWN_REPO}@${BTCUPDOWN_REF} (${BTCUPDOWN_COMMIT})" && \
    if [ -n "${GITHUB_TOKEN}" ]; then \
      git clone --depth 1 --branch "${BTCUPDOWN_REF}" \
        "https://x-access-token:${GITHUB_TOKEN}@${BTCUPDOWN_REPO}" /app/src; \
    else \
      git clone --depth 1 --branch "${BTCUPDOWN_REF}" \
        "https://${BTCUPDOWN_REPO}" /app/src; \
    fi

WORKDIR /app/src
RUN cargo build --release \
    --bin data-broker \
    --bin vixxy-poller \
    --bin kalshi-poller \
    --bin btcupdown-engine \
    --bin btcupdown-cli
RUN sed -i 's/status=open&limit=10/limit=100/g' crates/kalshi-poller/src/lib.rs && \
    cargo build --release --bin kalshi-poller

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libsqlite3-0 \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/src/target/release/data-broker /usr/local/bin/data-broker
COPY --from=builder /app/src/target/release/vixxy-poller /usr/local/bin/vixxy-poller
COPY --from=builder /app/src/target/release/kalshi-poller /usr/local/bin/kalshi-poller
COPY --from=builder /app/src/target/release/btcupdown-engine /usr/local/bin/btcupdown-engine
COPY --from=builder /app/src/target/release/btcupdown-cli /usr/local/bin/btcupdown-cli
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /data
VOLUME ["/data"]
EXPOSE 8080 8081

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
