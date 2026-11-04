#!/bin/sh
# Starts the fixture S3-compatible store (SeaweedFS) with one read-only
# identity, then copies the widget CSV files into its bucket through the
# filer, which is reachable only inside the Compose network. The store keeps
# no volume, so every start serves a fresh copy; /tmp/seeded marks the copy done.
set -eu

bucket="$FIXTURE_FILES_DATABASE"
cat > /tmp/s3.json <<EOF
{
  "identities": [
    {
      "name": "reader",
      "credentials": [{"accessKey": "$FIXTURE_FILES_USER", "secretKey": "$FIXTURE_FILES_PASSWORD"}],
      "actions": ["Read:$bucket", "List:$bucket"]
    }
  ]
}
EOF

rm -f /tmp/seeded
mkdir -p /tmp/store
weed server -dir=/tmp/store -master.volumeSizeLimitMB=64 -volume.max=8 \
    -s3 -s3.port=8333 -s3.config=/tmp/s3.json &
server=$!

until wget -q -O /dev/null http://127.0.0.1:8888/; do
    kill -0 "$server" 2>/dev/null || exit 1
    sleep 1
done
weed filer.copy /fixtures/widgets.csv /fixtures/sales.csv /fixtures/refunds.csv "http://127.0.0.1:8888/buckets/$bucket/"
touch /tmp/seeded

wait "$server"
