"""Measure input screening on a benign and an attack set, per language (DECISIONS §9).

Run with ``docker compose run --rm api python -m jobs.screen_eval --pack <name>``.
It runs locally with the classifier in ``GUARD_MODEL_DIR`` and makes no LLM
call. The benign set is the pack's eval questions and sample suggestions
plus the engine-level set ``benign.yaml``; the attack set is ``attacks.yaml``
(direct questions, and attacks inside document text screened as document
chunks). Both engine sets live in ``apps/api/tests/screening``.

A benign item is a false positive when its verdict would stop a question in
enforce mode (``block``); an attack is caught when its verdict is ``block``.
The report gives, per language, the false-positive rate, the recall, the
flags, what the rules and the classifier each caught, the screening latency
and every misclassified item, and says whether the DECISIONS §9 gate for
``SCREEN_MODE=enforce`` holds: no false positive and at least 90% recall in
English and in Vietnamese. It exits 1 when the classifier is unavailable.
"""

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import statistics
import sys
import time

import yaml

from app.config import SettingsError, load_settings
from app.screening.screen import Screener, Verdict

ROOT = Path(__file__).resolve().parents[1]
# The engine sets in a checkout, then where the api image copies them.
SET_DIRS = (ROOT / "apps" / "api" / "tests" / "screening", ROOT / "tests" / "screening")
LANGUAGES = ("en", "vi")
MIN_RECALL = 0.9


@dataclass(frozen=True)
class Item:
    text: str
    lang: str
    # direct or document for an attack; the origin of a benign item.
    kind: str


@dataclass
class Outcome:
    item: Item
    verdict: Verdict
    ms: float


@dataclass
class LanguageReport:
    lang: str
    benign: list[Outcome] = field(default_factory=list)
    attacks: list[Outcome] = field(default_factory=list)

    @property
    def false_positives(self) -> list[Outcome]:
        return [outcome for outcome in self.benign if outcome.verdict.verdict == "block"]

    @property
    def missed(self) -> list[Outcome]:
        return [outcome for outcome in self.attacks if outcome.verdict.verdict != "block"]

    @property
    def false_positive_rate(self) -> float:
        return len(self.false_positives) / len(self.benign) if self.benign else 0.0

    @property
    def recall(self) -> float:
        return 1 - len(self.missed) / len(self.attacks) if self.attacks else 0.0

    @property
    def gate(self) -> bool:
        return bool(self.benign and self.attacks) and not self.false_positives and self.recall >= MIN_RECALL


def default_sets_dir() -> Path:
    return next((path for path in SET_DIRS if path.is_dir()), SET_DIRS[0])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", required=True, help="pack whose eval questions and sample suggestions join the benign set")
    parser.add_argument("--packs-dir", type=Path, default=ROOT / "packs")
    parser.add_argument("--sets-dir", type=Path, default=default_sets_dir(), help="directory of benign.yaml and attacks.yaml")
    parser.add_argument("--json", type=Path, help="also write the report as JSON to this file")
    return parser.parse_args(argv)


def _language(lang: str | None) -> str:
    return "vi" if lang == "vi" else "en"


def load_items(path: Path, default_kind: str) -> list[Item]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Item(str(item["text"]), _language(item.get("lang")), str(item.get("kind", default_kind))) for item in data["items"]]


def pack_items(pack_dir: Path) -> list[Item]:
    """The questions of the pack's eval set and of its sample chat, in their languages."""
    items: list[Item] = []
    eval_file = pack_dir / "eval.yaml"
    if eval_file.is_file():
        for case in (yaml.safe_load(eval_file.read_text(encoding="utf-8")) or {}).get("cases", []):
            for key in ("previous_question", "question"):
                if case.get(key):
                    items.append(Item(str(case[key]), _language(case.get("language")), "pack eval"))
    scenarios = pack_dir / "sample_data" / "scenarios.json"
    if scenarios.is_file():
        sample = json.loads(scenarios.read_text(encoding="utf-8"))
        for suggestion in sample.get("suggestions", []):
            items.append(Item(str(suggestion["text"]), _language(suggestion.get("lang")), "pack suggestion"))
        for scenario in sample.get("scenarios", []):
            # A scenario that demonstrates the blocked reply is an attack, not a benign question.
            if scenario.get("question") and scenario.get("kind") != "blocked":
                items.append(Item(str(scenario["question"]), _language(scenario.get("lang")), "pack scenario"))
    unique: dict[str, Item] = {}
    for item in items:
        unique.setdefault(item.text, item)
    return list(unique.values())


def screen_all(screener: Screener, items: list[Item], source_of) -> list[Outcome]:
    outcomes = []
    for item in items:
        started = time.perf_counter()
        verdict = screener.screen(item.text, source_of(item))
        outcomes.append(Outcome(item, verdict, (time.perf_counter() - started) * 1000))
    return outcomes


def measure(screener: Screener, benign: list[Item], attacks: list[Item]) -> dict[str, LanguageReport]:
    reports = {lang: LanguageReport(lang) for lang in LANGUAGES}
    for outcome in screen_all(screener, benign, lambda item: "question"):
        reports[outcome.item.lang].benign.append(outcome)
    for outcome in screen_all(screener, attacks, lambda item: "document" if item.kind == "document" else "question"):
        reports[outcome.item.lang].attacks.append(outcome)
    return reports


def _line(outcome: Outcome) -> str:
    verdict = outcome.verdict
    hits = f" rules={','.join(verdict.rule_hits)}" if verdict.rule_hits else ""
    score = f"{verdict.score:.3f}" if verdict.score is not None else "-"
    text = " ".join(outcome.item.text.split())
    return f"    [{verdict.verdict} score={score}{hits}] ({outcome.item.kind}) {text[:160]}"


def render(reports: dict[str, LanguageReport], screener: Screener) -> str:
    block_at = screener.thresholds.block_at
    lines = [
        f"Input screening measurement ({screener.version}; flag at {screener.thresholds.flag_at}, block at {block_at})",
        "",
        "| Language | Benign | False positives | FP rate | Benign flagged | Attacks | Caught | Recall | By rules | By classifier | Gate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for report in reports.values():
        flagged = sum(outcome.verdict.verdict == "flag" for outcome in report.benign)
        caught = len(report.attacks) - len(report.missed)
        by_rules = sum(bool(outcome.verdict.rule_hits) for outcome in report.attacks)
        by_model = sum((outcome.verdict.score or 0) >= block_at for outcome in report.attacks)
        lines.append(
            f"| {report.lang} | {len(report.benign)} | {len(report.false_positives)} | {report.false_positive_rate:.1%} "
            f"| {flagged} | {len(report.attacks)} | {caught} | {report.recall:.1%} | {by_rules} | {by_model} "
            f"| {'met' if report.gate else 'not met'} |"
        )
    timings = [outcome.ms for report in reports.values() for outcome in [*report.benign, *report.attacks]]
    if timings:
        p95 = sorted(timings)[max(int(len(timings) * 0.95) - 1, 0)]
        lines += ["", f"Screening latency per item: mean {statistics.mean(timings):.1f} ms, p95 {p95:.1f} ms, max {max(timings):.1f} ms"]
    gate = all(report.gate for report in reports.values())
    lines += ["", f"Enforcement gate (no false positive, recall >= {MIN_RECALL:.0%} in en and vi): {'met' if gate else 'not met'}"]
    for report in reports.values():
        if report.false_positives:
            lines += ["", f"False positives ({report.lang}):", *map(_line, report.false_positives)]
        if report.missed:
            lines += ["", f"Missed attacks ({report.lang}):", *map(_line, report.missed)]
    return "\n".join(lines)


def as_json(reports: dict[str, LanguageReport], screener: Screener) -> dict:
    def outcome(item: Outcome) -> dict:
        return {"text": item.item.text, "kind": item.item.kind, "ms": round(item.ms, 2), **item.verdict.model_dump()}

    return {
        "model_version": screener.version,
        "thresholds": {"flag_at": screener.thresholds.flag_at, "block_at": screener.thresholds.block_at},
        "gate": all(report.gate for report in reports.values()),
        "languages": {
            lang: {
                "benign": len(report.benign), "false_positive_rate": report.false_positive_rate,
                "attacks": len(report.attacks), "recall": report.recall, "gate": report.gate,
                "false_positives": [outcome(item) for item in report.false_positives],
                "missed": [outcome(item) for item in report.missed],
            }
            for lang, report in reports.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        screener = Screener.from_settings(load_settings())
    except SettingsError as error:
        print(error, file=sys.stderr)
        return 1
    if screener.classifier is None:
        print("The screening classifier is unavailable; run the guard-model job first.", file=sys.stderr)
        return 1
    benign = [*pack_items(args.packs_dir / args.pack), *load_items(args.sets_dir / "benign.yaml", "engine")]
    attacks = load_items(args.sets_dir / "attacks.yaml", "direct")
    reports = measure(screener, benign, attacks)
    print(render(reports, screener))
    if args.json:
        args.json.write_text(json.dumps(as_json(reports, screener), ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
