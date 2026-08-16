"""The three follow-up drafts, one per tier.

Same discipline as the invoice covering email: the model is handed facts and writes prose,
it is never asked to work out whether to chase or how hard. That decision is already made
by the time this runs, so a bad draft can be rewritten without touching the cadence.

Every draft must name the real client, amount, currency and days overdue. No placeholders.
"""

from finos.dunning.state import DunningState, Tier
from finos.llm import MODEL_EXTRACT, ask_text

SHARED_RULES = """
Use only the facts given. Never invent a date, a figure, a penalty or a legal threat.
Always name the client and state the amount with its currency exactly as given.
Always say how many days overdue the invoice is, using the Days overdue number you are
given, written as a number followed by "day" or "days", for example "3 days overdue". The
due date on its own is not enough; the reader must be told the number of days.
Never write a placeholder such as [Client's Name] or [amount].
Keep it short, a few sentences. Sign off as Younes.
Reply with the email body only, no subject line and no preamble."""

TIER_PROMPTS = {
    Tier.REMINDER_1: """You write the first, gentle payment reminder for an unpaid invoice.

Assume good faith: it has almost certainly been overlooked. Friendly, light, no pressure.
Do not mention consequences.""" + SHARED_RULES,

    Tier.REMINDER_2: """You write the second payment reminder for an invoice that is still unpaid.

A previous gentle reminder has already gone out and been ignored. Firmer and more direct
than the first, still polite and still assuming good faith. Ask for a payment date.
Do not threaten anything.""" + SHARED_RULES,

    Tier.ESCALATION: """You write the final escalation for a significantly overdue invoice.

Two reminders have already gone unanswered. Formal and businesslike, no warmth or
small talk. State the position plainly and ask them to escalate it internally to whoever
can release the payment. Request a response by a specific commitment from them, but do not
invent a deadline date, a penalty, an interest charge or any legal action.""" + SHARED_RULES,
}


def facts_for(state: DunningState) -> str:
    """Everything the drafter is allowed to rely on, and nothing else."""
    invoice = state.invoice
    return (
        f"Client: {invoice.client_name}\n"
        f"Amount outstanding: {invoice.amount} {invoice.currency}\n"
        f"Invoice due date: {invoice.due_date.isoformat()}\n"
        f"Days overdue: {state.days_overdue}\n"
        f"Reminders already sent: {[tier.value for tier in state.reminders_sent] or 'none'}"
    )


def draft_for_tier(state: DunningState) -> str:
    return ask_text(MODEL_EXTRACT, TIER_PROMPTS[state.tier], facts_for(state))
