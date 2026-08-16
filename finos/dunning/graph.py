"""The dunning follow-up loop, as a LangGraph graph.

One invocation answers one question about one invoice: what should happen next, as of a
given date? It decides and it drafts. It never sends. A human approves the draft, and the
fact that a reminder went out comes back in as `reminders_sent` on the NEXT run.

    START -> check_paid -+-(paid)---> mark_resolved ----------------> END
                         |
                         +-(unpaid)-> compute_overdue -> decide_tier -+-(tier due)-> draft_follow_up -> END
                                                                     |
                                                                     +-(nothing)--> no_action ------> END

Two things about the shape are deliberate:

`check_paid` runs FIRST, before anything is computed or drafted. A paid invoice leaves the
graph at the second node, so no arithmetic, no tier and no draft can happen for someone who
has already paid. Chasing a client for money they have sent is the failure this loop must
never produce, so it is designed out rather than checked for at the end.

There is no cycle edge back to `check_paid`. The loop across days is real, but it runs
through a human: the graph stops at a draft, someone approves it, and the next run is
invoked with a longer `reminders_sent`. A cycle inside one invocation would imply the graph
sends and re-checks by itself, which is exactly the no-auto-send rule this system keeps.
"""

from langgraph.graph import END, START, StateGraph

from finos.dunning.drafts import draft_for_tier
from finos.dunning.payments import MockPayments, PaymentStatus
from finos.dunning.schedule import DUNNING_SCHEDULE, days_overdue, next_tier
from finos.dunning.state import Action, DunningState, Tier

# The threshold of the gentlest tier. Read from the schedule so the explanation in
# `_no_action` cannot drift away from the cadence it is describing.
DUNNING_MIN_DAYS = DUNNING_SCHEDULE[0][0]

# --- nodes. Each returns only the fields it sets. ---


def _check_paid(state: DunningState, payments: PaymentStatus) -> dict:
    return {"is_paid": payments.is_paid(state.invoice.invoice_id)}


def _mark_resolved(state: DunningState) -> dict:
    return {"action": Action.RESOLVED, "reason": "invoice is paid, nothing to chase"}


def _compute_overdue(state: DunningState) -> dict:
    return {"days_overdue": days_overdue(state.invoice.due_date, state.as_of)}


def _decide_tier(state: DunningState) -> dict:
    return {"tier": next_tier(state.days_overdue, state.reminders_sent)}


def _draft_follow_up(state: DunningState) -> dict:
    return {
        "action": Action.SEND_REMINDER,
        "draft_email": draft_for_tier(state),
        "reason": f"{state.days_overdue} days overdue, {state.tier.value} is due",
    }


def _no_action(state: DunningState) -> dict:
    if state.days_overdue < DUNNING_MIN_DAYS:
        reason = f"only {state.days_overdue} days overdue, first reminder is not due yet"
    else:
        reason = "every tier in the schedule has already been sent"
    return {"action": Action.NONE, "reason": reason}


# --- edges. The two decisions that give the graph its shape. ---


def _route_on_payment(state: DunningState) -> str:
    return "mark_resolved" if state.is_paid else "compute_overdue"


def _route_on_tier(state: DunningState) -> str:
    return "draft_follow_up" if state.tier else "no_action"


def build_dunning_graph(payments: PaymentStatus | None = None):
    """Wire the graph. `payments` is injected so Stripe can replace the mock later."""
    payments = payments or MockPayments()

    builder = StateGraph(DunningState)
    builder.add_node("check_paid", lambda state: _check_paid(state, payments))
    builder.add_node("mark_resolved", _mark_resolved)
    builder.add_node("compute_overdue", _compute_overdue)
    builder.add_node("decide_tier", _decide_tier)
    builder.add_node("draft_follow_up", _draft_follow_up)
    builder.add_node("no_action", _no_action)

    builder.add_edge(START, "check_paid")
    builder.add_conditional_edges("check_paid", _route_on_payment,
                                  ["mark_resolved", "compute_overdue"])
    builder.add_edge("compute_overdue", "decide_tier")
    builder.add_conditional_edges("decide_tier", _route_on_tier,
                                  ["draft_follow_up", "no_action"])
    builder.add_edge("mark_resolved", END)
    builder.add_edge("draft_follow_up", END)
    builder.add_edge("no_action", END)

    return builder.compile()


def decide(invoice, reminders_sent: list[Tier], as_of, payments: PaymentStatus | None = None
           ) -> DunningState:
    """Run the graph once for one invoice. Returns the finished state."""
    graph = build_dunning_graph(payments)
    result = graph.invoke(
        DunningState(invoice=invoice, reminders_sent=reminders_sent, as_of=as_of)
    )
    # LangGraph hands back a plain dict of the final state; re-validate so callers get the
    # same typed object they passed in.
    return DunningState.model_validate(result)
