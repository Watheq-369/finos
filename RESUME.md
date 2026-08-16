# RESUME - where we are and what to do next

**Last session: 16 Aug 2026.** Slices 0, 1, 2, 4, A, B1, B2 (Moves A and C), the deepened evals, and v1.5 Slice 1 are shipped and pushed. 81 tests green, all 8 must-pass gates pass, `python -m finos.score` exits 0 on a clean checkout with no key. CI runs the whole suite from the committed LLM cache on every push.

**The whole loop is proven, with no hand-seeding.** The pipeline wrote the row, the review UI approved it, and the worker finalised it. `run --mock --stripe --push` reported `inserted: 0, updated: 16` and created no new Stripe invoices; `GET /api/public/approved` then returned exactly one row, `gmail:msg-002` Barcelona Retail Group S.L. EUR 15,000, carrying the `stripe_invoice_id` the pipeline itself had stored. The worker finalised that invoice `draft` -> `open` and marked the row sent.

Verified against before/after Stripe snapshots rather than from log output: 10 invoices before and after, none created or deleted, exactly one row changed, the other nine identical field for field, no duplicate signatures. No customer delivery (`auto_advance=False`, `attempted=False`, `amount_paid=0`, `paid_at=None`). Re-running the worker afterwards returned "no approved rows waiting", so `mark_sent` took effect and the same invoice cannot be finalised twice.

This supersedes the 15 Aug caveat: that proof used a row seeded by hand in the Supabase SQL editor. This one did not. All three review-app bugs are fixed Lovable-side.

**Eval suite deepened (16 Aug).** The corpus is now 29 cases (27 email + 2 Slack), up from 22. Seven harder extraction fixtures were added: an approximate amount, a second currency conflict, a multi-line German VAT block, a four-milestone percentage drawdown, a near-duplicate from a client already invoiced, and a near-miss recipient name. A new per-market VAT section grades treatment, rate and tax id for DE, ES and AE. The judge now faces a second frozen bad draft that is fluent and placeholder-free but bills the wrong number, so it is tested on factual errors, not just template artefacts. The pipeline got every new case right on the first run.

## Done so far

- **Slice A** - pivot to Slack in / Stripe out; Slack source adapter mock-first; prompt-injection case and a `no injected instruction obeyed` gate.
- **Slice B1** - `StripeBilling` behind `BillingClient`, drafts only, idempotent on a client|amount|currency signature stored in Stripe metadata. Hard stop on any key that is not `rk_test_`/`sk_test_`.
- **Slice B2 Move A** - the approval-gated worker, three independent locks: the queue only returns approved rows, `--send` is required, and Stripe's own status is checked before finalising.
- **Slice B2 Move C** - `HttpReviewQueue` against the two live bearer-authenticated endpoints. A failed read exits 1 and never looks like an empty queue.

## Done: Slice 4 - Evals (the TRACE loop)

Built per `docs/slice-4.md`: trajectory grading, an LLM judge on draft quality validated against hand labels, a failure taxonomy, and six must-pass gates. `python -m finos.score` exits 0 with all gates passing; 23 tests green offline.

The msg-002 schedule blind spot is closed: the extractor was copying the "50% upfront" example onto a three-milestone contract. Schedule is now graded by instalment count against the golden set and is 9/9, with a must-pass gate.

## Closed on 16 Aug - the three review-app bugs

All three are fixed Lovable-side and verified from this repo:

1. **`/api/public/ingest` now stores `stripe_invoice_id`.** Verified by reading the row back through `/api/public/approved` and finding the id the pipeline had just written.
2. **The Approve button now writes `status = 'approved'`.** Verified when an approved row appeared in `GET /api/public/approved`.
3. **`run --push` no longer resets `status` on existing rows.** Verified by approving a row, running a full 16-row push over it, and finding it still approved afterwards.

The correct Lovable account is reconnected.

## Housekeeping before any demo

Four Stripe test invoices are now `open` (Nordwind, Falcon, Velasco, Barcelona). An open invoice can be voided but never returned to draft. For a clean demo run, void them and let the pipeline create fresh drafts.

## Done: v1.5 Slice 1 - the dunning loop (16 Aug)

The first agentic piece. A LangGraph graph decides the next dunning action for one open unpaid invoice, as of a date passed in, and drafts the follow-up. It never sends. Spec and the graph diagram are in `docs/slice-v1.5-1.md`.

Six nodes, two branches. `check_paid` runs first, so a paid invoice exits before any tier or draft exists. No cycle edge: the day-to-day loop runs through a human approval and re-invocation. Cadence is a `DUNNING_SCHEDULE` constant (1 day gentle, 2 days firmer, 4 days formal). Six graded scenarios, 18/18, plus a new must-pass gate.

Not wired to anything real yet: `MockPayments` reads a fixture, and no code reads open invoices from Stripe or writes a dunning decision to the review queue.

## Next

Two candidates, your call:

1. **Wire the dunning loop to something real** - read open invoices from Stripe via the `PaymentStatus` seam, and record approved reminders so `reminders_sent` advances by itself. Without this the loop cannot actually progress a tier in production.
2. **Slice C** (`docs/slice-3.md`) - swap the mock Slack reader for a real read of a TAGGED message. Still parked; it was skipped, not replaced.

**Do not start either without an explicit go.**

## To resume in Claude Code (VS Code)

1. Open the `ai-bootcamp` folder in VS Code, open the Claude Code panel.
2. Check the footer: model Opus 5, mode Auto, effort High.
3. If you will step away, run `caffeinate -i` in a Terminal tab (keeps the Mac awake).
4. Paste the kickoff line below.

## Kickoff line that built Slice 4 (already run, kept for reference)

```
Advance the slice pointer in CLAUDE.md to Slice 4 (spec: docs/slice-4.md), then build Slice 4 per that spec: trajectory grading, an LLM-as-judge on draft quality (cached, and validated against about 6 hand-labelled drafts), a failure-taxonomy output, must-pass gates, and a CI file. Extend the existing score.py, keep it minimal, keep the offline suite passing with no network, log any discoveries to docs/backlog.md, and commit when green. Then show me the full eval output. Do not change the pipeline logic and do not add LangGraph.
```

## What it produced

- `python -m finos.score` prints route, abstain, extraction, schedule, trajectory and draft-quality scores, a failure taxonomy, and six must-pass gates. Exit 0 when all gates pass.
- The judge did flag the Nordwind "[Client's Name]" placeholder draft on its own, which is the proof it works. That draft has since been fixed, so the pre-fix version is kept frozen in the judge's validation set to keep it measured against a known failure.

## Parked, in docs/backlog.md, not blocking

- Your decision: unknown-VAT domestic invoices, abstain or let Stripe default them at Slice B/C.
- Free security hardening in Lovable ("Try to fix all") before demo day.

## Also outstanding, minor

- Optional: click Approve on a row in the review app to confirm the status flips (that fully closes Slice 2).
