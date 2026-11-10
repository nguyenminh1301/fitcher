# The Qdrant image with Debian security updates its upstream image does not carry yet.
# zlib1g 1:1.3.dfsg+really1.3.1-1+deb13u1 fixes CVE-2026-76844 and CVE-2026-85091; upstream v1.20.0 ships +b1.
# Drop this file and use the upstream tag again once a Qdrant release ships the fixed package (check SECURITY.md).

FROM qdrant/qdrant:v1.20.0
RUN apt-get update \
    && apt-get install --yes --no-install-recommends --only-upgrade zlib1g \
    && rm -rf /var/lib/apt/lists/*
