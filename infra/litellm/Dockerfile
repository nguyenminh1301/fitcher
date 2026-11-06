# The LiteLLM gateway image with patched Python packages its upstream image still bundles at a
# vulnerable version. The upstream image has no pip, so a builder stage installs each pinned,
# pure-Python replacement and the final stage swaps it into the image's virtual environment.
# Drop a replacement once the pinned upstream tag ships the fixed version (check SECURITY.md).

FROM python:3.13-slim AS patches
# oauthlib 4.0.1 fixes CVE-2026-49272; upstream v1.106.7 and v1.108.1 ship 4.0.0.
RUN pip install --no-deps --no-compile --target /patches oauthlib==4.0.1

FROM ghcr.io/berriai/litellm:v1.106.7
RUN rm -rf /app/.venv/lib/python3.13/site-packages/oauthlib \
    /app/.venv/lib/python3.13/site-packages/oauthlib-4.0.0.dist-info
COPY --from=patches /patches/ /app/.venv/lib/python3.13/site-packages/
