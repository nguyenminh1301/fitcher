from datetime import UTC, datetime

import pytest

from app.feedback.proposals import Proposal, RunFacts, build_proposal, ineligible_reason, normalize, propose
from app.feedback.redaction import redact, redact_spec, redact_sql

NOW = datetime(2026, 11, 6, tzinfo=UTC)
SPEC = {"intent": "data_query", "metric_ids": ["widget_revenue"], "filters": [
    {"column": "customer_email", "op": "=", "value": "ana.lee@example.com"}, {"column": "region", "op": "=", "value": "west"},
]}


def facts(**overrides) -> RunFacts:
    base = dict(trace_id="t1", pack="minimal", question="Revenue for ana.lee@example.com in 2025", status="succeeded",
                intent="data_query", error="", spec=SPEC, sql="SELECT sum(x) FROM t WHERE email = 'ana.lee@example.com'",
                rating="dislike", note="Call me on +84 912 345 678")
    return RunFacts(**{**base, **overrides})


@pytest.mark.parametrize(("text", "expected"), [
    ("mail ana.lee@example.com now", "mail [MASKED_EMAIL] now"),
    ("call +84 912 345 678 or (028) 3822-1234", "call [MASKED_PHONE] or [MASKED_PHONE]"),
    ("order 123456789 and year 2025", "order [MASKED_NUMBER] and year 2025"),
    ("nothing personal", "nothing personal"),
])
def test_redact_masks_emails_phones_and_long_digit_runs(text, expected):
    assert redact(text) == expected


def test_redact_sql_masks_only_personal_string_literals():
    sql = "SELECT 1 FROM t WHERE email = 'a@b.co' AND region = 'west' AND id = '1234567'"
    assert redact_sql(sql) == "SELECT 1 FROM t WHERE email = '[MASKED_EMAIL]' AND region = 'west' AND id = '[MASKED_NUMBER]'"


def test_redact_spec_masks_filter_values():
    assert [f["value"] for f in redact_spec(SPEC)["filters"]] == ["[MASKED_EMAIL]", "west"]


@pytest.mark.parametrize(("overrides", "reason"), [
    ({"intent": "metadata_qa"}, "not a data question"),
    ({"status": "clarified", "rating": None}, "clarified"),
    ({"status": "denied"}, "denied"),
    ({"status": "rejected"}, "rejected"),
    ({"status": "succeeded", "rating": "like"}, "neither disliked nor failed"),
    ({"status": "succeeded", "rating": None}, "neither disliked nor failed"),
    ({"spec": None}, "no QuerySpec"),
    ({"sql": ""}, "no SQL"),
])
def test_ineligible_runs(overrides, reason):
    assert reason in ineligible_reason(facts(**overrides))


def test_failed_and_disliked_runs_are_eligible():
    assert ineligible_reason(facts()) is None
    assert ineligible_reason(facts(status="failed", rating=None, error="Code: 47")) is None


def test_a_proposal_is_redacted_and_keeps_no_rows():
    proposal = build_proposal(facts(status="failed", error="no column ana.lee@example.com"), clock=lambda: NOW,
                              new_id=lambda: "p1")
    assert proposal.question == "Revenue for [MASKED_EMAIL] in 2025"
    assert proposal.sql.endswith("email = '[MASKED_EMAIL]'")
    assert proposal.note == "Call me on [MASKED_PHONE]"
    assert proposal.error == "no column [MASKED_EMAIL]"
    assert '"[MASKED_EMAIL]"' in proposal.spec and "ana.lee" not in proposal.spec
    assert (proposal.source, proposal.status, proposal.proposal_id, proposal.ts) == ("failed", "proposed", "p1", NOW)


def test_normalize_ignores_case_spacing_and_punctuation():
    assert normalize("  Revenue,  in 2025? ") == normalize("revenue in 2025")


class Store:
    def __init__(self, runs, known=()):
        self.runs = runs
        self.known = set(known)
        self.saved: list[Proposal] = []

    def candidates(self, pack, since):
        return self.runs

    def known_questions(self, pack):
        return self.known

    def save(self, proposal):
        self.saved.append(proposal)


def test_propose_skips_ineligible_runs_and_duplicate_questions():
    store = Store([
        facts(trace_id="t1"),
        facts(trace_id="t2", question="revenue for ANA.LEE@example.com in 2025!"),
        facts(trace_id="t3", status="denied"),
        facts(trace_id="t4", question="Already proposed"),
    ], known={normalize("Already proposed")})

    summary = propose(store, "minimal", since=NOW, clock=lambda: NOW)

    assert [proposal.trace_id for proposal in store.saved] == ["t1"]
    assert summary.added == ["t1"] and set(summary.skipped) == {"t2", "t3", "t4"}
