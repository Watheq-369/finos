"""Run the dunning loop over every open Stripe invoice, once, for one date.

    python -m finos.dunning.run --stripe
    python -m finos.dunning.run --stripe --as-of 2026-09-18

Reads the finalised, unpaid invoices from Stripe, asks the graph what to do about each one
as of the reference date, prints a table, and writes what it decided to runs/dunning.json so
the next run knows which tiers have already been used.

It drafts. It never sends. Every reminder still needs a human.

`--stripe` is opt-in and `--as-of` defaults to today, so a demo can simulate any date without
touching a clock inside the logic.
"""

import argparse
from datetime import date

from finos.dunning.graph import decide
from finos.dunning.log import DunningLog
from finos.dunning.state import DunningInvoice

HEADER = f"{'CLIENT':30} {'AMOUNT':>14} {'DUE':>10} {'OVERDUE':>8} {'TIER':>12}  NEXT ACTION"


def row_for(invoice: DunningInvoice, state) -> str:
    amount = f"{invoice.amount:,.2f} {invoice.currency}"
    overdue = "-" if state.days_overdue is None else f"{state.days_overdue}d"
    tier = state.tier.value if state.tier else "-"
    return (f"{invoice.client_name[:30]:30} {amount:>14} {invoice.due_date.isoformat():>10} "
            f"{overdue:>8} {tier:>12}  {state.reason}")


def run_dunning(invoices: list[DunningInvoice], as_of: date, payments,
                log: DunningLog) -> list[tuple[DunningInvoice, object]]:
    """Decide for every invoice. Returns the (invoice, finished state) pairs.

    Takes its inputs rather than fetching them, so the whole loop can be exercised offline
    with fake invoices and a fake payment source.
    """
    results = []
    for invoice in invoices:
        state = decide(
            invoice=invoice,
            reminders_sent=log.reminders_sent(invoice.invoice_id),
            as_of=as_of,
            payments=payments,
        )
        log.record(invoice.invoice_id, state)
        results.append((invoice, state))
    return results


def print_table(results) -> None:
    if not results:
        print("no open invoices in Stripe. Nothing to chase.")
        return
    print(HEADER)
    print("-" * len(HEADER))
    for invoice, state in results:
        print(row_for(invoice, state))

    drafted = [(i, s) for i, s in results if s.draft_email]
    print(f"\n{len(results)} open invoice(s), {len(drafted)} reminder(s) drafted, "
          f"awaiting approval. Nothing was sent.")
    for invoice, state in drafted:
        print(f"\n--- {invoice.client_name} / {state.tier.value} "
              f"({state.days_overdue} days overdue) ---")
        print(state.draft_email)


def main() -> None:
    parser = argparse.ArgumentParser(description="Decide the next dunning action per open invoice.")
    parser.add_argument("--stripe", action="store_true",
                        help="read real open invoices from Stripe in test mode")
    parser.add_argument("--as-of", dest="as_of", default=None,
                        help="reference date, YYYY-MM-DD. Defaults to today.")
    args = parser.parse_args()

    if not args.stripe:
        print("this runner reads real invoices and needs --stripe.")
        print("The offline scenarios are covered by `python -m finos.score`.")
        raise SystemExit(1)

    # Imported here so a checkout with no Stripe SDK and no key can still run the suite.
    from finos.dunning.stripe_payments import StripePayments

    try:
        payments = StripePayments()
    except RuntimeError as error:
        print(f"\ncannot use Stripe: {error}")
        print("Nothing was read. Fix STRIPE_RESTRICTED_KEY in .env.")
        raise SystemExit(1)

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    print(f"dunning run as of {as_of.isoformat()} (real Stripe, test mode, drafts only)\n")

    log = DunningLog()
    results = run_dunning(payments.open_invoices(), as_of, payments, log)
    print_table(results)
    log.save()
    print(f"\ndecisions written to {log.path}")


if __name__ == "__main__":
    main()
