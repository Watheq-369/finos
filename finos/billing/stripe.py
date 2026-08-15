"""Real Stripe billing client, the system of record.

Same contract as MockBilling, so the pipeline cannot tell them apart. Stripe owns invoice
numbering, tax and payment status; we do not reimplement any of it.

Three safety properties matter more than anything else here:

1. **The pipeline only ever creates drafts.** `create_draft_invoice` sets
   `auto_advance=False` and never finalises. A draft sits in Stripe waiting for a human.
2. **Finalising is separate, and gated.** `finalise_invoice` exists for the worker, which
   only acts on rows a human approved and only behind an explicit `--send` flag. It also
   passes `auto_advance=False`, so Stripe does not deliver or dun on its own. Nothing here
   ever calls `send_invoice`; customer delivery is a deliberate future step.
3. **One invoice per contract.** The event id and a client|amount|currency signature are
   written into invoice metadata, and looked up before creating anything. Running the
   pipeline twice returns the existing draft instead of billing a client twice.

Opt-in only: `python -m finos.run --mock --stripe`. The scorer and the whole test suite
stay on MockBilling, so CI needs no key and touches no network.
"""

import os
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

import stripe as stripe_sdk
from dotenv import load_dotenv

from finos.models import ContractEvent

load_dotenv()

# Our own namespace on the Stripe object, so nothing else can be mistaken for it.
EVENT_ID_KEY = "finos_event_id"
SIGNATURE_KEY = "finos_signature"


def _signature(event: ContractEvent) -> str:
    """What makes two invoices the same invoice. Identical to mock billing on purpose."""
    return f"{(event.client_name or '').strip().lower()}|{event.invoice_amount}|{event.currency}"


def _minor_units(amount: Decimal) -> int:
    """Stripe takes amounts in the currency's smallest unit: EUR 12,500.00 -> 1250000."""
    return int((Decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class StripeBilling:
    """Implements BillingClient against the real Stripe API, in test mode."""

    def __init__(self, api_key: Optional[str] = None):
        key = (api_key or os.getenv("STRIPE_RESTRICTED_KEY") or "").strip()
        if not key:
            raise RuntimeError("STRIPE_RESTRICTED_KEY must be set in .env to use Stripe.")
        # A hard stop, not a warning. This client creates invoices for real clients, and
        # the one mistake that cannot be undone is doing it against a live account.
        if not key.startswith(("sk_test_", "rk_test_")):
            raise RuntimeError(
                "STRIPE_RESTRICTED_KEY is not a Stripe TEST key. Expected it to start with "
                "'rk_test_' (restricted, preferred) or 'sk_test_'. Refusing to run."
            )
        self.api_key = key
        self._customers: dict[str, str] = {}  # name (lowercased) -> customer id
        self._invoices: dict[str, dict] = {}  # signature -> {invoice_id, event_id}
        self._loaded = False

    def _load(self) -> None:
        """Read what Stripe already has, once, the way MockBilling reads its JSON store.

        Deliberately a plain listing rather than the Search API: search is eventually
        consistent by up to a minute, so a second run moments later could miss the invoice
        it just wrote and bill twice. Listing is immediately consistent.
        """
        if self._loaded:
            return
        for customer in stripe_sdk.Customer.list(api_key=self.api_key, limit=100).auto_paging_iter():
            if customer.name:
                self._customers.setdefault(customer.name.strip().lower(), customer.id)
        # EVERY status, not just draft. Once the worker finalises an invoice it leaves
        # draft, and if the index only held drafts the next pipeline run would not see it,
        # would believe the contract was never invoiced, and would raise a second one.
        # That is a wrong invoice, which is the one thing this system must never do.
        for invoice in stripe_sdk.Invoice.list(
            api_key=self.api_key, limit=100
        ).auto_paging_iter():
            # Stripe returns metadata as a StripeObject, not a dict: it has no .get() and
            # dict() on it raises. to_dict() is the only safe read, and it copes with empty
            # metadata. Getting this wrong crashes the second run, which is the run that
            # proves we do not double-bill.
            metadata = invoice.metadata.to_dict() if invoice.metadata else {}
            signature = metadata.get(SIGNATURE_KEY)
            if signature:
                self._invoices.setdefault(signature, {
                    "invoice_id": invoice.id,
                    "event_id": metadata.get(EVENT_ID_KEY),
                })
        self._loaded = True

    def match_or_create_customer(self, name: str, email: Optional[str]) -> str:
        self._load()
        key = (name or "").strip().lower()
        if key not in self._customers:
            customer = stripe_sdk.Customer.create(api_key=self.api_key, name=name, email=email)
            self._customers[key] = customer.id
        return self._customers[key]

    def invoiced_by(self, event: ContractEvent) -> Optional[str]:
        """Which event already invoiced this exact client, amount and currency, if any."""
        self._load()
        existing = self._invoices.get(_signature(event))
        return existing["event_id"] if existing else None

    def create_draft_invoice(self, event: ContractEvent) -> str:
        """Create a DRAFT invoice, or return the existing one. Never finalises, never sends."""
        self._load()
        signature = _signature(event)
        existing = self._invoices.get(signature)
        if existing:
            return existing["invoice_id"]

        customer_id = self.match_or_create_customer(event.client_name, event.client_email)
        currency = (event.currency or "").lower()
        invoice = stripe_sdk.Invoice.create(
            api_key=self.api_key,
            customer=customer_id,
            currency=currency,
            collection_method="send_invoice",
            days_until_due=30,
            auto_advance=False,  # never let Stripe finalise or send this on its own
            pending_invoice_items_behavior="exclude",
            metadata={EVENT_ID_KEY: event.event_id, SIGNATURE_KEY: signature},
        )
        stripe_sdk.InvoiceItem.create(
            api_key=self.api_key,
            customer=customer_id,
            invoice=invoice.id,
            amount=_minor_units(event.invoice_amount),
            currency=currency,
            description=f"{event.client_name} - {event.invoice_amount} {event.currency}",
        )
        self._invoices[signature] = {"invoice_id": invoice.id, "event_id": event.event_id}
        return invoice.id

    def invoice_status(self, invoice_id: str) -> str:
        """Read Stripe's own status. Always fetched live, never cached: the worker's
        idempotency depends on this being current, not on what we remember."""
        return stripe_sdk.Invoice.retrieve(invoice_id, api_key=self.api_key).status

    def finalise_invoice(self, invoice_id: str) -> str:
        """Move a draft to open. Refuses anything that is not still a draft.

        `auto_advance=False` matters: it stops Stripe from progressing the invoice on its
        own, which is what would otherwise email the customer and start dunning. Finalising
        is the action here; delivery to the client is a deliberate future step.
        """
        status = self.invoice_status(invoice_id)
        if status != "draft":
            return status
        invoice = stripe_sdk.Invoice.finalize_invoice(
            invoice_id, api_key=self.api_key, auto_advance=False
        )
        return invoice.status
