from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import admin, ask, auth, conversations, datasets, documents, evaluation, feedback, feedback_review, models, review, runtime, setup, users
from app.state.db import shared_state


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Loading the screening classifier takes seconds; questions wait for it, /health does not.
    shared_state()
    runtime.build_screener_in_background()
    yield
    runtime.close()


app = FastAPI(title="fitcher API", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(ask.router)
app.include_router(conversations.router)
app.include_router(feedback.router)
app.include_router(models.router)
app.include_router(documents.router)
app.include_router(review.router)
app.include_router(datasets.router)
app.include_router(admin.router)
app.include_router(feedback_review.router)
app.include_router(evaluation.router)
app.include_router(users.router)
app.include_router(setup.router)


@app.get("/health")
def health() -> dict[str, str | None]:
    """Liveness, with whether questions can be screened (DECISIONS §9).

    It never loads the classifier: until the screener is built, and whenever the model is missing, it
    reports ``screening: unavailable`` and stays healthy, so Compose and CI never depend on the gated model.
    """
    screener = runtime.loaded_screener()
    classifier = screener.loaded if screener else None
    return {
        "status": "ok", "screening": "ready" if classifier else "unavailable",
        "classifier": classifier.version if classifier else None,
    }
