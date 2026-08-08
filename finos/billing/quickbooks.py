"""Real QuickBooks client. Stub until Slice 3 — mock billing is what runs today."""

from finos.models import ContractEvent


class QuickBooksBilling:
    def match_or_create_customer(self, name: str, email: str | None) -> str:
        raise NotImplementedError("Real QuickBooks arrives in Slice 3.")

    def create_draft_invoice(self, event: ContractEvent) -> str:
        raise NotImplementedError("Real QuickBooks arrives in Slice 3.")
