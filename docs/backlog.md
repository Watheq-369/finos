# FinOS Backlog (living tracker)

The single place every discovery lands: blind spots, caveats, bugs, ideas, deviations, removals. From Younes, from Claude (chat), or from Claude Code during a build.

**The rule: if it is not in this file, it does not exist.** The moment something surfaces, it gets one line here. Reviewed at the start and end of every slice: what moved into scope, what got done, what is still parked.

**Where things live (so the backlog stays a tracker, not a dumping ground):**
- Permanent rules and principles go in `CLAUDE.md`.
- Scope for a slice goes in `docs/slice-N.md`.
- High-level state and decisions go in the project doc.
- Everything discovered-but-not-yet-placed goes here, tagged with where it belongs and a status.

Status tags: `[open]` `[in progress]` `[done]` `[dropped]`.

---

## Current (Slice 0 into Slice 1)

- `[done]` Add expected extraction fields to fixtures (golden set for Slice 1).
- `[in progress]` Slice 0 hardening: temperature 0, route scorer command, LLM response cache, `.gitignore` (exclude .env/.venv/__pycache__/runs), git init + first commit.
- `[open]` msg-005: currency invented as AED instead of abstaining. Core north-star miss. Fix in Slice 1 abstain rules.
- `[open]` msg-016 and msg-018 routed INVOICE, should be FLAG (terms hidden in an MSA; email addressed to the wrong person). Slice 1.
- `[open]` msg-014: internal email routed HOLD not REJECT. Classifier not distinguishing internal from client mail. Slice 1.
- `[open]` The six hardened abstain rules (the FLAG conditions). Slice 1.
- `[open]` Write `docs/slice-1.md` before starting Slice 1.

## Upcoming slices

- `[open]` Slice 2: Lovable review UI (approve/send/flag) + Supabase trace store. Also clears Builder "ship v1". Navy editorial, not the dark demo look.
- `[open]` Slice 3: real Gmail read + QuickBooks sandbox, with idempotency. OAuth is the friction point.
- `[open]` Slice 4: full TRACE eval suite (LLM judge + trajectory grading) and CI (auto-run tests on commit).
- `[open]` Runbook / README so a stranger could run it. The handoff artifact. Before demo day.

## Later phases

- `[open]` v1.5 follow-up: reconciliation freshness guard (fixes the "you haven't paid" race condition), 3-tier escalation, run as a live Hermes agent. Document the dunning cadence first.
- `[open]` v2 weekly AR report + dashboard. "Anything off" = explicit threshold rules, labelled as rules not AI.
- `[open]` Phase 0: expenses, cash position, forecast. Needs the bank feed wired and categorisation rules written. Fails both readiness gates today.
- `[open]` Phase 2: RAG over VAT / e-invoicing rules to validate by market.
- `[open]` Memory reframed to bounded, human-confirmed learned defaults. Never silent behaviour change on money.

## Open questions / assumptions to confirm

- `[open]` Hermes: can it run scheduled and reach Gmail, QuickBooks, and Supabase? If not, n8n. Affects v1.5.
- `[open]` QuickBooks sandbox allows the invoice-write API on the free tier (assumed yes per Intuit docs). Confirm at Slice 3.

## Deviations logged (accepted, on purpose)

- Mock invoice store persists to `runs/mock_invoices.json` (spec said in-memory; cross-run dedup needs persistence). Accepted.
- Pipeline stages take the email body as a second argument (`raw_ref` is a pointer, body passed separately). Accepted, keeps the canonical object clean.
