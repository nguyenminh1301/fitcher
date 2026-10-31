"""Versioned prompt templates under ``apps/api/prompts`` (DECISIONS §13).

Templates use ``$name`` placeholders so JSON braces in them need no escaping.
"""

from functools import cache
from pathlib import Path
from string import Template

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


@cache
def _template(name: str) -> Template:
    return Template((PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8"))


def render(name: str, **values: str) -> str:
    """Fill prompt ``name`` (for example ``extract.v1``); a missing value raises KeyError."""
    return _template(name).substitute(values)
