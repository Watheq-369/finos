"""Orchestrator. Runs every email in the mock inbox through the pipeline and writes a trace.

Nothing is ever sent. INVOICE cases end at a draft invoice and a draft email, waiting for a human.

    python -m finos.run --mock
"""

import argparse
from collections import Counter

from finos.adapters.mock_inbox import MockInbox
from finos.billing.mock_billing import MockBilling
from finos.models import ContractEvent, Route
from finos.pipeline.classify import classify
from finos.pipeline.dedup import check_duplicate
from finos.pipeline.draft import draft
from finos.pipeline.extract import extract
from finos.pipeline.validate import validate
from finos.store.local_trace import LocalTrace


def process_one(event: ContractEvent, email_text: str, billing: MockBilling, trace: LocalTrace) -> str:
    """Run one email through every stage. Returns the one-line summary."""
    classify(event, email_text)
    trace.write(event.event_id, "classify", {"route": event.route, "confidence": event.confidence})

    # Anything the classifier did not reject is a contract candidate worth reading.
    if event.route != Route.REJECT:
        extract(event, email_text)
        trace.write(event.event_id, "extract", event.model_dump(include={
            "client_name", "client_email", "total_amount", "invoice_amount", "currency",
            "vat_treatment", "vat_rate", "tax_id", "payment_terms", "schedule", "flags",
        }))

    check_duplicate(event, billing)
    validate(event)
    trace.write(event.event_id, "validate", {"route": event.route, "flags": event.flags})

    if event.route != Route.INVOICE:
        return f"{event.event_id:24} {event.route.value:8} {'; '.join(event.flags)}"

    customer_id = billing.match_or_create_customer(event.client_name, event.client_email)
    was_duplicate = billing.invoiced_by(event) is not None
    invoice_id = billing.create_draft_invoice(event)
    trace.write(event.event_id, "billing", {
        "customer_id": customer_id,
        "invoice_id": invoice_id,
        "duplicate": was_duplicate,
    })

    covering_email = draft(event)
    trace.write(event.event_id, "draft", {"covering_email": covering_email})

    note = "duplicate, no new invoice" if was_duplicate else "draft invoice + email ready"
    return f"{event.event_id:24} {event.route.value:8} {event.invoice_amount} {event.currency} -> {invoice_id} ({note})"


def run_all() -> list[ContractEvent]:
    """Run every email in the mock inbox through the pipeline. Returns the finished events."""
    inbox = MockInbox()
    billing = MockBilling()
    trace = LocalTrace()

    events = inbox.fetch()
    for event in events:
        email_text = inbox.read_raw(event.raw_ref)
        print(process_one(event, email_text, billing, trace))

    routes = Counter(event.route.value for event in events)
    print("\n" + "  ".join(f"{route}: {count}" for route, count in sorted(routes.items())))
    print(f"trace written to {trace.trace_path}")
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the FinOS pipeline over the mock inbox.")
    parser.add_argument("--mock", action="store_true", help="use the mock inbox and mock billing")
    parser.parse_args()
    run_all()


if __name__ == "__main__":
    main()
