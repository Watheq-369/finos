"""The cadence, as data, plus the one rule that reads it.

The cadence is the thing most likely to change: a client asks for a gentler rhythm, or a
market's norms differ. It lives here as a constant so changing it is editing one list, not
hunting through the graph for a hardcoded number.
"""

from finos.dunning.state import Tier

# (days overdue at which the tier becomes due, the tier). Ordered gentlest first.
DUNNING_SCHEDULE: list[tuple[int, Tier]] = [
    (1, Tier.REMINDER_1),
    (2, Tier.REMINDER_2),
    (4, Tier.ESCALATION),
]


def days_overdue(due_date, as_of) -> int:
    """How many days late, as of the reference date. Negative before the due date."""
    return (as_of - due_date).days


def next_tier(days: int, already_sent: list[Tier]) -> Tier | None:
    """The tier to send now, or None if nothing is due.

    Two rules, and they are the whole cadence:
    1. A tier is due once `days` reaches its threshold.
    2. A tier already sent is never sent again.

    Taking the LAST qualifying tier rather than the first matters when a run is missed. An
    invoice first seen at 4 days overdue escalates, instead of opening with a gentle nudge
    that is already four days stale. It still never skips a tier that was actually sent.
    """
    due = [tier for threshold, tier in DUNNING_SCHEDULE
           if days >= threshold and tier not in already_sent]
    return due[-1] if due else None
