"""Real Gmail adapter. Stub until Slice 3 — the mock inbox is what runs today."""

from finos.models import ContractEvent


class GmailInbox:
    def fetch(self) -> list[ContractEvent]:
        raise NotImplementedError("Real Gmail arrives in Slice 3.")

    def read_raw(self, raw_ref: str) -> str:
        raise NotImplementedError("Real Gmail arrives in Slice 3.")
