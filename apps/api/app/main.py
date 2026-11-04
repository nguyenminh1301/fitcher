from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import logging

from app.api import ask, auth, conversations, feedback, runtime


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    runtime.close()


app = FastAPI(title="fitcher API", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(ask.router)
app.include_router(conversations.router)
app.include_router(feedback.router)


logger = logging.getLogger(__name__)


@app.get("/health")
def health() -> dict[str, str | None]:
    """Liveness, with whether questions can be screened; the gated classifier never makes it fail (DECISIONS §9)."""
    try:
        classifier = runtime.get_screener().classifier
    except Exception:  # noqa: BLE001 - invalid screening settings leave screening unavailable, not the api down
        logger.exception("cannot build the question screener")
        classifier = None
    return {
        "status": "ok", "screening": "ready" if classifier else "unavailable",
        "classifier": classifier.version if classifier else None,
    }
