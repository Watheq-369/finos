"""Pushes the review-worthy results to the Lovable ingest endpoint.

One POST, an array of `review_queue` rows, authorised with `Bearer INGEST_SECRET`.
The endpoint upserts on `event_id`, so re-running the pipeline updates the existing
rows instead of duplicating them.

This is an extra writer. The local JSONL trace is untouched and stays the tested path.
"""

import os
from typing import Optional

import httpx
from dotenv import load_dotenv

from finos.models import ContractEvent, Route

load_dotenv()

# Only these two routes need a human. HOLD and REJECT stay out of the review queue.
STATUS_BY_ROUTE = {Route.INVOICE: "pending", Route.FLAG: "flagged"}


def to_review_row(event: ContractEvent, draft_email: Optional[str]) -> dict:
    """Shape one finished event as a review_queue row."""
    return {
        "event_id": event.event_id,
        "source": event.source.value,
        "received_at": event.received_at.isoformat(),
        "route": event.route.value,
        "client_name": event.client_name,
        "invoice_amount": None if event.invoice_amount is None else float(event.invoice_amount),
        "currency": event.currency,
        "vat_treatment": event.vat_treatment.value,
        "tax_id": event.tax_id,
        "flags": event.flags,
        "draft_email": draft_email,
        "status": STATUS_BY_ROUTE[event.route],
    }


def rows_for(events: list[ContractEvent], drafts: dict[str, str]) -> list[dict]:
    """The INVOICE and FLAG rows from a run, in corpus order."""
    return [
        to_review_row(event, drafts.get(event.event_id))
        for event in events
        if event.route in STATUS_BY_ROUTE
    ]


class IngestClient:
    """Sends review_queue rows to the endpoint. Never sends an email, never bills anything."""

    def __init__(self):
        self.url = os.getenv("INGEST_URL")
        self.secret = os.getenv("INGEST_SECRET")
        if not self.url or not self.secret:
            raise RuntimeError("INGEST_URL and INGEST_SECRET must both be set in .env")

    def push(self, rows: list[dict]) -> dict:
        """POST the rows and return what the endpoint reports back."""
        response = httpx.post(
            self.url,
            json=rows,
            headers={"Authorization": f"Bearer {self.secret}"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
