from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import admin, ask, auth, conversations, datasets, documents, evaluation, feedback, feedback_review, oidc, providers, review, runtime, screening, session, setup, sources, users
from app.auth.origin import HostOriginGuard
from app.llm.clients import bootstrap
from app.state.db import shared_state


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Loading the screening classifier takes seconds; questions wait for it, /health does not.
    shared_state()
    bootstrap()
    runtime.build_screener_in_background()
    runtime.start_source_scheduler()
    yield
    runtime.close()


app = FastAPI(title="fitcher API", version="0.1.0", lifespan=lifespan)
app.add_middleware(HostOriginGuard)
app.include_router(auth.router)
app.include_router(session.router)
app.include_router(oidc.router)
app.include_router(ask.router)
app.include_router(conversations.router)
app.include_router(feedback.router)
app.include_router(documents.router)
app.include_router(review.router)
app.include_router(datasets.router)
app.include_router(admin.router)
app.include_router(feedback_review.router)
app.include_router(evaluation.router)
app.include_router(users.router)
app.include_router(setup.router)
app.include_router(providers.router)
app.include_router(screening.router)
app.include_router(sources.router)


@app.get("/health")
def health() -> dict[str, str | None]:
    """Liveness, with whether questions can be screened (DECISIONS §9): ``rules_only`` while the classifier is off.

    It never loads the classifier: until the screener is built, and whenever the model is missing, it
    reports ``screening: unavailable`` and stays healthy, so Compose and CI never depend on the gated model.
    """
    screener = runtime.loaded_screener()
    if screener is not None and screener.disabled:
        return {"status": "ok", "screening": "rules_only", "classifier": None}
    classifier = screener.loaded if screener else None
    return {
        "status": "ok", "screening": "ready" if classifier else "unavailable",
        "classifier": classifier.version if classifier else None,
    }
