"""Send one tiny billable request to every alias the LiteLLM gateway loaded.

Run it explicitly with ``make smoke`` or
``docker compose exec -T api python -m jobs.smoke_llm``; ``--alias`` limits it
to the named aliases. It never runs from tests or health checks. A chat alias
must answer a request for JSON matching a small schema, the structured output
every engine node relies on; an ``-embed`` alias must return one vector. The
reply is not printed, only whether it passed (DECISIONS §2 Model tiers). The
fixed prompt is engine text, so it carries the ``trusted_pack`` screening
metadata the gateway guardrail requires (DECISIONS §9).
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 60
SCREENING = {"screening": "trusted_pack"}
SCHEMA = {
    "type": "object",
    "properties": {"word": {"type": "string"}, "count": {"type": "integer"}},
    "required": ["word", "count"],
    "additionalProperties": False,
}


class SmokeError(Exception):
    """The alias did not give a usable reply; the message never holds the reply or a key."""


def _post(base_url: str, master_key: str, path: str, payload: dict | None = None) -> dict:
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {master_key}", "Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise SmokeError(f"HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise SmokeError(type(error).__name__) from None


def check_chat(base_url: str, master_key: str, alias: str) -> None:
    body = _post(base_url, master_key, "/v1/chat/completions", {
        "model": alias,
        "messages": [{"role": "user", "content": 'Reply with JSON: the word "ready" and the count 2.'}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "Smoke", "schema": SCHEMA}},
        "metadata": SCREENING,
    })
    content = ((body.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    try:
        reply = json.loads(content)
    except json.JSONDecodeError:
        raise SmokeError("the reply is not JSON") from None
    if not isinstance(reply, dict) or not isinstance(reply.get("word"), str) or not isinstance(reply.get("count"), int):
        raise SmokeError("the reply does not match the schema")


def check_embedding(base_url: str, master_key: str, alias: str) -> None:
    body = _post(base_url, master_key, "/v1/embeddings", {"model": alias, "input": ["ready"], "metadata": SCREENING})
    data = body.get("data") or []
    if len(data) != 1 or not data[0].get("embedding"):
        raise SmokeError("no vector returned")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--alias", action="append", default=[], help="check only this alias; repeat for several")
    args = parser.parse_args(argv)
    base_url = os.environ.get("LITELLM_BASE_URL", "").rstrip("/")
    master_key = os.environ.get("LITELLM_MASTER_KEY", "")
    if not base_url or not master_key:
        print("LITELLM_BASE_URL and LITELLM_MASTER_KEY must be set", file=sys.stderr)
        return 1
    try:
        loaded = sorted({str(item["id"]) for item in _post(base_url, master_key, "/v1/models").get("data", [])})
    except (SmokeError, KeyError, TypeError, AttributeError) as error:
        print(f"LiteLLM did not list its aliases: {error}", file=sys.stderr)
        return 1
    missing = [alias for alias in args.alias if alias not in loaded]
    if missing:
        print(f"The gateway has not loaded {', '.join(missing)}; is its provider key set?", file=sys.stderr)
        return 1
    aliases = args.alias or loaded
    if not aliases:
        print("The gateway loaded no alias; set a provider key in .env", file=sys.stderr)
        return 1
    failed = 0
    for alias in aliases:
        check = check_embedding if alias.endswith("-embed") else check_chat
        try:
            check(base_url, master_key, alias)
        except SmokeError as error:
            failed += 1
            print(f"{alias}: FAIL ({error})", file=sys.stderr)
            continue
        print(f"{alias}: ok")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
