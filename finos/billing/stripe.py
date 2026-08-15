"""Real Stripe client, the billing system of record. Dormant stub until Slice B.

Stripe owns invoice numbering, tax and payment tracking. We drive it through its API with
a RESTRICTED key that lives only in the worker's .env, never in the browser. Nothing here
is ever called without a human approving the row first.

Mock billing is what runs today.
"""

from finos.models import ContractEvent


class StripeBilling:
    def match_or_create_customer(self, name: str, email: str | None) -> str:
        raise NotImplementedError("Real Stripe arrives in Slice B.")

    def create_draft_invoice(self, event: ContractEvent) -> str:
        raise NotImplementedError("Real Stripe arrives in Slice B.")

    def invoiced_by(self, event: ContractEvent) -> str | None:
        raise NotImplementedError("Real Stripe arrives in Slice B.")
