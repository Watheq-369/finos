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

    def create_draft_invoice(self, event: ContractEvent) -> str:
        """Return a draft invoice id. Refuses duplicates (see mock billing)."""


class TraceStore(Protocol):
    def write(self, event_id: str, stage: str, payload: dict) -> None:
        """Append one trace record."""
