"""Stage 4: write the covering email that goes out with the invoice.

This drafts only. Nothing is ever sent without a human approving it.
"""

from finos.llm import MODEL_EXTRACT, ask_text
from finos.models import ContractEvent

SYSTEM_PROMPT = """You write the short covering email a consultant sends with an invoice.

Use only the billing facts given to you. Do not invent figures, dates or terms.
Keep it to a few sentences, warm but businesslike, and sign off as Younes.
Reply with the email body only, no subject line and no preamble."""


def draft(event: ContractEvent) -> str:
    facts = (
        f"Client: {event.client_name}\n"
        f"Contact: {event.client_email}\n"
        f"Amount to invoice now: {event.invoice_amount} {event.currency}\n"
        f"VAT treatment: {event.vat_treatment.value}\n"
        f"Payment terms: {event.payment_terms}\n"
        f"Schedule: {[item.model_dump() for item in event.schedule]}"
    )
    return ask_text(MODEL_EXTRACT, SYSTEM_PROMPT, facts)
