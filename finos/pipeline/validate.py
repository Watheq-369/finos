"""Stage 3: the abstain rules. Rule-based, no LLM.

The extractor reports what it found and what looked wrong. This is the only place
that turns those signals into a route. When anything is off, we abstain and flag.
"""

from finos.models import ContractEvent, Route

CONFIDENCE_THRESHOLD = 0.7


def validate(event: ContractEvent) -> ContractEvent:
    if event.route == Route.INVOICE:
        reasons = []

        # The extractor already reported problems it saw (missing currency, a range,
        # figures in an attachment, terms in an MSA, addressed to someone else).
        if event.flags:
            reasons.extend(event.flags)

        if event.invoice_amount is None:
            reasons.append("no amount to invoice")
        if event.currency is None:
            reasons.append("no currency")
        if event.confidence.get("classify", 1.0) < CONFIDENCE_THRESHOLD:
            reasons.append("low confidence on the route")

        if reasons:
            event.route = Route.FLAG
            event.flags = reasons

    # If we are not invoicing, there is no amount to invoice. Never leave a stale figure.
    if event.route != Route.INVOICE:
        event.invoice_amount = None

    return event
