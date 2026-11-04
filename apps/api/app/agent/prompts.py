"""Versioned prompt templates under ``apps/api/prompts`` (DECISIONS §9, §13).

Templates use ``$name`` placeholders so JSON braces in them need no escaping.
A line ``<!-- user -->`` splits a template: the instructions above it become
the ``system`` message and the untrusted content below it (question, history,
definitions, rows) the ``user`` message.
"""

from functools import cache
from pathlib import Path
from string import Template

from app.llm.client import Prompt

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
USER_MARK = "<!-- user -->"


@cache
def _templates(name: str) -> tuple[Template, Template]:
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    system, mark, user = text.partition(f"\n{USER_MARK}\n")
    if not mark:
        raise ValueError(f"prompt {name} has no {USER_MARK} line between its instructions and its content")
    return Template(system), Template(user)


def render(name: str, **values: str) -> Prompt:
    """Fill prompt ``name`` (for example ``extract.v4``); a missing value raises KeyError."""
    system, user = _templates(name)
    return Prompt(system=system.substitute(values), user=user.substitute(values))
