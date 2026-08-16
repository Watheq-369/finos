"""Push each invoice's current Stripe status to the review app, so the money tiles populate.

    python -m finos.dunning.status_sync                 dry run, prints what it would send
    python -m finos.dunning.status_sync --push          actually sends it

Stripe is the system of record for whether an invoice is draft, open, paid or void. The
dashboard should show what Stripe says, not a copy that drifts. This reads the status from
Stripe and writes it to the existing `POST /api/public/ingest` endpoint, which upserts on
`event_id`, into its `stripe_status` field.

The match between a Stripe invoice and a review-queue row is the `finos_event_id` stamped
into invoice metadata at creation. That is why the review app needs no read-everything
endpoint for this to work.

Opt-in and read-only on the Stripe side: nothing here creates, finalises, voids or sends.
"""

import argparse

from finos.store.ingest import IngestClient


def rows_for(statuses_by_event: dict[str, dict]) -> list[dict]:
    """The smallest row that names a status.

    Only the key and the two fields being updated are sent. Everything else the row holds
    (the draft, the flags, the approval status a human set) is deliberately absent so the
    upsert cannot overwrite it with nulls.
    """
    return [
        {
            "event_id": event_id,
            "stripe_invoice_id": found["invoice_id"],
            "stripe_status": found["status"],
        }
        for event_id, found in sorted(statuses_by_event.items())
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Stripe invoice status to the review app.")
    parser.add_argument("--push", action="store_true",
                        help="actually send. Without this it prints what it would send.")
    args = parser.parse_args()

    from finos.dunning.stripe_payments import StripePayments

    try:
        payments = StripePayments()
    except RuntimeError as error:
        print(f"\ncannot use Stripe: {error}")
        raise SystemExit(1)

    rows = rows_for(payments.statuses_by_event())
    if not rows:
        print("no Stripe invoices carry a finos_event_id. Nothing to sync.")
        return

    print(f"{len(rows)} invoice status(es) from Stripe:\n")
    for row in rows:
        print(f"  {row['event_id']:40} {row['stripe_status']:8} {row['stripe_invoice_id']}")

    if not args.push:
        print("\nDry run. Nothing was sent. Re-run with --push to sync.")
        return

    import httpx

    try:
        result = IngestClient().push(rows)
    except httpx.HTTPStatusError as error:
        print(f"\nsync FAILED: the endpoint answered {error.response.status_code} "
              f"for {error.request.url}")
        print("Nothing was synced.")
        raise SystemExit(1)
    print(f"\npushed {len(rows)} status update(s)")
    print(f"endpoint response: {result}")


if __name__ == "__main__":
    main()
