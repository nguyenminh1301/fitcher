# One-off image for jobs/fetch_guard_model.py: PyTorch and Transformers export
# the gated classifier to ONNX. The api image runs the export with ONNX
# Runtime only, so none of these packages reach it. Versions are pinned; the
# CPU wheel index keeps CUDA libraries out.
FROM python:3.13.18-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_DISABLE_TELEMETRY=1

RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.15.0 \
    && pip install \
        transformers==5.22.1 \
        huggingface-hub==2.4.0 \
        tokenizers==0.23.3 \
        onnx==1.23.2 \
        onnxruntime==1.31.1 \
        numpy==2.5.4

WORKDIR /app
# The api's classifier checks the export exactly as the api will run it.
COPY apps/api/app/screening ./app/screening
COPY jobs/fetch_guard_model.py ./jobs/fetch_guard_model.py

# The guard_models volume is mounted here; Docker copies this directory's owner into a new volume.
RUN useradd --create-home --uid 10001 app && mkdir -p /models/guard && chown app /models/guard
USER app
ENV GUARD_MODEL_DIR=/models/guard \
    HF_HOME=/tmp/huggingface
CMD ["python", "-m", "jobs.fetch_guard_model"]
