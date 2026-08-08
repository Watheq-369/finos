"""Stage 3: cheap rule checks, no LLM. Anything missing means abstain, not guess.

First pass only. The full set of abstain rules lands in Slice 1.
"""

from finos.models import ContractEvent, Route

REQUIRED_FIELDS = {
    "client_name": "no client name",
    "amount": "no amount",
    "currency": "no currency",
}


def validate(event: ContractEvent) -> ContractEvent:
    if event.route != Route.INVOICE:
        return event

    missing = [reason for field, reason in REQUIRED_FIELDS.items() if getattr(event, field) is None]
    if missing:
        event.route = Route.FLAG
        event.flags.extend(missing)

    return event
