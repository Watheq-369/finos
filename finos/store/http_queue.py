"""The real review queue: the two scoped Lovable endpoints, behind the ReviewQueue interface.

    approved_rows()  ->  GET  {base}/api/public/approved
    mark_sent()      ->  POST {base}/api/public/mark-sent   {event_id, stripe_invoice_id}

Both bearer-authenticated with SEND_SECRET, which is separate from INGEST_SECRET so the
write-in path and the send-out path can be revoked independently. The database service_role
key stays hidden behind the endpoints and never reaches this process.

Same interface as StubReviewQueue, so the worker cannot tell them apart. Opt-in only:
`python -m finos.worker --http`. Nothing the scorer or the tests run comes near this.
"""

import os

import httpx
from dotenv import load_dotenv

load_dotenv()


def base_url() -> str:
    """Where the review app lives.

    Derived from INGEST_URL by default, because the approved and mark-sent endpoints sit on
    the same app as the ingest one. REVIEW_APP_URL overrides it if they ever diverge.
    """
    explicit = (os.getenv("REVIEW_APP_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    ingest = (os.getenv("INGEST_URL") or "").strip()
    if not ingest:
        raise RuntimeError(
            "Set REVIEW_APP_URL, or INGEST_URL so the app host can be derived from it."
        )
    return ingest.split("/api/public/")[0].rstrip("/")


class HttpReviewQueue:
    def __init__(self, base: str | None = None, secret: str | None = None):
        self.base = (base or base_url()).rstrip("/")
        self.secret = (secret or os.getenv("SEND_SECRET") or "").strip()
        if not self.secret:
            raise RuntimeError("SEND_SECRET must be set in .env to reach the review queue.")

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.secret}"}

    def approved_rows(self) -> list[dict]:
        """Rows the owner approved. A non-200 raises rather than returning a partial list."""
        response = httpx.get(
            f"{self.base}/api/public/approved", headers=self._headers, timeout=30
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise RuntimeError(
                f"expected the approved endpoint to return a list of rows, got {type(rows).__name__}"
            )
        return rows

    def mark_sent(self, event_id: str, stripe_invoice_id: str) -> None:
        response = httpx.post(
            f"{self.base}/api/public/mark-sent",
            json={"event_id": event_id, "stripe_invoice_id": stripe_invoice_id},
            headers=self._headers,
            timeout=30,
        )
        response.raise_for_status()
