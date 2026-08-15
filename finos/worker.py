"""The approval-gated worker. Finalises invoices a human already approved. Nothing else.

    python -m finos.worker                           dry run, stub queue, mock billing. Touches nothing.
    python -m finos.worker --http --stripe           dry run against the live queue and real Stripe.
    python -m finos.worker --http --stripe --send    the real thing: finalise and mark sent.

Three locks sit between a contract and a finalised invoice:

1. **The queue.** Only rows a human set to `approved` are ever returned. Pending, flagged,
   rejected and already-sent rows are invisible to this worker.
2. **The flag.** Without `--send` this prints what it would do and calls nothing.
3. **The status check.** An invoice that is not still a draft is skipped, so running twice
   cannot finalise twice.

Finalising is the irreversible step: a draft can be edited or deleted, an open invoice
cannot. It does NOT deliver anything to the customer.
"""

import argparse

import httpx

from finos.billing.mock_billing import MockBilling
from finos.interfaces import BillingClient, ReviewQueue
from finos.store.stub_queue import StubReviewQueue


def process(queue: ReviewQueue, billing: BillingClient, send: bool = False) -> dict:
    """Walk the approved rows. Returns a small tally of what happened."""
    rows = queue.approved_rows()
    tally = {"approved": len(rows), "finalised": 0, "skipped": 0, "would_finalise": 0}

    if not rows:
        print("no approved rows waiting. Nothing to do.")
        return tally

    print(f"{len(rows)} approved row(s) waiting\n")
    for row in rows:
        event_id = row["event_id"]
        invoice_id = row.get("stripe_invoice_id")
        label = f"{event_id} ({row.get('client_name')}, {row.get('invoice_amount')} {row.get('currency')})"

        if not invoice_id:
            print(f"  SKIP  {label}: no stripe_invoice_id on the row")
            tally["skipped"] += 1
            continue

        status = billing.invoice_status(invoice_id)
        if status != "draft":
            # Already acted on. The whole point of checking before finalising.
            print(f"  SKIP  {label}: invoice {invoice_id} is already {status}")
            tally["skipped"] += 1
            continue

        if not send:
            print(f"  would finalise {invoice_id} and mark {event_id} sent")
            tally["would_finalise"] += 1
            continue

        new_status = billing.finalise_invoice(invoice_id)
        queue.mark_sent(event_id, invoice_id)
        print(f"  SENT  {label}: invoice {invoice_id} is now {new_status}, row marked sent")
        tally["finalised"] += 1

    return tally


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Finalise invoices for review-queue rows a human approved.")
    parser.add_argument("--http", action="store_true",
                        help="read the live review queue instead of the local stub")
    parser.add_argument("--stripe", action="store_true",
                        help="use real Stripe in test mode instead of the mock")
    parser.add_argument("--send", action="store_true",
                        help="actually finalise and mark sent. Without this it is a dry run.")
    args = parser.parse_args()

    if args.http:
        # Imported here so the offline path needs neither the endpoints nor the secret.
        from finos.store.http_queue import HttpReviewQueue

        try:
            queue = HttpReviewQueue()
        except RuntimeError as error:
            print(f"\ncannot reach the review queue: {error}")
            raise SystemExit(1)
    else:
        queue = StubReviewQueue()

    if args.stripe:
        # Imported here so a checkout with no Stripe SDK can still run the dry path.
        from finos.billing.stripe import StripeBilling

        try:
            billing = StripeBilling()
        except RuntimeError as error:
            print(f"\ncannot use Stripe: {error}")
            print("Nothing was finalised. Fix STRIPE_RESTRICTED_KEY in .env, or drop --stripe.")
            raise SystemExit(1)
    else:
        billing = MockBilling()

    mode = "SEND (invoices will be finalised)" if args.send else "DRY RUN (nothing will change)"
    engine = "real Stripe, test mode" if args.stripe else "mock billing"
    source = f"live review queue at {queue.base}" if args.http else "local stub queue"
    print(f"worker: {mode}, billing: {engine}, queue: {source}\n")

    try:
        tally = process(queue, billing, send=args.send)
    except httpx.HTTPStatusError as error:
        # Never act on a partial or failed read. Say what happened in plain language.
        code = error.response.status_code
        hint = " (check SEND_SECRET matches the value in Lovable Secrets)" if code == 401 else ""
        print(f"\nreview queue FAILED: the endpoint answered {code} for {error.request.url}{hint}")
        print("Nothing was finalised and nothing was marked sent.")
        raise SystemExit(1)

    print(f"\napproved: {tally['approved']}  finalised: {tally['finalised']}  "
          f"skipped: {tally['skipped']}  would finalise: {tally['would_finalise']}")
    if not args.send and tally["would_finalise"]:
        print("This was a dry run. Re-run with --send to finalise for real.")


if __name__ == "__main__":
    main()
