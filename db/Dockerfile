FROM pgvector/pgvector:0.8.7-pg17-bookworm

RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /usr/local/bin/gosu

# Named volumes inherit the base image's postgres-owned data directory.
# Starting as postgres makes the root-only gosu handoff unnecessary.
USER postgres
