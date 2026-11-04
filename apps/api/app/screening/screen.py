"""Screen one untrusted text before any LLM sees it (DECISIONS §9, Layer 0).

``Screener.screen(text, source)`` runs the EN/VI rules and the classifier and
returns a ``Verdict``: ``block`` on a rule hit or a score at or above
``block_at``, ``flag`` at or above ``flag_at``, otherwise ``allow``. Without a
classifier every verdict is ``unavailable``, rule hits included, so the
caller fails closed. What a verdict stops depends on the caller and on
``SCREEN_MODE``: the graph's ``screen`` node, the compiler and the
measurement job each decide.

A screener without its model tries to load it again at most once every
``RELOAD_SECONDS``, so the api picks up a model fetched after it started.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import threading
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.screening.classifier import Classifier, load_classifier
from app.screening.rules import RULES_VERSION, match

VerdictName = Literal["allow", "flag", "block", "unavailable"]
Source = Literal["question", "document", "column_value"]
ScreenMode = Literal["log", "enforce"]
RELOAD_SECONDS = 30.0


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: VerdictName
    # The classifier's highest malicious probability; None without a classifier.
    score: float | None
    rule_hits: list[str]
    # The rules version and, when loaded, the classifier version.
    model_version: str


@dataclass(frozen=True)
class Thresholds:
    flag_at: float = 0.5
    block_at: float = 0.9


class Screener:
    def __init__(
        self, classifier: Classifier | None, thresholds: Thresholds = Thresholds(), *,
        loader: Callable[[], Classifier | None] | None = None, clock: Callable[[], float] = time.monotonic,
    ):
        self._classifier = classifier
        self.thresholds = thresholds
        self._loader = loader
        self._clock = clock
        self._tried = clock()
        self._lock = threading.Lock()

    @classmethod
    def from_model_dir(cls, model_dir: Path, thresholds: Thresholds = Thresholds()) -> "Screener":
        return cls(load_classifier(model_dir), thresholds, loader=lambda: load_classifier(model_dir))

    @classmethod
    def from_settings(cls, settings) -> "Screener":
        """The screener of ``app.config.Settings``: its model directory and thresholds."""
        return cls.from_model_dir(
            Path(settings.guard_model_dir), Thresholds(settings.screen_flag_at, settings.screen_block_at),
        )

    @property
    def classifier(self) -> Classifier | None:
        if self._classifier is None and self._loader is not None:
            with self._lock:
                if self._classifier is None and self._clock() - self._tried >= RELOAD_SECONDS:
                    self._tried = self._clock()
                    self._classifier = self._loader()
        return self._classifier

    @property
    def version(self) -> str:
        classifier = self.classifier
        return f"{RULES_VERSION}+{classifier.version}" if classifier else RULES_VERSION

    def screen(self, text: str, source: Source) -> Verdict:
        return self.screen_many([text], source)[0]

    def screen_many(self, texts: Sequence[str], source: Source) -> list[Verdict]:
        """One verdict per text; the classifier scores them in batches."""
        hits = [match(text) for text in texts]
        classifier = self.classifier
        if classifier is None:
            return [Verdict(verdict="unavailable", score=None, rule_hits=found, model_version=RULES_VERSION) for found in hits]
        scores = classifier.scores(list(texts)) if texts else []
        version = f"{RULES_VERSION}+{classifier.version}"
        return [
            Verdict(verdict=self._verdict(score, found), score=round(score, 6), rule_hits=found, model_version=version)
            for score, found in zip(scores, hits, strict=True)
        ]

    def _verdict(self, score: float, rule_hits: list[str]) -> VerdictName:
        if rule_hits or score >= self.thresholds.block_at:
            return "block"
        return "flag" if score >= self.thresholds.flag_at else "allow"


def stops_run(verdict: Verdict, mode: ScreenMode) -> bool:
    """Whether a question with ``verdict`` ends its run: always without a classifier, on a block when enforcing."""
    return verdict.verdict == "unavailable" or (verdict.verdict == "block" and mode == "enforce")
