# RESUME - where we are and what to do next

**Last session: end of day, 15 Aug 2026.** Slices 0, 1, 2, 4, A, B1 and B2 (Moves A and C) are shipped and pushed. 59 tests green, all 7 must-pass gates pass, `python -m finos.score` exits 0 on a clean checkout with no key. CI runs the whole suite from the committed LLM cache on every push.

**The approve-to-finalise loop is proven end to end.** The worker read an approved row from the live `GET /api/public/approved` endpoint, finalised exactly that Stripe invoice (`in_1U4h7SQ...`, Nordwind Logistics, EUR 24,000) from `draft` to `open`, and marked the row sent via `POST /api/public/mark-sent`. Verified against a before/after Stripe snapshot rather than from log output: exactly 1 of 10 invoices changed status, the other 9 untouched, no new invoices, no duplicated contracts. No customer delivery (`auto_advance=False`, `attempted=False`, `paid_at=None`). A re-run found nothing to do and changed nothing in Stripe, so the loop is safe to repeat.

**Important caveat on that proof.** The approved row was seeded by hand in the Supabase SQL editor, because three review-app bugs still block the automatic path. So the worker-and-Stripe half of the loop is genuinely proven; the pipeline-to-review-queue half is not. Specifically, it is NOT yet shown that the pipeline can put a correct, approvable row into the queue on its own.

## Done so far

- **Slice A** - pivot to Slack in / Stripe out; Slack source adapter mock-first; prompt-injection case and a `no injected instruction obeyed` gate.
- **Slice B1** - `StripeBilling` behind `BillingClient`, drafts only, idempotent on a client|amount|currency signature stored in Stripe metadata. Hard stop on any key that is not `rk_test_`/`sk_test_`.
- **Slice B2 Move A** - the approval-gated worker, three independent locks: the queue only returns approved rows, `--send` is required, and Stripe's own status is checked before finalising.
- **Slice B2 Move C** - `HttpReviewQueue` against the two live bearer-authenticated endpoints. A failed read exits 1 and never looks like an empty queue.

## Done: Slice 4 - Evals (the TRACE loop)

Built per `docs/slice-4.md`: trajectory grading, an LLM judge on draft quality validated against hand labels, a failure taxonomy, and six must-pass gates. `python -m finos.score` exits 0 with all gates passing; 23 tests green offline.

The msg-002 schedule blind spot is closed: the extractor was copying the "50% upfront" example onto a three-milestone contract. Schedule is now graded by instalment count against the golden set and is 9/9, with a must-pass gate.

## Tomorrow's first tasks - all Lovable-side, none in this repo

Three review-app bugs block the automatic path. Until they are fixed, an approved row can only be produced by hand in the SQL editor.

1. **`/api/public/ingest` does not store `stripe_invoice_id`.** The pipeline sends it on every INVOICE row and the endpoint answers `updated: 16`, but the column is not persisted. Without it an approved row names no invoice and the worker has nothing to finalise.
2. **The Approve button does not write `status = 'approved'`.** Clicking Approve in the review UI leaves the row in a state the `approved` endpoint does not return, so the worker never sees it.
3. **`run --push` resets `status` on rows that already exist.** Every INVOICE row is pushed as `pending`, and the ingest upsert overwrites whatever a human had set, so re-running the pipeline silently undoes an approval. The push should leave `status` alone on rows that are already in the table.

Also: **reconnect the correct Lovable account** before touching any of the above.

Once those three are fixed, re-run the loop with a row the pipeline produced itself, not a hand-seeded one. That is the remaining proof.

## After that

Slice C (`docs/slice-3.md`): swap the mock Slack reader for a real read of a TAGGED message, keeping the mocks as the test default. Then the deepened evals and CI, then the v1.5 follow-up loop, then LangGraph.

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
