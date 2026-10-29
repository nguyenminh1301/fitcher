"""Run one explicit OpenAI connectivity check; never run as a health probe."""

import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from openai import APIStatusError, OpenAI, OpenAIError


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", encoding="utf-8-sig")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("Set OPENAI_API_KEY in the root .env or environment first.", file=sys.stderr)
        return 1
    model = os.getenv("OPENAI_SMOKE_MODEL") or os.getenv("OPENAI_SUMMARY_MODEL") or "gpt-6-luna"
    try:
        with OpenAI(api_key=api_key, timeout=30.0, max_retries=0) as client:
            response = client.responses.create(
                model=model,
                input="Reply with the word OK.",
                max_output_tokens=128,
                store=False,
            )
        if response.status != "completed" or not response.output_text.strip():
            print("OpenAI returned no completed response with usable text.", file=sys.stderr)
            return 1
    except APIStatusError as error:
        print(
            f"OpenAI request failed (HTTP {error.status_code}). "
            "Check the API key, project quota and OPENAI_SMOKE_MODEL access.",
            file=sys.stderr,
        )
        return 1
    except OpenAIError as error:
        print(f"OpenAI request failed ({type(error).__name__}). Check connectivity.", file=sys.stderr)
        return 1
    print(f"OpenAI Responses API check succeeded (model: {model}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
