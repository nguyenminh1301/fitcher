from fastapi import FastAPI

from app.api import auth

app = FastAPI(title="fitcher API", version="0.1.0")
app.include_router(auth.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
