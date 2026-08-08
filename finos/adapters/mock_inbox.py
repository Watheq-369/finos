"""Reads fixtures/emails.json and emits one ContractEvent per entry. Stands in for Gmail until Slice 3."""

import json
from datetime import datetime, timezone
from pathlib import Path

from finos.models import ContractEvent, Source, TrustLevel

FIXTURES_PATH = Path("fixtures/emails.json")


class MockInbox:
    def __init__(self, fixtures_path: Path = FIXTURES_PATH):
        self.emails = json.loads(fixtures_path.read_text())

    def fetch(self) -> list[ContractEvent]:
        received_at = datetime.now(timezone.utc)
        return [
            ContractEvent(
                event_id=f"gmail:{email['message_id']}",
                source=Source.GMAIL,
                trust_level=TrustLevel.UNTRUSTED,
                received_at=received_at,
                raw_ref=f"fixtures/emails.json#{email['message_id']}",
            )
            for email in self.emails
        ]

    def read_raw(self, raw_ref: str) -> str:
        """Return the message text a raw_ref points at, as From / Subject / Body."""
        message_id = raw_ref.split("#", 1)[1]
        email = next(e for e in self.emails if e["message_id"] == message_id)
        return f"From: {email['from']}\nSubject: {email['subject']}\n\n{email['body']}"
