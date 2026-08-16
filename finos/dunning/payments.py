"""Is this invoice paid? Mock for now, Stripe later.

Deliberately its own seam. The dunning loop's worst failure is chasing someone who has
already paid, so the thing that answers this question has to be swappable for the real
Stripe read without touching the graph.
"""

import json
from pathlib import Path
from typing import Protocol

STORE_PATH = Path("fixtures/dunning_payments.json")


class PaymentStatus(Protocol):
    """The one question the graph asks. Stripe will implement this same method."""

    def is_paid(self, invoice_id: str) -> bool: ...


class MockPayments:
    """Reads paid/unpaid from a fixture file. No network, no key."""

    def __init__(self, paid_ids: set[str] | None = None):
        if paid_ids is not None:
            self.paid_ids = paid_ids
        else:
            self.paid_ids = set(json.loads(STORE_PATH.read_text())) if STORE_PATH.exists() else set()

    def is_paid(self, invoice_id: str) -> bool:
        return invoice_id in self.paid_ids
