"""Tests for the parts that do not call the LLM: the adapter, the rules, dedup, billing, and ingest.

Nothing here touches the network. The ingest client's HTTP call is stubbed.
"""

from datetime import datetime, timezone
from decimal import Decimal

from finos.adapters.mock_inbox import MockInbox
from finos.adapters.slack_mock import PICKUP_TAG, SlackMock
from finos.billing.mock_billing import MockBilling
from finos.models import ContractEvent, Route, Source, TrustLevel
from finos.pipeline.classify import is_internal
from finos.pipeline.dedup import check_duplicate
from finos.pipeline.validate import validate
from finos.run import sources
from finos.score import GRADED_FIELDS
from finos.evals.judge import agreement, has_placeholder, load_labels
from finos.evals.trajectory import (
    ABSTAIN_PATH,
    INVOICE_PATH,
    SHORT_CIRCUIT_PATH,
    classify_routes_from_trace,
    expected_path,
    paths_from_trace,
)
from finos.store import ingest
from finos.store.ingest import IngestClient, rows_for


def make_event(**overrides) -> ContractEvent:
    fields = {
        "event_id": "gmail:test-001",
        "source": Source.GMAIL,
        "trust_level": TrustLevel.UNTRUSTED,
        "received_at": datetime.now(timezone.utc),
        "raw_ref": "fixtures/emails.json#test-001",
        "route": Route.INVOICE,
        "client_name": "Test GmbH",
        "total_amount": Decimal("1000"),
        "invoice_amount": Decimal("1000"),
        "currency": "EUR",
    }
    return ContractEvent(**{**fields, **overrides})


def test_mock_inbox_emits_one_event_per_email():
    inbox = MockInbox()
    events = inbox.fetch()

    assert len(events) == 20
    assert events[0].event_id == "gmail:msg-001"
    assert events[0].trust_level == TrustLevel.UNTRUSTED
    assert "Nordwind" in inbox.read_raw(events[0].raw_ref)


def test_internal_mail_is_recognised_by_sender_domain():
    assert is_internal("From: Sami K. <sami@younesmotasam.com>\nSubject: hi")
    assert not is_internal("From: Petra <p.lang@nordwind-logistics.de>\nSubject: hi")


def test_validate_flags_a_missing_amount():
    event = validate(make_event(invoice_amount=None))

    assert event.route == Route.FLAG
    assert "no amount to invoice" in event.flags


def test_validate_flags_a_missing_currency():
    event = validate(make_event(currency=None))

    assert event.route == Route.FLAG
    assert "no currency" in event.flags


def test_validate_turns_an_extractor_problem_into_a_flag():
    event = validate(make_event(flags=["amount is a range"]))

    assert event.route == Route.FLAG


def test_validate_flags_low_confidence():
    event = validate(make_event(confidence={"classify": 0.3}))

    assert event.route == Route.FLAG
    assert "low confidence on the route" in event.flags


def test_validate_clears_the_invoice_amount_when_not_invoicing():
    assert validate(make_event(route=Route.HOLD)).invoice_amount is None


def test_validate_leaves_a_complete_invoice_alone():
    event = validate(make_event())

    assert event.route == Route.INVOICE
    assert event.invoice_amount == Decimal("1000")


def test_a_resend_of_an_invoiced_contract_is_rejected(tmp_path):
    billing = MockBilling(store_path=tmp_path / "invoices.json")
    billing.create_draft_invoice(make_event())

    resend = check_duplicate(make_event(event_id="gmail:test-002"), billing)

    assert resend.route == Route.REJECT
    assert "duplicate of gmail:test-001" in resend.flags[0]


def test_the_same_event_seen_again_is_not_a_duplicate_of_itself(tmp_path):
    """Re-running the corpus must not reject everything it invoiced last time."""
    billing = MockBilling(store_path=tmp_path / "invoices.json")
    billing.create_draft_invoice(make_event())

    rerun = check_duplicate(make_event(), billing)

    assert rerun.route == Route.INVOICE


def test_billing_refuses_a_second_invoice_for_the_same_thing(tmp_path):
    billing = MockBilling(store_path=tmp_path / "invoices.json")

    first = billing.create_draft_invoice(make_event())
    second = billing.create_draft_invoice(make_event(event_id="gmail:test-002"))

    assert first == second
    assert len(billing.invoices) == 1


# --- ingest: only what a human must review leaves the machine ---


def test_only_invoice_and_flag_cases_reach_the_review_queue():
    events = [
        make_event(event_id="gmail:a", route=Route.INVOICE),
        make_event(event_id="gmail:b", route=Route.FLAG),
        make_event(event_id="gmail:c", route=Route.HOLD),
        make_event(event_id="gmail:d", route=Route.REJECT),
    ]

    rows = rows_for(events, drafts={"gmail:a": "Hi there, invoice attached."})

    assert [row["event_id"] for row in rows] == ["gmail:a", "gmail:b"]
    assert [row["status"] for row in rows] == ["pending", "flagged"]


def test_an_invoice_row_carries_the_billing_facts_and_its_draft():
    row = rows_for([make_event()], drafts={"gmail:test-001": "Hi there."})[0]

    assert row["client_name"] == "Test GmbH"
    assert row["invoice_amount"] == 1000.0
    assert row["currency"] == "EUR"
    assert row["draft_email"] == "Hi there."


def test_a_flagged_row_carries_its_reasons_and_no_draft():
    event = validate(make_event(invoice_amount=None))

    row = rows_for([event], drafts={})[0]

    assert row["status"] == "flagged"
    assert "no amount to invoice" in row["flags"]
    assert row["draft_email"] is None


def test_push_sends_a_bearer_token_and_the_rows(monkeypatch):
    """The HTTP call is stubbed, so the suite stays offline."""
    monkeypatch.setenv("INGEST_URL", "https://example.test/ingest")
    monkeypatch.setenv("INGEST_SECRET", "test-secret")
    sent = {}

    class StubResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"inserted": 1, "updated": 0}

    def stub_post(url, json, headers, timeout):
        sent.update(url=url, rows=json, headers=headers)
        return StubResponse()

    monkeypatch.setattr(ingest.httpx, "post", stub_post)

    result = IngestClient().push([{"event_id": "gmail:a"}])

    assert sent["url"] == "https://example.test/ingest"
    assert sent["headers"]["Authorization"] == "Bearer test-secret"
    assert sent["rows"] == [{"event_id": "gmail:a"}]
    assert result == {"inserted": 1, "updated": 0}


# --- evals: the path is graded, not just the answer ---


def test_an_invoice_must_go_all_the_way_to_a_draft():
    assert expected_path("INVOICE", "INVOICE") == INVOICE_PATH


def test_an_abstain_stops_after_validate():
    assert expected_path("INVOICE", "FLAG") == ABSTAIN_PATH
    assert expected_path("INVOICE", "HOLD") == ABSTAIN_PATH


def test_a_non_contract_must_never_reach_the_extractor():
    """Extracting from marketing and internal mail is what produced invented values."""
    assert expected_path("REJECT", "REJECT") == SHORT_CIRCUIT_PATH
    assert "extract" not in expected_path("REJECT", "REJECT")


def test_a_duplicate_must_be_caught_at_dedup_not_at_billing():
    """The classifier said contract; dedup overturned it. It must stop before billing."""
    path = expected_path("INVOICE", "REJECT")

    assert path == ABSTAIN_PATH
    assert "billing" not in path


def test_trace_is_read_back_as_one_path_per_event():
    records = [
        {"event_id": "gmail:a", "stage": "classify", "payload": {"route": "INVOICE"}},
        {"event_id": "gmail:b", "stage": "classify", "payload": {"route": "REJECT"}},
        {"event_id": "gmail:a", "stage": "extract", "payload": {}},
        {"event_id": "gmail:a", "stage": "validate", "payload": {}},
    ]

    assert paths_from_trace(records) == {
        "gmail:a": ["classify", "extract", "validate"],
        "gmail:b": ["classify"],
    }
    assert classify_routes_from_trace(records) == {"gmail:a": "INVOICE", "gmail:b": "REJECT"}


# --- evals: draft quality ---


def test_a_leftover_placeholder_is_caught_without_an_llm():
    assert has_placeholder("Dear [Client's Name],\n\nPlease find attached.")
    assert has_placeholder("Amount: {{invoice_amount}}")
    assert not has_placeholder("Dear Petra,\n\nPlease find attached the invoice for 24,000 EUR.")


def test_the_hand_labels_cover_both_verdicts():
    """A judge validated only against passes has not been validated."""
    labels = load_labels()

    assert len(labels) >= 6
    assert {label["label"] for label in labels.values()} == {"pass", "fail"}


def test_judge_agreement_counts_only_the_labelled_cases():
    labels = {"gmail:a": {"label": "pass"}, "gmail:b": {"label": "fail"}}
    verdicts = {
        "gmail:a": {"verdict": "pass", "reason": ""},
        "gmail:b": {"verdict": "pass", "reason": "looked fine"},
        "gmail:c": {"verdict": "fail", "reason": "unlabelled, ignored"},
    }

    matched, checked, disagreements = agreement(verdicts, labels)

    assert (matched, checked) == (1, 2)
    assert "gmail:b" in disagreements[0]


# --- the Slack source: only tagged messages become work ---


def test_slack_adapter_emits_only_tagged_messages():
    slack = SlackMock()

    events = slack.fetch()

    assert len(slack.messages) == 3, "the fixture must include untagged chatter to test the filter"
    assert len(events) == 2
    assert [event.event_id for event in events] == list(slack.corpus())
    assert all(event.event_id.startswith("slack:") for event in events)
    assert all(event.source == Source.SLACK for event in events)
    assert all(event.trust_level == TrustLevel.UNTRUSTED for event in events)


def test_every_adapter_mints_the_ids_it_fetches():
    """The scorer keys the golden set off corpus(); it must match what the run produced."""
    for adapter in sources().values():
        assert {event.event_id for event in adapter.fetch()} == set(adapter.corpus())


def test_event_ids_do_not_collide_across_sources():
    corpora = [adapter.corpus() for adapter in sources().values()]

    merged = {key: value for corpus in corpora for key, value in corpus.items()}

    assert len(merged) == sum(len(corpus) for corpus in corpora)


def test_every_event_can_be_read_back_by_its_own_adapter():
    """What run_all's dispatch relies on, checked without an LLM call."""
    adapters = sources()
    for source, adapter in adapters.items():
        for event in adapter.fetch():
            assert event.source is source
            assert adapters[event.source].read_raw(event.raw_ref)


def test_slack_sender_line_is_built_only_from_what_slack_vouches_for():
    """is_internal reads line one. Nothing a sender types may reach it."""
    slack = SlackMock()

    for event in slack.fetch():
        first_line = slack.read_raw(event.raw_ref).splitlines()[0]

        assert first_line.startswith("From: ")
        assert "attacker" not in first_line
        assert not is_internal(slack.read_raw(event.raw_ref))


def test_a_slack_post_from_our_own_domain_is_still_internal():
    assert is_internal("From: sami@younesmotasam.com (Slack #contracts-inbound)")


def test_the_pickup_tag_never_reaches_the_model():
    """A subject line hinting 'invoice' would bias the very classifier we are testing."""
    slack = SlackMock()

    for event in slack.fetch():
        assert PICKUP_TAG not in slack.read_raw(event.raw_ref).splitlines()[1]


def test_every_golden_case_has_the_fields_the_scorer_reads():
    """golden_value() does expected[field]; a missing key is a KeyError halfway through a run."""
    for adapter in sources().values():
        for event_id, fixture in adapter.corpus().items():
            assert "expected_route" in fixture, event_id
            missing = [f for f in GRADED_FIELDS if f not in fixture["expected"]]
            assert not missing, f"{event_id} is missing {missing}"


def test_the_injection_case_names_what_must_never_appear():
    cases = [f for f in SlackMock().corpus().values() if f["expected"].get("must_not_appear")]

    assert len(cases) == 1
    injection = cases[0]
    assert "attacker@x.com" in injection["expected"]["must_not_appear"]
    assert "attacker@x.com" in injection["text"], "the bait must really be in the message"
    assert injection["expected_route"] in {"HOLD", "FLAG"}, "never a route that bills"
