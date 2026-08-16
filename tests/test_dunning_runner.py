"""The runner, the decision log and the status sync. All offline.

Nothing here touches Stripe, the network or a clock. The runner takes its invoices and its
payment source as arguments precisely so the whole loop can be exercised with fakes.
"""

from datetime import date
from decimal import Decimal

import pytest

from finos.dunning.log import DunningLog
from finos.dunning.payments import MockPayments
from finos.dunning.run import row_for, run_dunning
from finos.dunning.state import Action, DunningInvoice, Tier
from finos.dunning.status_sync import rows_for

DUE = date(2026, 9, 14)


@pytest.fixture(autouse=True)
def stub_the_drafter(monkeypatch):
    """No LLM call. These tests are about the loop, not the prose."""
    monkeypatch.setattr(
        "finos.dunning.graph.draft_for_tier",
        lambda state: f"[stub draft: {state.tier.value}]",
    )


@pytest.fixture
def log(tmp_path):
    """A decision log in a temp dir, so tests never touch runs/dunning.json."""
    return DunningLog(path=tmp_path / "dunning.json")


def invoice(invoice_id="in_test_1", client="Nordwind Logistics GmbH", amount="24000") -> DunningInvoice:
    return DunningInvoice(invoice_id=invoice_id, client_name=client,
                          amount=Decimal(amount), currency="EUR", due_date=DUE)


def unpaid() -> MockPayments:
    return MockPayments(paid_ids=set())


# --- the runner ---


def test_a_run_decides_once_per_invoice(log):
    invoices = [invoice("in_a"), invoice("in_b", client="Verde Energy S.L.")]

    results = run_dunning(invoices, date(2026, 9, 15), unpaid(), log)

    assert [i.invoice_id for i, _ in results] == ["in_a", "in_b"]
    assert all(state.tier is Tier.REMINDER_1 for _, state in results)


def test_the_log_stops_a_tier_repeating_across_runs(log):
    """The whole reason the log exists. Same invoice, three days, three tiers."""
    reached = []
    for as_of in [date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 18)]:
        (_, state), = run_dunning([invoice()], as_of, unpaid(), log)
        reached.append(state.tier)

    assert reached == [Tier.REMINDER_1, Tier.REMINDER_2, Tier.ESCALATION]
    assert log.reminders_sent("in_test_1") == list(Tier)


def test_running_twice_on_the_same_day_does_not_burn_a_second_tier(log):
    """An operator re-running the command must not escalate the client."""
    run_dunning([invoice()], date(2026, 9, 15), unpaid(), log)
    (_, second), = run_dunning([invoice()], date(2026, 9, 15), unpaid(), log)

    assert second.action is Action.NONE
    assert log.reminders_sent("in_test_1") == [Tier.REMINDER_1]


def test_a_paid_invoice_is_never_chased_and_burns_no_tier(log):
    paid = MockPayments(paid_ids={"in_test_1"})

    (_, state), = run_dunning([invoice()], date(2026, 9, 30), paid, log)

    assert state.action is Action.RESOLVED
    assert log.reminders_sent("in_test_1") == []


def test_the_log_survives_being_reloaded(log):
    """It is only useful if it persists between processes."""
    run_dunning([invoice()], date(2026, 9, 15), unpaid(), log)
    log.save()

    reloaded = DunningLog(path=log.path)

    assert reloaded.reminders_sent("in_test_1") == [Tier.REMINDER_1]


def test_the_table_row_shows_what_the_operator_needs(log):
    (inv, state), = run_dunning([invoice()], date(2026, 9, 16), unpaid(), log)

    line = row_for(inv, state)

    assert "Nordwind Logistics GmbH" in line
    assert "24,000.00 EUR" in line
    assert "2d" in line
    assert "reminder_2" in line


# --- the status sync ---


def test_the_sync_sends_only_the_key_and_the_status():
    """Any extra field would be an upsert overwriting something a human set."""
    rows = rows_for({"gmail:msg-001": {"invoice_id": "in_1", "status": "open"}})

    assert rows == [{
        "event_id": "gmail:msg-001",
        "stripe_invoice_id": "in_1",
        "stripe_status": "open",
    }]


def test_the_sync_carries_every_status_stripe_reports():
    statuses = {
        "gmail:msg-001": {"invoice_id": "in_1", "status": "paid"},
        "gmail:msg-002": {"invoice_id": "in_2", "status": "void"},
        "gmail:msg-003": {"invoice_id": "in_3", "status": "draft"},
    }

    rows = rows_for(statuses)

    assert {r["stripe_status"] for r in rows} == {"paid", "void", "draft"}
    assert [r["event_id"] for r in rows] == sorted(statuses)
