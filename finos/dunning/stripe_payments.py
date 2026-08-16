"""Real Stripe payment status, behind the same `PaymentStatus` protocol as the mock.

The dunning graph asks one question, "is this paid?", and never learns which implementation
answered it. This module also supplies the two other things the runner needs from Stripe:
the list of open invoices to chase, and each invoice's raw status for the dashboard sync.

Opt-in only: `python -m finos.dunning.run --stripe`. The graph's tests, the scenario evals
and `score.py` all stay on `MockPayments`, so the suite needs no key and no network.

Read-only. Nothing here creates, finalises, voids or sends anything.
"""

import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import stripe as stripe_sdk
from dotenv import load_dotenv

from finos.dunning.state import DunningInvoice

load_dotenv()

# Stripe's own name for "finalised and not yet paid". These are the invoices a client
# actually owes money on, and the only ones worth chasing. Drafts are not yet real, void
# ones are cancelled, and paid ones are done.
CHASEABLE_STATUS = "open"


def test_key() -> str:
    """The same hard stop the billing adapter applies, deliberately repeated.

    A safety check that can be bypassed by importing a different module is not a safety
    check. This reads the key itself rather than borrowing it from `StripeBilling`.
    """
    key = (os.getenv("STRIPE_RESTRICTED_KEY") or "").strip()
    if not key:
        raise RuntimeError("STRIPE_RESTRICTED_KEY must be set in .env to use Stripe.")
    if not key.startswith(("sk_test_", "rk_test_")):
        raise RuntimeError(
            "STRIPE_RESTRICTED_KEY is not a Stripe TEST key. Expected it to start with "
            "'rk_test_' (restricted, preferred) or 'sk_test_'. Refusing to run."
        )
    return key


def _to_date(timestamp: Optional[int]) -> Optional[date]:
    return None if timestamp is None else datetime.fromtimestamp(timestamp, timezone.utc).date()


class StripePayments:
    """Implements PaymentStatus against real Stripe, in test mode."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or test_key()

    def status(self, invoice_id: str) -> str:
        """Stripe's own status: draft, open, paid, void or uncollectible.

        Always fetched live. The whole point of the freshness guard is that this is current,
        not what we remembered from an earlier run.
        """
        return stripe_sdk.Invoice.retrieve(invoice_id, api_key=self.api_key).status

    def is_paid(self, invoice_id: str) -> bool:
        """The one question the dunning graph asks."""
        return self.status(invoice_id) == "paid"

    def open_invoices(self) -> list[DunningInvoice]:
        """Every finalised, unpaid invoice, as the dunning loop sees it.

        Invoices with no due date are skipped: there is no such thing as overdue without
        one, and guessing a due date would be inventing the fact the whole decision rests on.
        """
        found = []
        for invoice in stripe_sdk.Invoice.list(
            api_key=self.api_key, status=CHASEABLE_STATUS, limit=100
        ).auto_paging_iter():
            due_date = _to_date(getattr(invoice, "due_date", None))
            if due_date is None:
                continue
            found.append(DunningInvoice(
                invoice_id=invoice.id,
                client_name=invoice.customer_name or "(unnamed customer)",
                # Stripe holds amounts in the currency's smallest unit.
                amount=Decimal(invoice.total) / 100,
                currency=invoice.currency.upper(),
                due_date=due_date,
            ))
        return found

    def statuses_by_event(self) -> dict[str, dict]:
        """{finos_event_id: {invoice_id, status}} for every invoice this system created.

        The event id is stamped into invoice metadata at creation, which is what lets the
        dashboard sync match a Stripe invoice back to its review-queue row without the
        review app needing to expose a read-everything endpoint.
        """
        by_event = {}
        for invoice in stripe_sdk.Invoice.list(api_key=self.api_key, limit=100).auto_paging_iter():
            # StripeObject, not a dict: no .get(), and dict() on it raises.
            metadata = invoice.metadata.to_dict() if invoice.metadata else {}
            event_id = metadata.get("finos_event_id")
            if event_id:
                # setdefault, not assignment: Stripe lists newest first, and one event CAN
                # have more than one invoice (a voided original plus a later draft). The
                # newest is the live one, so the first seen wins and the stale record does
                # not overwrite it.
                by_event.setdefault(event_id, {"invoice_id": invoice.id, "status": invoice.status})
        return by_event
