"""Real Gmail adapter. Dormant future stub, not wired and not built.

Kept deliberately: it is the worked example of the swap-a-source pattern. Slack is the
one live source for v1; a second source becomes a new adapter behind SourceAdapter plus
one line in run.sources(), never a rewrite of the pipeline.
"""

from finos.models import ContractEvent


class GmailInbox:
    def fetch(self) -> list[ContractEvent]:
        raise NotImplementedError("Gmail is a dormant future source, not built.")

    def read_raw(self, raw_ref: str) -> str:
        raise NotImplementedError("Gmail is a dormant future source, not built.")
