#!/usr/bin/env bash
# Image scan gate shared by the Security and Release workflows (SECURITY.md, Image exceptions).
#
#   scripts/scan_image.sh <image> [<ignore file>]
#
# Installs the checksum-verified Trivy release, saves every advisory of the image to
# $REPORT (image-report.json), then fails on a fixable High or Critical finding that the
# optional ignore file of that image does not list. Exceptions in the file expire.
set -euo pipefail

image="${1:?usage: scripts/scan_image.sh <image> [<ignore file>]}"
ignore_file="${2:-}"
report="${REPORT:-image-report.json}"
TRIVY_VERSION="0.76.1"
TRIVY_SHA256="c7cbe3137fb8a48a17574bede3dd6beb16742d1e9772929940fc90082c39d9c0"

work="${RUNNER_TEMP:-$(mktemp -d)}"
trivy="$work/trivy"
if [ ! -x "$trivy" ]; then
    curl --fail --silent --show-error --location --retry 3 \
        "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" \
        --output "$work/trivy.tar.gz"
    echo "$TRIVY_SHA256  $work/trivy.tar.gz" | sha256sum --check --quiet
    tar -xzf "$work/trivy.tar.gz" -C "$work" trivy
fi

"$trivy" image --image-src docker --scanners vuln --format json --output "$report" "$image"

ignore=()
if [ -n "$ignore_file" ] && [ -f "$ignore_file" ]; then
    ignore=(--ignorefile "$ignore_file")
fi
"$trivy" image --image-src docker --scanners vuln \
    --ignore-unfixed --severity HIGH,CRITICAL --exit-code 1 "${ignore[@]}" "$image"
