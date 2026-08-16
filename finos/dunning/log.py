"""What the dunning loop remembers between runs.

The graph is stateless: each run is told what has already been sent. Something has to hold
that between days, and this is it. Without it, every run would see an invoice with an empty
history and send reminder 1 again, for ever.

`runs/dunning.json` is gitignored like the rest of `runs/`, so this is local operator state,
not part of the repo.
"""

import json
from pathlib import Path

from finos.dunning.state import Tier

LOG_PATH = Path("runs/dunning.json")


class DunningLog:
    """{invoice_id: {"reminders_sent": [...], "history": [...]}}"""

    def __init__(self, path: Path = LOG_PATH):
        self.path = path
        self.entries: dict[str, dict] = json.loads(path.read_text()) if path.exists() else {}

    def reminders_sent(self, invoice_id: str) -> list[Tier]:
        return [Tier(t) for t in self.entries.get(invoice_id, {}).get("reminders_sent", [])]

    def record(self, invoice_id: str, state) -> None:
        """Write down what this run decided.

        Only a tier that was actually decided is added to `reminders_sent`. A run that
        concluded "nothing due" or "paid" changes nothing, so re-running the same day is
        harmless and does not burn a tier.

        Be precise about what this records: a tier is marked the moment it is DRAFTED, not
        when a human approves and sends it. Nothing is wired to approval yet, so a draft
        that is never sent still blocks that tier from being offered again. That is the
        safe direction to be wrong in (it under-chases rather than repeating itself), but
        it is not the same as knowing what the client received.
        """
        entry = self.entries.setdefault(invoice_id, {"reminders_sent": [], "history": []})
        entry["history"].append({
            "as_of": state.as_of.isoformat(),
            "action": state.action.value,
            "tier": state.tier.value if state.tier else None,
            "days_overdue": state.days_overdue,
        })
        if state.tier and state.tier.value not in entry["reminders_sent"]:
            entry["reminders_sent"].append(state.tier.value)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.entries, indent=2))
