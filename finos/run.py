"""Orchestrator. Runs every email in the mock inbox through the pipeline and writes a trace.

Nothing is ever sent. INVOICE cases end at a draft invoice and a draft email, waiting for a human.

    python -m finos.run --mock
"""

import argparse
from collections import Counter

import httpx

from finos.adapters.mock_inbox import MockInbox
from finos.adapters.slack_mock import SlackMock
from finos.billing.mock_billing import MockBilling
from finos.interfaces import SourceAdapter
from finos.models import ContractEvent, Route, Source
from finos.pipeline.classify import classify
from finos.pipeline.dedup import check_duplicate
from finos.pipeline.draft import draft
from finos.pipeline.extract import extract
from finos.pipeline.validate import validate
from finos.store.ingest import IngestClient, rows_for
from finos.store.local_trace import LocalTrace


def process_one(
    event: ContractEvent,
    email_text: str,
    billing: MockBilling,
    trace: LocalTrace,
    drafts: dict[str, str],
    invoice_ids: dict[str, str],
) -> str:
    """Run one email through every stage. Returns the one-line summary.

    Any covering email written along the way is recorded in `drafts`, and the invoice id
    in `invoice_ids`, so the review queue can show the owner what would go out and the
    worker knows which invoice to finalise once they approve it.
    """
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
    invoice_ids[event.event_id] = invoice_id
    trace.write(event.event_id, "billing", {
        "customer_id": customer_id,
        "invoice_id": invoice_id,
        "duplicate": was_duplicate,
    })

    covering_email = draft(event)
    drafts[event.event_id] = covering_email
    trace.write(event.event_id, "draft", {"covering_email": covering_email})

    note = "duplicate, no new invoice" if was_duplicate else "draft invoice + email ready"
    return f"{event.event_id:24} {event.route.value:8} {event.invoice_amount} {event.currency} -> {invoice_id} ({note})"


def sources() -> dict[Source, SourceAdapter]:
    """Every signal source this slice reads, keyed by the source its events carry.

    The one place adapters are built. Order matters: sources are read in this order, and
    dedup treats the first contract it sees as the original.
    """
    return {Source.GMAIL: MockInbox(), Source.SLACK: SlackMock()}


def run_all(push: bool = False, use_stripe: bool = False) -> list[ContractEvent]:
    """Run every message from every source through the pipeline. Returns the finished events.

    `push` and `use_stripe` are both opt-in, so the scorer and the tests never touch the
    network and never need a key. Billing stays mocked unless you ask for Stripe by name.
    """
    adapters = sources()
    if use_stripe:
        # Imported here, not at module load, so a checkout with no Stripe SDK and no key
        # can still run the whole offline suite.
        from finos.billing.stripe import StripeBilling

        try:
            billing = StripeBilling()
        except RuntimeError as error:
            # Config problem, not a crash. Say it plainly instead of dumping a traceback.
            print(f"\ncannot use Stripe: {error}")
            print("Nothing was sent to Stripe. Fix STRIPE_RESTRICTED_KEY in .env, or drop "
                  "--stripe to run on the mock.")
            raise SystemExit(1)
        print("billing: REAL Stripe (test mode). Drafts only, nothing is finalised or sent.\n")
    else:
        billing = MockBilling()
    trace = LocalTrace()
    drafts: dict[str, str] = {}
    invoice_ids: dict[str, str] = {}

    events = [event for adapter in adapters.values() for event in adapter.fetch()]
    for event in events:
        message_text = adapters[event.source].read_raw(event.raw_ref)
        print(process_one(event, message_text, billing, trace, drafts, invoice_ids))

    routes = Counter(event.route.value for event in events)
    print("\n" + "  ".join(f"{route}: {count}" for route, count in sorted(routes.items())))
    print(f"trace written to {trace.trace_path}")

    if push:
        # Pipeline-owned columns only. The Stripe ids captured above are NOT pushed here:
        # stripe_invoice_id belongs to the status sync, which writes it and stripe_status
        # on their own. Mixing them into this payload is what let a re-push clobber
        # columns it did not own.
        rows = rows_for(events, drafts)
        try:
            result = IngestClient().push(rows)
            print(f"\npushed {len(rows)} rows to the ingest endpoint")
            print(f"endpoint response: {result}")
        except httpx.HTTPStatusError as error:
            # The trace above is already written, so nothing is lost. Say what happened plainly.
            print(f"\npush FAILED: the endpoint answered {error.response.status_code} "
                  f"for {error.request.url}")
            print(f"{len(rows)} rows were not sent. The local trace is unaffected.")
            raise SystemExit(1)
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the FinOS pipeline over the mock inbox.")
    parser.add_argument("--mock", action="store_true", help="use the mock inbox and mock billing")
    parser.add_argument("--push", action="store_true", help="also push the results to the review queue")
    parser.add_argument("--stripe", action="store_true",
                        help="bill through real Stripe in test mode instead of the mock (drafts only)")
    args = parser.parse_args()
    run_all(push=args.push, use_stripe=args.stripe)


if __name__ == "__main__":
    main()
