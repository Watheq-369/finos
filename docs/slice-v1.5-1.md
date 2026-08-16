# v1.5 Slice 1 - the dunning follow-up loop (LangGraph, mock-first)

Built 16 Aug 2026.

## What this is

The first agentic piece. Everything before it is a straight line: read a message, extract,
route, draft, stop. This one has a real decision with branches, and it runs repeatedly over
the same invoice across days, carrying what happened last time.

It decides the next dunning action for ONE open, unpaid invoice, and it drafts the
follow-up. **It never sends anything.** A human approves the draft, exactly as with invoice
covering emails.

## Scope

In:

- A LangGraph graph over one invoice, one reference date, one decision.
- A configurable cadence constant.
- Three escalating drafts, one per tier.
- Mock payment status behind a swappable seam.
- Six graded scenarios and a must-pass gate.

Out, deliberately:

- Real Stripe invoice reads. `MockPayments` implements the `PaymentStatus` protocol that
  Stripe will implement later.
- Any connection to the review queue. The graph returns a decision; nothing writes it
  anywhere yet.
- Sending. Permanently out, not "not yet".
- Any change to the invoice pipeline, the approval worker, or the Stripe adapter.

## The graph

```
START -> check_paid -+-(paid)---> mark_resolved --------------------------> END
                     |
                     +-(unpaid)-> compute_overdue -> decide_tier -+-(due)--> draft_follow_up -> END
                                                                 |
                                                                 +-(none)-> no_action -------> END
```

Six nodes, two conditional branches. Two shape decisions carry the safety properties:

**`check_paid` runs first.** A paid invoice leaves at the second node, so no arithmetic, no
tier and no draft can be produced for someone who has already paid. Chasing a client for
money they have sent is the worst thing this loop could do, so it is designed out rather
than filtered at the end. The paid scenario in the golden set is deliberately the most
overdue one in the whole set, so a graph that checked payment last would fail loudly.

**There is no cycle edge.** The loop across days is real, but it runs through a human: the
graph stops at a draft, someone approves it, and the next run is invoked with a longer
`reminders_sent`. A cycle inside one invocation would mean the graph sends and re-checks by
itself, which breaks the no-auto-send rule.

## The cadence

`DUNNING_SCHEDULE` in `finos/dunning/schedule.py`, as data:

| Days overdue | Tier |
|---|---|
| 1 | `reminder_1` (gentle) |
| 2 | `reminder_2` (firmer) |
| 4 | `escalation` (formal) |

Two rules make up the whole cadence: a tier is due once its threshold is reached, and a tier
already sent is never sent again. Under 1 day overdue, nothing is due.

`next_tier` takes the LAST qualifying tier, not the first. An invoice first seen at 4 days
overdue escalates rather than opening with a nudge that is already four days stale. It never
skips a tier that was actually sent.

## Determinism

`as_of` is a required field on the state. Nothing in the loop reads the clock, so a test or
a demo can simulate any day and get the same answer tomorrow. The drafts go through the
existing temperature-0 cached LLM wrapper. The test suite stubs the drafter entirely, so it
runs offline with no key in under a second.

## Grading

`fixtures/dunning.json`, six scenarios: not overdue, 1 day, 2 days, 4 days, already paid,
already escalated. Graded on `action`, `tier` and `days_overdue` - 18 fields. A right answer
reached from the wrong number of days is luck, so the day count is graded too.

Drafts are checked deterministically for the four facts each must state: client, amount,
currency and days overdue. This caught two real gaps on the first run, where the drafts gave
the due date instead of the day count.

Gates: `dunning tier correct on all scenarios` (new, 8th) and the existing draft gate,
widened to `no draft with a placeholder or a missing fact`.

## Honest note on LangGraph

This flow is four steps and two branches. As plain Python it is about thirty readable lines,
and LangGraph makes it longer, not shorter. It earns its place as the scaffolding for what
comes next - durable state across runs, and human-in-the-loop interrupts - not because this
particular loop demands a graph engine today.
