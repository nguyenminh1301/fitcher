"""The prompt-injection classifier run by a model provider (DECISIONS §9, Layer 0).

Groq hosts Llama Prompt Guard 2 (``meta-llama/llama-prompt-guard-2-86m``) as a
chat model whose reply is the malicious probability as a number, such as
``0.9995``. A text longer than one window is split into overlapping windows of
``WINDOW_CHARS`` characters, at most ``MAX_WINDOWS`` of them, and its score is
the highest window's. A reply that is not a number from 0 to 1, or a failed
call, raises ``ClassifierError``: the screener then fails closed.
"""

from collections.abc import Callable, Sequence

from app.llm.call_log import CallLog
from app.llm.client import LLMError
from app.llm.gateway import classifier_reply, Route

DEFAULT_MODEL = "meta-llama/llama-prompt-guard-2-86m"
# About 512 tokens of the model's window for English and Vietnamese text.
WINDOW_CHARS = 1500
OVERLAP_CHARS = 200
MAX_WINDOWS = 8


class ClassifierError(RuntimeError):
    """The provider did not score the text; the message names the model and the reason only."""


def text_windows(text: str, size: int = WINDOW_CHARS, overlap: int = OVERLAP_CHARS, limit: int = MAX_WINDOWS) -> list[str]:
    """Overlapping slices of ``text``, at most ``limit``; one slice for a short or empty text."""
    if len(text) <= size:
        return [text]
    step = size - overlap
    return [text[start:start + size] for start in range(0, len(text) - overlap, step)][:limit]


def parse_score(reply: str) -> float:
    try:
        score = float(reply.strip())
    except ValueError:
        raise ClassifierError("the classifier replied with something other than a score") from None
    if not 0.0 <= score <= 1.0:
        raise ClassifierError("the classifier replied with a score outside 0 to 1")
    return score


class ProviderClassifier:
    def __init__(self, route: Route, *, call_log: CallLog | None = None,
                 reply: Callable[..., str] = classifier_reply):
        self._route = route
        self._call_log = call_log
        self._reply = reply
        self.version = f"{route.provider}/{route.model.split('/', 1)[-1]}"

    def scores(self, texts: Sequence[str]) -> list[float]:
        return [max(self._score(window) for window in text_windows(text)) for text in texts]

    def _score(self, window: str) -> float:
        try:
            return parse_score(self._reply(self._route, window, call_log=self._call_log))
        except LLMError as error:
            raise ClassifierError(str(error)) from None
