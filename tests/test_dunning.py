"""The dunning loop, offline. No network, no key, no clock.

Every test passes its own reference date. Nothing here reads datetime.now(), which is what
lets a test simulate any day and get the same answer tomorrow.
"""

from datetime import date
from decimal import Decimal

import pytest

from finos.dunning.graph import build_dunning_graph, decide
from finos.dunning.payments import MockPayments
from finos.dunning.schedule import DUNNING_SCHEDULE, days_overdue, next_tier
from finos.dunning.state import Action, DunningInvoice, DunningState, Tier
from finos.evals import dunning_eval

DUE = date(2026, 8, 15)


@pytest.fixture(autouse=True)
def stub_the_drafter(monkeypatch):
    """No LLM call anywhere in this file.

    These tests are about the decision, not the prose. Letting the real drafter run would
    put the suite on the network and make it slow and key-dependent. The actual drafts are
    exercised and graded by `python -m finos.score`, from the committed cache.
    """
    monkeypatch.setattr(
        "finos.dunning.graph.draft_for_tier",
        lambda state: f"[stub draft: {state.tier.value}]",
    )


def invoice(**overrides) -> DunningInvoice:
    fields = {
        "invoice_id": "in_test_001",
        "client_name": "Nordwind Logistics GmbH",
        "amount": Decimal("24000"),
        "currency": "EUR",
        "due_date": DUE,
    }
    return DunningInvoice(**{**fields, **overrides})


def unpaid() -> MockPayments:
    return MockPayments(paid_ids=set())


def paid(invoice_id: str = "in_test_001") -> MockPayments:
    return MockPayments(paid_ids={invoice_id})


# --- the cadence, independent of the graph ---


def test_days_overdue_counts_from_the_reference_date_not_the_clock():
    assert days_overdue(DUE, date(2026, 8, 15)) == 0
    assert days_overdue(DUE, date(2026, 8, 19)) == 4
    assert days_overdue(DUE, date(2026, 8, 10)) == -5


@pytest.mark.parametrize("days,expected", [
    (-3, None), (0, None),
    (1, Tier.REMINDER_1), (2, Tier.REMINDER_2), (4, Tier.ESCALATION),
])
def test_the_schedule_thresholds_are_the_cadence(days, expected):
    assert next_tier(days, already_sent=[]) is expected


def test_a_tier_already_sent_is_never_sent_again():
    assert next_tier(1, already_sent=[Tier.REMINDER_1]) is None
    assert next_tier(2, already_sent=[Tier.REMINDER_1]) is Tier.REMINDER_2
    assert next_tier(9, already_sent=list(Tier)) is None


def test_the_cadence_lives_in_the_constant_not_the_logic():
    """Changing the constant must change the behaviour, or it is decoration."""
    assert DUNNING_SCHEDULE == [(1, Tier.REMINDER_1), (2, Tier.REMINDER_2), (4, Tier.ESCALATION)]

    patched = [(10, Tier.REMINDER_1)]
    original = DUNNING_SCHEDULE[:]
    DUNNING_SCHEDULE[:] = patched
    try:
        assert next_tier(1, []) is None   # would be reminder_1 under the real cadence
        assert next_tier(10, []) is Tier.REMINDER_1
    finally:
        DUNNING_SCHEDULE[:] = original


# --- the graph ---


def test_a_paid_invoice_is_resolved_and_never_chased():
    """The freshness guard. Deliberately the most overdue case in the suite."""
    state = decide(invoice(), reminders_sent=[Tier.REMINDER_1], as_of=date(2026, 8, 30),
                   payments=paid())

    assert state.action is Action.RESOLVED
    assert state.tier is None
    assert state.draft_email is None
    # It left the graph before any arithmetic happened, rather than being filtered later.
    assert state.days_overdue is None


def test_not_overdue_yet_means_no_action_and_no_draft():
    state = decide(invoice(), reminders_sent=[], as_of=DUE, payments=unpaid())

    assert state.action is Action.NONE
    assert state.tier is None
    assert state.draft_email is None
    assert state.days_overdue == 0


def test_an_exhausted_schedule_stops_rather_than_repeating():
    state = decide(invoice(), reminders_sent=list(Tier), as_of=date(2026, 8, 30),
                   payments=unpaid())

    assert state.action is Action.NONE
    assert state.draft_email is None
    assert "already been sent" in state.reason


def test_the_run_never_sends_anything():
    """Whatever it decides, the output is a draft awaiting a human."""
    state = decide(invoice(), reminders_sent=[], as_of=date(2026, 8, 16), payments=unpaid())

    assert state.action is Action.SEND_REMINDER
    assert state.tier is Tier.REMINDER_1
    # The tier is not recorded as sent by the run. That only happens after a human approves,
    # and arrives as an input to the NEXT run.
    assert state.reminders_sent == []


def test_the_loop_advances_one_tier_per_run():
    """Three runs of the same invoice, each fed the previous run's outcome."""
    sent: list[Tier] = []
    reached = []
    for as_of in [date(2026, 8, 16), date(2026, 8, 17), date(2026, 8, 19)]:
        state = decide(invoice(), reminders_sent=sent, as_of=as_of, payments=unpaid())
        reached.append(state.tier)
        sent = sent + [state.tier]

    assert reached == [Tier.REMINDER_1, Tier.REMINDER_2, Tier.ESCALATION]


def test_a_missed_run_escalates_rather_than_opening_gently():
    """First look at an invoice already 4 days late: do not start with a stale nudge."""
    state = decide(invoice(), reminders_sent=[], as_of=date(2026, 8, 19), payments=unpaid())

    assert state.tier is Tier.ESCALATION


# --- the graph's shape ---


def test_the_graph_has_the_nodes_and_branches_the_loop_needs():
    graph = build_dunning_graph(unpaid()).get_graph()
    nodes = set(graph.nodes)

    assert {"check_paid", "mark_resolved", "compute_overdue",
            "decide_tier", "draft_follow_up", "no_action"} <= nodes

    edges = {(e.source, e.target) for e in graph.edges}
    # Payment is checked first, before anything is computed or drafted.
    assert ("__start__", "check_paid") in edges
    assert ("check_paid", "mark_resolved") in edges
    assert ("check_paid", "compute_overdue") in edges
    assert ("decide_tier", "draft_follow_up") in edges
    assert ("decide_tier", "no_action") in edges


def test_the_graph_has_no_cycle_back_into_checking():
    """The loop across days runs through a human, not around an edge.

    A cycle inside one invocation would mean the graph sends and re-checks by itself.
    """
    graph = build_dunning_graph(unpaid()).get_graph()
    edges = {(e.source, e.target) for e in graph.edges}

    assert not any(target == "check_paid" for source, target in edges if source != "__start__")


# --- the golden set ---


def test_every_dunning_scenario_carries_a_full_expected_block():
    """A missing key would be a KeyError halfway through the eval."""
    for scenario in dunning_eval.scenarios():
        missing = [f for f in dunning_eval.GRADED if f not in scenario["expected"]]
        assert not missing, f"{scenario['scenario_id']} is missing {missing}"


def test_the_scenario_set_covers_every_action_and_every_tier():
    """A golden set that never exercises escalation cannot catch a broken escalation."""
    expected = [s["expected"] for s in dunning_eval.scenarios()]

    assert {e["action"] for e in expected} == {a.value for a in Action}
    assert {e["tier"] for e in expected if e["tier"]} == {t.value for t in Tier}


def test_the_mock_payment_store_marks_exactly_the_paid_scenario():
    """If nothing is paid, the freshness guard scenario passes for the wrong reason."""
    paid_scenarios = [s for s in dunning_eval.scenarios()
                      if s["expected"]["action"] == Action.RESOLVED.value]

    assert len(paid_scenarios) == 1
    payments = MockPayments()
    assert payments.is_paid(paid_scenarios[0]["invoice"]["invoice_id"])
    for scenario in dunning_eval.scenarios():
        if scenario not in paid_scenarios:
            assert not payments.is_paid(scenario["invoice"]["invoice_id"])


def test_the_state_rejects_a_run_with_no_reference_date():
    """as_of is required, so nothing can quietly fall back to the clock."""
    with pytest.raises(ValueError):
        DunningState(invoice=invoice())
