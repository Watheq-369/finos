"""Reads fixtures/slack.json and emits one ContractEvent per TAGGED message.

Stands in for the real Slack app the way MockInbox stands in for Gmail. Only messages
carrying the pickup tag become events; that is the rule the real integration will use
too, so the mock and the real path agree on when a message becomes work. Ordinary
channel chatter is never read as a contract.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from finos.models import ContractEvent, Source, TrustLevel

FIXTURES_PATH = Path("fixtures/slack.json")

# The marker that hands a message to the agent. In real Slack this is the emoji reaction
# the owner adds; the fixture writes the same value down.
PICKUP_TAG = "invoice"


class SlackMock:
    def __init__(self, fixtures_path: Path = FIXTURES_PATH):
        self.messages = json.loads(fixtures_path.read_text())

    def _key(self, message: dict) -> str:
        """Slack's own identity for a message: the channel it is in plus its timestamp."""
        return f"{message['channel']}-{message['ts']}"

    def corpus(self) -> dict[str, dict]:
        """{event_id: fixture entry} for tagged messages. The only place a slack id is minted."""
        return {
            f"slack:{self._key(message)}": message
            for message in self.messages
            if message.get("tag") == PICKUP_TAG
        }

    def fetch(self) -> list[ContractEvent]:
        received_at = datetime.now(timezone.utc)
        return [
            ContractEvent(
                event_id=event_id,
                source=Source.SLACK,
                trust_level=TrustLevel.UNTRUSTED,
                received_at=received_at,
                raw_ref=f"fixtures/slack.json#{self._key(message)}",
            )
            for event_id, message in self.corpus().items()
        ]

    def read_raw(self, raw_ref: str) -> str:
        """Return the message as From / Subject / body, the shape the email adapter returns.

        The first line is built only from what Slack itself vouches for: the poster's
        account email and the channel. Never from the message text. classify.is_internal()
        reads that first line, so nothing a sender types can make their message look like
        it came from our own domain. A Slack display name is user-settable, so it stays
        off the first line too.

        The pickup tag is deliberately absent: a subject line hinting "invoice" would bias
        the classifier, which is exactly what the injection case exists to test.
        """
        key = raw_ref.split("#", 1)[1]
        message = next(m for m in self.messages if self._key(m) == key)
        return (
            f"From: {message['user_email']} (Slack #{message['channel_name']})\n"
            f"Subject: Slack message from {message['user_name']}\n\n"
            f"{message['text']}"
        )
