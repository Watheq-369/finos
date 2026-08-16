"""Pushes the review-worthy results to the Lovable ingest endpoint.

One POST, an array of `review_queue` rows, authorised with `Bearer INGEST_SECRET`.
The endpoint upserts on `event_id`, so re-running the pipeline updates the existing
rows instead of duplicating them.

This is an extra writer. The local JSONL trace is untouched and stays the tested path.

## Who owns which column

An upsert writes every column it is given. So the only reliable way to stop a machine
write from clobbering a human decision is for the machine never to name that column.

- **Pipeline-owned** (`PIPELINE_OWNED`): the facts extracted from the message and the draft
  written from them. This client may write these.
- **Human-owned** (`HUMAN_OWNED`): `status` and `decided_at`. A person sets these in the
  review UI. This client must never send them, not even as null.
- **Database-owned**: `created_at`. Never sent.
- **Stripe-owned**: `stripe_invoice_id` and `stripe_status`. Written only by
  `finos.dunning.status_sync`, which sends those two columns and nothing else.

A field whose value is None is omitted rather than sent as null, so an absent value can
never overwrite one that is already there. This is why a re-sync cannot blank a row.

That rule exists because it was broken: a sync that carried human-owned fields nulled
`status` on three already-approved rows and hid them from the UI.
"""

import os
from typing import Optional

import httpx
from dotenv import load_dotenv

from finos.models import ContractEvent, Route

load_dotenv()

# Only these two routes need a human. HOLD and REJECT stay out of the review queue.
ROUTES_NEEDING_REVIEW = {Route.INVOICE, Route.FLAG}

# The columns this client is allowed to write. `event_id` is the upsert key and is always
# present; everything else is omitted when it has no value.
PIPELINE_OWNED = [
    "event_id", "source", "received_at", "route", "client_name", "invoice_amount",
    "currency", "vat_treatment", "tax_id", "flags", "draft_email",
]

# Set by a human in the review UI, or by the database. Never sent by any writer here.
HUMAN_OWNED = {"status", "decided_at"}
DATABASE_OWNED = {"created_at"}

# Written only by the Stripe status sync, and only ever on their own.
STRIPE_OWNED = {"stripe_invoice_id", "stripe_status"}


def check_payload(row: dict, allowed: set[str]) -> dict:
    """The contract, enforced in code rather than trusted to reviewers.

    A payload that names a human-owned column is a bug that silently destroys someone's
    decision, and it would look completely normal in a diff. Failing loudly here is the
    only way that stays impossible as the code changes.
    """
    forbidden = HUMAN_OWNED | DATABASE_OWNED
    named = set(row)
    if named & forbidden:
        raise ValueError(
            f"ingest payload must never carry {sorted(named & forbidden)}: "
            "those columns belong to the human review UI or the database."
        )
    if not named <= allowed:
        raise ValueError(f"ingest payload carries unexpected columns {sorted(named - allowed)}")
    if "event_id" not in row:
        raise ValueError("ingest payload needs event_id, the upsert key")
    if any(value is None for value in row.values()):
        nulls = sorted(k for k, v in row.items() if v is None)
        raise ValueError(
            f"ingest payload must omit empty fields, not send them as null: {nulls}"
        )
    return row


def to_review_row(event: ContractEvent, draft_email: Optional[str]) -> dict:
    """Shape one finished event as a review_queue row, pipeline-owned columns only.

    No `status`: that is the human's column. No `stripe_invoice_id`: the Stripe sync owns
    that one and writes it separately.
    """
    values = {
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
    }
    # Omit, never null. An absent key leaves whatever the row already holds.
    row = {key: value for key, value in values.items() if value is not None}
    return check_payload(row, allowed=set(PIPELINE_OWNED))


def rows_for(events: list[ContractEvent], drafts: dict[str, str]) -> list[dict]:
    """The INVOICE and FLAG rows from a run, in corpus order."""
    return [
        to_review_row(event, drafts.get(event.event_id))
        for event in events
        if event.route in ROUTES_NEEDING_REVIEW
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
