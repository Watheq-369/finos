"""Grades the dunning graph against the scenario fixtures.

Same discipline as the extraction evals: a golden set with the correct answer written down,
compared field by field, with the misses bucketed so a dropped number always has a cause.

Graded on `action`, `tier` and `days_overdue`. Those three are the whole decision: whether
to chase, how hard, and on what basis. The draft text is graded separately, by the
placeholder check and the judge, exactly as invoice covering emails are.
"""

import json
from pathlib import Path

from finos.dunning.graph import decide
from finos.dunning.payments import MockPayments
from finos.dunning.state import DunningInvoice, Tier

FIXTURES_PATH = Path("fixtures/dunning.json")

GRADED = ["action", "tier", "days_overdue"]


def scenarios() -> list[dict]:
    return json.loads(FIXTURES_PATH.read_text())


def run_scenario(scenario: dict, payments: MockPayments | None = None):
    """One scenario through the graph. Returns the finished state."""
    return decide(
        invoice=DunningInvoice(**scenario["invoice"]),
        reminders_sent=[Tier(t) for t in scenario["reminders_sent"]],
        as_of=scenario["as_of"],
        payments=payments or MockPayments(),
    )


def actual(state, field):
    """What the graph produced, normalised so it compares to the golden JSON."""
    value = getattr(state, field)
    if field in ("action", "tier"):
        return None if value is None else value.value
    return value


def missing_facts(state) -> list[str]:
    """Which required facts a follow-up draft failed to state.

    A dunning email that does not say who, how much, in what currency and how late is not
    ready to send, however fluent it reads. The placeholder regex cannot catch this: a draft
    can be free of template artefacts and still leave the reader guessing.
    """
    if not state.draft_email:
        return []
    # Compare with separators stripped, so "15,000" and "15000" are the same figure.
    haystack = state.draft_email.replace(",", "").lower()
    amount = f"{state.invoice.amount:f}".rstrip("0").rstrip(".")

    missing = []
    if state.invoice.client_name.lower() not in haystack:
        missing.append("client name")
    if amount not in haystack:
        missing.append(f"amount ({amount})")
    if state.invoice.currency.lower() not in haystack:
        missing.append(f"currency ({state.invoice.currency})")
    # "1 day", "2 days": match the figure and the noun, not a fixed phrasing.
    if f"{state.days_overdue} day" not in haystack:
        missing.append(f"days overdue ({state.days_overdue})")
    return missing


def grade() -> tuple[int, int, list[str], dict]:
    """Returns (matched, checked, misses, states-by-scenario-id)."""
    matched = checked = 0
    misses = []
    states = {}
    for scenario in scenarios():
        state = run_scenario(scenario)
        states[scenario["scenario_id"]] = state
        for field in GRADED:
            got, want = actual(state, field), scenario["expected"][field]
            checked += 1
            if got == want:
                matched += 1
            else:
                misses.append(
                    f"{scenario['scenario_id']}: {field} expected {want!r}, got {got!r}")
    return matched, checked, misses, states
