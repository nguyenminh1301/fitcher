"""Send one tiny billable request to the model of every mapped tier through the gateway.

Run it explicitly with ``make smoke`` or
``docker compose exec -T api python -m jobs.smoke_llm``; ``--tier`` limits it
to the named tiers. It never runs from tests or health checks. Each chat model
mapped to a tier must answer a request for JSON matching a small schema, the
structured output every engine node relies on; the embedding model must return
one vector; a local embedding model is loaded and run instead of called. A
model that serves several tiers is called once. The reply is not
printed, only whether it passed (DECISIONS §2 Model tiers). The fixed prompt is
engine text, so it runs as reviewed pack content for the gateway's screening
(DECISIONS §9).
"""

import argparse
from collections.abc import Callable
import sys

from pydantic import BaseModel, ConfigDict

from app.llm import clients
from app.llm.client import LLMError, Prompt
from app.llm.embeddings import EmbeddingError
from app.llm.gateway import Gateway, GatewayEmbeddings
from app.llm.routes import RouteError
from app.llm.tiers import CHAT_TIERS, EMBED_TIER, TIERS
from app.observability.tracing import trusted_pack_calls

PROMPT = Prompt(system="Reply with JSON only.", user='Reply with JSON: the word "ready" and the count 2.')


class Smoke(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: str
    count: int


def _groups(labels: dict[str, str], tiers: list[str]) -> dict[str, list[str]]:
    """Each mapped model with the tiers it serves, in tier order."""
    groups: dict[str, list[str]] = {}
    for tier in TIERS:
        if tier in labels and (not tiers or tier in tiers):
            groups.setdefault(labels[tier], []).append(tier)
    return groups


def main(argv: list[str] | None = None, *, completion: Callable | None = None, embedding: Callable | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tier", action="append", default=[], choices=TIERS, help="check only this tier; repeat for several")
    args = parser.parse_args(argv)
    clients.bootstrap()
    routes = clients.shared_routes()
    labels = routes.labels()
    if not any(tier in labels for tier in CHAT_TIERS):
        print("No chat model is mapped; add a provider on the Models page or in the setup", file=sys.stderr)
        return 1
    groups = _groups(labels, args.tier)
    embedding_choice = clients.embedding_choice()
    chat = Gateway(routes, completion=completion, retries=0)
    failed = 0
    with trusted_pack_calls():
        for label, tiers in groups.items():
            try:
                if tiers == [EMBED_TIER] and embedding_choice.backend == "local":
                    clients.embedding_client(embedding_choice.dimensions).embed(["ready"])
                elif tiers == [EMBED_TIER]:
                    GatewayEmbeddings(routes, embedding_choice.dimensions, embedding=embedding, retries=0).embed(["ready"])
                else:
                    chat.structured(next(tier for tier in tiers if tier in CHAT_TIERS), PROMPT, Smoke)
            except (LLMError, EmbeddingError, RouteError) as error:
                failed += 1
                print(f"{', '.join(tiers)}: {label} FAIL ({error})", file=sys.stderr)
                continue
            print(f"{', '.join(tiers)}: {label} ok")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
