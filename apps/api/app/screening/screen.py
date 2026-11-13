"""Screen one untrusted text before any LLM sees it (DECISIONS §9, Layer 0).

``Screener.screen(text, source)`` runs the EN/VI rules and the classifier and
returns a ``Verdict``: ``block`` on a rule hit or a score at or above
``block_at``, ``flag`` at or above ``flag_at``, otherwise ``allow``. The
classifier is optional: while it is turned off (``enabled`` is false) the
rules decide alone, ``block`` on a hit and ``allow`` otherwise, and the
screener's state is ``disabled``. When it is turned on and its model cannot
run, every verdict is ``unavailable``, rule hits included, so the caller fails
closed. What a verdict stops depends on the caller and on
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
ScreenerState = Literal["disabled", "ready", "unavailable"]
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
        enabled: Callable[[], bool] = lambda: True,
    ):
        """``enabled`` tells, on every screen, whether the classifier is turned on."""
        self._classifier = classifier
        self._enabled = enabled
        self.thresholds = thresholds
        self._loader = loader
        self._clock = clock
        self._tried = clock()
        self._lock = threading.Lock()

    @classmethod
    def from_model_dir(cls, model_dir: Path, thresholds: Thresholds = Thresholds(),
                       enabled: Callable[[], bool] = lambda: True) -> "Screener":
        """A screener whose model loads only once the classifier is turned on."""
        return cls(None, thresholds, loader=lambda: load_classifier(model_dir), clock=time.monotonic,
                   enabled=enabled).load_now()

    @classmethod
    def from_settings(cls, settings, enabled: Callable[[], bool] | None = None) -> "Screener":
        """The screener of ``app.config.Settings`` and of the app state's ``screening.classifier_enabled``."""
        return cls.from_model_dir(
            Path(settings.guard_model_dir), Thresholds(settings.screen_flag_at, settings.screen_block_at),
            enabled or classifier_enabled,
        )

    def load_now(self) -> "Screener":
        """Load the model now when the classifier is on, instead of at the next screen."""
        if self._enabled() and self._loader is not None:
            self._tried = self._clock()
            self._classifier = self._loader()
        return self

    @property
    def state(self) -> ScreenerState:
        if not self._enabled():
            return "disabled"
        return "ready" if self.classifier is not None else "unavailable"

    @property
    def classifier(self) -> Classifier | None:
        if self._classifier is None and self._loader is not None:
            with self._lock:
                if self._classifier is None and self._clock() - self._tried >= RELOAD_SECONDS:
                    self._tried = self._clock()
                    self._classifier = self._loader()
        return self._classifier

    @property
    def disabled(self) -> bool:
        """Whether the classifier is turned off; never loads it."""
        return not self._enabled()

    @property
    def loaded(self) -> Classifier | None:
        """The classifier if it is loaded, without trying to load it."""
        return self._classifier

    @property
    def version(self) -> str:
        classifier = self.classifier if self._enabled() else None
        return f"{RULES_VERSION}+{classifier.version}" if classifier else RULES_VERSION

    def screen(self, text: str, source: Source) -> Verdict:
        return self.screen_many([text], source)[0]

    def screen_many(self, texts: Sequence[str], source: Source) -> list[Verdict]:
        """One verdict per text; the classifier scores them in batches."""
        hits = [match(text) for text in texts]
        if not self._enabled():
            return [Verdict(verdict="block" if found else "allow", score=None, rule_hits=found,
                            model_version=RULES_VERSION) for found in hits]
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


def classifier_enabled() -> bool:
    """``screening.classifier_enabled`` of the shared app state; off when it cannot be read."""
    from app.state.db import shared_state  # noqa: PLC0415 - the screener module stays free of the state at import
    from app.state.settings import Settings  # noqa: PLC0415

    try:
        return bool(Settings(shared_state()).get("screening", "classifier_enabled"))
    except Exception:  # noqa: BLE001 - an unreadable app state leaves screening to the rules
        return False


def stops_run(verdict: Verdict, mode: ScreenMode) -> bool:
    """Whether a question with ``verdict`` ends its run: always without a classifier, on a block when enforcing."""
    return verdict.verdict == "unavailable" or (verdict.verdict == "block" and mode == "enforce")
