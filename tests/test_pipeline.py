"""Tests for the parts that do not call the LLM: the adapter, the rule checks, and dedup."""

from datetime import datetime, timezone
from decimal import Decimal

from finos.billing.mock_billing import MockBilling
from finos.adapters.mock_inbox import MockInbox
from finos.models import ContractEvent, Route, Source, TrustLevel
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
        "amount": Decimal("1000"),
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


def test_validate_flags_a_missing_amount():
    event = validate(make_event(amount=None))

    assert event.route == Route.FLAG
    assert "no amount" in event.flags


def test_validate_leaves_a_complete_invoice_alone():
    assert validate(make_event()).route == Route.INVOICE


def test_billing_refuses_a_second_invoice_for_the_same_thing(tmp_path):
    billing = MockBilling(store_path=tmp_path / "invoices.json")

    first = billing.create_draft_invoice(make_event())
    second = billing.create_draft_invoice(make_event(event_id="gmail:test-002"))

    assert first == second
    assert len(billing.invoices) == 1
