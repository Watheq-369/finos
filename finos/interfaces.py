"""The seams. Mock and real implementations satisfy the same shape, so swapping one in is not a rewrite."""

from typing import Optional, Protocol

from finos.models import ContractEvent


class SourceAdapter(Protocol):
    def fetch(self) -> list[ContractEvent]:
        """Return raw ContractEvents, fields empty except the adapter-set ones."""

    def read_raw(self, raw_ref: str) -> str:
        """Return the raw message text a raw_ref points at."""


class BillingClient(Protocol):
    def match_or_create_customer(self, name: str, email: Optional[str]) -> str:
        """Return a customer id. Idempotent on name."""

    def invoiced_by(self, event: ContractEvent) -> Optional[str]:
        """Which event already invoiced this client, amount and currency, if any.

        Returns that event's id, or None. `dedup.check_duplicate` calls this before
        anything is billed, so an implementation that gets it wrong bills twice.
        """

    def create_draft_invoice(self, event: ContractEvent) -> str:
        """Return a DRAFT invoice id. Never finalises and never sends.

        Idempotent: the same client, amount and currency returns the existing draft
        rather than creating a second one.
        """

    def invoice_status(self, invoice_id: str) -> str:
        """Stripe's own status: draft, open, paid, void, uncollectible.

        The worker reads this before acting, so an already-finalised invoice is a no-op
        rather than a second finalise.
        """

    def finalise_invoice(self, invoice_id: str) -> str:
        """Move a draft to open. Returns the new status.

        This is the one irreversible step in the system, which is why it sits behind a
        human approval and an explicit flag. It does NOT deliver anything to the customer.
        """


class ReviewQueue(Protocol):
    """The rows a human has acted on. A stub locally, the Lovable endpoints later."""

    def approved_rows(self) -> list[dict]:
        """Rows the owner approved that have not been sent yet. Never anything else."""

    def mark_sent(self, event_id: str, stripe_invoice_id: str) -> None:
        """Record the send: store the invoice id and flip the row to sent."""


class TraceStore(Protocol):
    def write(self, event_id: str, stage: str, payload: dict) -> None:
        """Append one trace record."""
