from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import ask, auth, conversations, runtime


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    runtime.close()


app = FastAPI(title="fitcher API", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(ask.router)
app.include_router(conversations.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
