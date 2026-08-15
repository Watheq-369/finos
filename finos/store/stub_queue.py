"""A local stand-in for the two Lovable review-queue endpoints, which do not exist yet.

Mimics exactly what they will do:

    approved_rows()  ->  GET  /api/public/approved   (status = approved, not yet sent)
    mark_sent()      ->  POST /api/public/mark-sent  (store the invoice id, flip to sent)

Backed by a small JSON file so a second worker run sees the first run's result, the same
way the real table would. Swapping in the HTTP client later is one isolated change behind
the ReviewQueue interface; nothing in the worker moves.
"""

import json
from pathlib import Path

STORE_PATH = Path("runs/review_queue.json")

APPROVED = "approved"
SENT = "sent"


class StubReviewQueue:
    def __init__(self, store_path: Path = STORE_PATH):
        self.store_path = store_path
        self.rows = json.loads(store_path.read_text()) if store_path.exists() else []

    def _save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(self.rows, indent=2) + "\n")

    def approved_rows(self) -> list[dict]:
        """Only what a human approved and that has not gone out yet.

        This filter is the approval gate. A row that is pending, flagged, rejected or
        already sent is never returned, so the worker cannot act on it.
        """
        return [row for row in self.rows if row.get("status") == APPROVED]

    def mark_sent(self, event_id: str, stripe_invoice_id: str) -> None:
        for row in self.rows:
            if row["event_id"] == event_id:
                row["status"] = SENT
                row["stripe_invoice_id"] = stripe_invoice_id
                self._save()
                return
        raise KeyError(f"no review_queue row for {event_id}")
