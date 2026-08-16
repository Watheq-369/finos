"""The objects the dunning graph passes between its nodes.

One graph run answers one question: given this invoice, what has already been sent, and
what day is it, what should happen next? It decides and drafts. It never sends.

`as_of` is passed in, never read from the clock. That is what makes a run reproducible:
the same inputs give the same answer today, in a test, and in a demo of any date.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Tier(str, Enum):
    """The dunning tiers, gentlest first. The order here is the escalation order."""

    REMINDER_1 = "reminder_1"
    REMINDER_2 = "reminder_2"
    ESCALATION = "escalation"


class Action(str, Enum):
    """What one graph run concluded. Exactly one of these per run."""

    NONE = "none"  # not overdue enough yet, or every tier already sent
    SEND_REMINDER = "send_reminder"  # a tier is due, draft written, awaiting approval
    RESOLVED = "resolved"  # paid, stop chasing


class DunningInvoice(BaseModel):
    """One open, unpaid invoice, as far as the dunning loop is concerned."""

    invoice_id: str
    client_name: str
    amount: Decimal
    currency: str
    due_date: date


class DunningState(BaseModel):
    """The graph's state. Nodes read the top half and fill in the bottom half."""

    # Inputs, set by the caller before the run.
    invoice: DunningInvoice
    reminders_sent: list[Tier] = Field(default_factory=list)
    as_of: date

    # Filled in by the nodes as the run proceeds.
    is_paid: Optional[bool] = None
    days_overdue: Optional[int] = None
    tier: Optional[Tier] = None
    action: Optional[Action] = None
    draft_email: Optional[str] = None
    reason: Optional[str] = None
