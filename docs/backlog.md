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

## Current (Slice 1)

- `[done]` Add expected extraction fields to fixtures (golden set for Slice 1).
- `[done]` Slice 0 hardening: temperature 0, `score.py` route scorer (14/20 baseline), LLM cache, git init + first commit. Determinism verified: identical re-runs, cache hit ~0.5s, zero API calls. Confirmed no secrets tracked in git.
- `[done]` msg-005 and msg-006: currency guessed instead of abstaining (AED inferred from domain; EUR/USD conflict resolved rather than flagged). Fixed by the explicit no-inference rule in the extractor prompt. Both now FLAG.
- `[done]` msg-016 and msg-018 routed INVOICE, should be FLAG (terms hidden in an MSA; email addressed to the wrong person). Fixed via the `terms in external document` problem and the `addressed_to` vs `OWNER_NAME` check.
- `[done]` msg-014: internal email routed HOLD not REJECT. Fixed with a deterministic `OWN_DOMAIN` check on the From line, before any LLM call.
- `[done]` msg-020 (resend) classified INVOICE, not REJECT. Fixed with a `dedup` stage before validate; now REJECTs at routing with "duplicate of gmail:msg-001". Billing keeps its own guard as a backstop.
- `[done]` The six hardened abstain rules (the FLAG conditions). In `validate.py`: no amount, no currency, extractor problem raised, addressed to someone else, low confidence, plus duplicate at the dedup stage.
- `[done]` `.claude/settings.local.json` added to `.gitignore`.
- `[done]` `docs/slice-1.md` written. Slice pointer advanced to Slice 1 in CLAUDE.md.
- `[done]` Slice 1 result: route 20/20, wrong invoices 0, invented values 0, extraction 118/120 (98%), 96% on the clean INVOICE core fields. 11 tests green, determinism verified (identical re-runs, ~0.5s cached).
- `[open]` Golden set issue, msg-010: `expected.client_name` is "Lakeside Media Inc" but the email only ever says "Jenna" and the domain `lakesidemedia.com`. Producing "Inc" would mean inventing a legal suffix, which is exactly what the north star forbids. Pipeline returns "Lakeside Media" and takes the miss on purpose. Decide whether to relax the golden value or accept a permanent 1-field gap.
- `[open]` msg-013 `client_name` is null because REJECT cases skip extraction (deliberate: extracting from marketing and internal mail is what caused invented values). Golden expects "Nordwind Logistics GmbH". Second permanent 1-field gap unless REJECT cases get a cheap sender-name extraction.
- `[open]` The confidence-threshold abstain rule is wired (0.7 on the classifier's own self-reported confidence) but never fires on this corpus, so it is untested in anger. Self-reported confidence is weak evidence; revisit when the eval suite lands in Slice 4.

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
- Slice 1: `ContractEvent.amount` split into `total_amount` and `invoice_amount`, because the golden set grades them separately and "amount" silently meaning "the part we bill now" is the kind of ambiguity that causes wrong invoices. Accepted.
- Slice 1: the invoice store records which `event_id` created each invoice. Without it, a re-run would see every contract matching its own previous invoice and REJECT the entire corpus as duplicates. Accepted, and covered by a test.
- Slice 1: `validate` clears `invoice_amount` whenever the final route is not INVOICE. If we are abstaining, there is no amount to bill, and leaving a stale figure on a flagged event invites a wrong invoice downstream. Accepted.
- Slice 1: extraction runs on every case the classifier did not REJECT, not just INVOICE and FLAG. Extracting from marketing and internal mail is what produced invented values, so REJECT stays skipped on purpose. Accepted.
- Slice 1: the scorer treats `vat_treatment = "unknown"` as null, since "unknown" is the enum's way of saying "not stated" and the golden set writes that as null. Accepted.
