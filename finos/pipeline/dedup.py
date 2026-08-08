"""Duplicate detection at routing time, before anything reaches billing.

A resend of a contract we have already invoiced is not a new contract. Catching it
here means the route is right, rather than relying on billing to refuse it later.
"""

from finos.interfaces import BillingClient
from finos.models import ContractEvent, Route


def check_duplicate(event: ContractEvent, billing: BillingClient) -> ContractEvent:
    if event.route != Route.INVOICE:
        return event

    invoiced_by = billing.invoiced_by(event)
    # Matching our own earlier invoice just means this run repeated. Only another
    # email claiming the same client, amount and currency is a duplicate.
    if invoiced_by is not None and invoiced_by != event.event_id:
        event.route = Route.REJECT
        event.flags.append(f"duplicate of {invoiced_by}, already invoiced")

    return event
