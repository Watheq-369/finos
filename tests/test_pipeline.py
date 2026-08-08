"""Tests for the parts that do not call the LLM: the adapter, the rules, dedup, and billing."""

from datetime import datetime, timezone
from decimal import Decimal

from finos.adapters.mock_inbox import MockInbox
from finos.billing.mock_billing import MockBilling
from finos.models import ContractEvent, Route, Source, TrustLevel
from finos.pipeline.classify import is_internal
from finos.pipeline.dedup import check_duplicate
from finos.pipeline.validate import validate


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
