"""LiteLLM ``pre_call`` guardrail that rejects requests the api did not screen (DECISIONS §9, Layer 0).

Every request must carry ``screening`` metadata from the api: ``allow`` or
``flag`` for a run whose question the ``screen`` node let through, or
``trusted_pack`` for calls on reviewed pack content outside a run. A request
without it, or with any other value, is rejected. The EN/VI rules then run
again on every message, and on every embedding input, as a safety net for
content added after the question was screened, such as history or result
rows. This closes code paths that forgot to screen; it is not an
authentication boundary.

The rules come from ``screening_rules.py``, a byte-identical copy of
``apps/api/app/screening/rules.py`` mounted next to this file, because the
LiteLLM image does not import ``apps/api``. The ``template_tag`` rule is
skipped: the api's own prompts put untrusted content between such tags.

A rejection is an HTTP 400 whose error starts with ``screening_guard:``; the
api maps it to the ``blocked`` reply. The reason names the failed check and
the rule ids, never the text that tripped them.

``infra/litellm/config.yaml`` registers ``ScreeningGuard`` as a default-on
``pre_call`` guardrail.
"""

from collections.abc import Iterator
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import screening_rules  # noqa: E402 - the mounted copy next to this file

try:
    from fastapi import HTTPException
    from litellm.integrations.custom_guardrail import CustomGuardrail
except ImportError:  # unit tests load this file without litellm installed
    CustomGuardrail = object

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

MARKER = "screening_guard"
SCREENED = frozenset({"allow", "flag", "trusted_pack"})
METADATA_KEYS = ("metadata", "litellm_metadata")


def screening_of(data: dict) -> str | None:
    """The request's ``screening`` metadata, wherever the proxy placed the caller's metadata."""
    for key in METADATA_KEYS:
        metadata = data.get(key)
        if not isinstance(metadata, dict):
            continue
        for holder in (metadata.get("requester_metadata"), metadata):
            if isinstance(holder, dict) and isinstance(holder.get("screening"), str):
                return holder["screening"]
    return None


def _texts(value) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                yield item
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                yield item["text"]


def texts_of(data: dict) -> Iterator[str]:
    """Every text the request sends to a model: message contents, embedding inputs and prompts."""
    for message in data.get("messages") or []:
        if isinstance(message, dict):
            yield from _texts(message.get("content"))
    yield from _texts(data.get("input"))
    yield from _texts(data.get("prompt"))


def rejection(data: dict) -> str | None:
    """Why the request is rejected, or None when it may pass."""
    screening = screening_of(data)
    if screening is None:
        return "the request carries no screening metadata"
    if screening not in SCREENED:
        return f"unknown screening value {screening[:40]!r}"
    hits = sorted({hit for text in texts_of(data) for hit in screening_rules.match(text, screening_rules.GATEWAY_SKIPPED)})
    if hits:
        return f"the request trips screening rules {', '.join(hits)}"
    return None


class ScreeningGuard(CustomGuardrail):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        reason = rejection(data)
        if reason is not None:
            raise HTTPException(status_code=400, detail={"error": f"{MARKER}: {reason}"})
        return data
