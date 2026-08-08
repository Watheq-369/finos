"""Mock billing. Logs instead of calling QuickBooks, and refuses to invoice the same thing twice.

The store is a small JSON file so that re-running the whole set does not create duplicates.
"""

import json
from pathlib import Path

from finos.models import ContractEvent

STORE_PATH = Path("runs/mock_invoices.json")


def _signature(event: ContractEvent) -> str:
    """What makes two invoices the same invoice: client, amount, currency."""
    return f"{(event.client_name or '').strip().lower()}|{event.amount}|{event.currency}"


class MockBilling:
    def __init__(self, store_path: Path = STORE_PATH):
        self.store_path = store_path
        if store_path.exists():
            store = json.loads(store_path.read_text())
        else:
            store = {"customers": {}, "invoices": {}}
        self.customers = store["customers"]  # name -> customer id
        self.invoices = store["invoices"]  # signature -> invoice id

    def _save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(
            json.dumps({"customers": self.customers, "invoices": self.invoices}, indent=2)
        )

    def match_or_create_customer(self, name: str, email: str | None) -> str:
        key = name.strip().lower()
        if key not in self.customers:
            self.customers[key] = f"cust-{len(self.customers) + 1:03d}"
            self._save()
        return self.customers[key]

    def is_duplicate(self, event: ContractEvent) -> bool:
        return _signature(event) in self.invoices

    def create_draft_invoice(self, event: ContractEvent) -> str:
        signature = _signature(event)
        if signature not in self.invoices:
            self.invoices[signature] = f"inv-{len(self.invoices) + 1:03d}"
            self._save()
        return self.invoices[signature]
