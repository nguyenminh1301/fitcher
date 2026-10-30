"""Send one billable chat request to the ``fast`` alias through LiteLLM.

Run it explicitly with ``make smoke`` or
``docker compose exec -T api python -m jobs.smoke_llm``. It never runs from
tests or health checks. The reply text is not printed; only its length is.
"""

import json
import os
import sys
import urllib.error
import urllib.request

ALIAS = "fast"
TIMEOUT_SECONDS = 60


def main() -> int:
    base_url = os.environ.get("LITELLM_BASE_URL", "").rstrip("/")
    master_key = os.environ.get("LITELLM_MASTER_KEY", "")
    if not base_url or not master_key:
        print("LITELLM_BASE_URL and LITELLM_MASTER_KEY must be set", file=sys.stderr)
        return 1

    payload = {
        "model": ALIAS,
        "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
    }
    request = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {master_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        print(f"LiteLLM returned HTTP {error.code} for alias {ALIAS}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        print(f"LiteLLM request for alias {ALIAS} failed: {type(error).__name__}", file=sys.stderr)
        return 1

    choices = body.get("choices") or [{}]
    content = (choices[0].get("message") or {}).get("content") or ""
    if not content.strip():
        print(f"Alias {ALIAS} returned an empty reply", file=sys.stderr)
        return 1

    print(f"Alias {ALIAS} replied with {len(content)} characters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
