# Slice 2: Review UI + Supabase (the human-send gate becomes real)

**Related:** PRD v1, Slice 1 (done). This is the Builder "ship your product v1" surface. It is Lovable-first and browser-based, different from the Python slices. The pipeline logic barely changes; what changes is where its results go (Supabase) and that a person now sees them on a screen and acts on them.

**Goal:** the pipeline's results land in a Supabase table; a Lovable review screen shows the pending invoices and the flagged cases; the owner clicks Approve & Send, Flag, or Reject, and that decision is recorded. This turns the human-send gate from a concept into a real screen. Navy editorial, not the dark demo dashboard.

**Honesty note for the screen:** in Slice 2, "Send" is still mock. Clicking Approve & Send records the decision (status = sent); no real email goes out until Slice 3. Say that on the screen.

## The seam (unchanged design)

The Python pipeline writes to Supabase. The Lovable UI reads from and writes to Supabase. They never call each other. The shared table below is the contract between them, so both sides must match it exactly.

## The shared table: `review_queue`

Both Lovable and Claude Code use exactly these columns:

- `event_id` (text, primary key)
- `source` (text)
- `received_at` (timestamptz)
- `route` (text: INVOICE / HOLD / REJECT / FLAG)
- `client_name` (text, nullable)
- `invoice_amount` (numeric, nullable)
- `currency` (text, nullable)
- `vat_treatment` (text, nullable)
- `tax_id` (text, nullable)
- `flags` (jsonb or text[], nullable) - the abstain reasons
- `draft_email` (text, nullable)
- `status` (text): `pending` | `sent` | `flagged` | `rejected`
- `decided_at` (timestamptz, nullable)
- `created_at` (timestamptz, default now())

The pipeline writes INVOICE cases as `pending` and FLAG cases as `flagged`. HOLD and REJECT can be written for completeness or skipped; keep the screen focused on pending INVOICE plus flagged.

## Build order (Lovable first, then Claude Code)

You are GUI-first, so let Lovable stand up Supabase rather than wiring it by hand.

1. **Lovable (browser).** Build the review app. Tell it to: create the `review_queue` table above in Supabase; add basic email login (single owner); build one screen listing pending invoices (status `pending`) showing client, amount, currency, VAT, and the draft email, each row with Approve & Send, Flag, and Reject buttons that set the row's `status` and `decided_at`; and a second section showing the flagged cases with their reasons so the owner sees what was escalated. Style: navy editorial (#022B72 and #F3F6FB, one sans typeface, translucent hairlines, sharp corners, no shadows). Note on the screen that Send is mock until Slice 3. Deploy to a live URL.
2. **Get the credentials.** From the Supabase project Lovable created, copy the project URL and the `service_role` key.
3. **Claude Code (Python).** Add a `SupabaseStore` that upserts the pipeline's results into `review_queue` using those credentials (in `.env` as `SUPABASE_URL` and `SUPABASE_KEY`). Keep the local JSONL trace exactly as it is; Supabase is an additional writer, not a replacement.
4. **Verify end to end.** Run the pipeline, confirm rows appear in the live UI, click Approve on one, confirm the status flips in Supabase.

## Foundations (keep the loop intact)

- The offline test suite must still pass with no network. Stub or skip the Supabase writer in tests; the local JSONL store stays the tested path. Determinism preserved.
- `SUPABASE_URL` and `SUPABASE_KEY` go in `.env` (already gitignored). Never commit them.
- Commit when green. Log any discovery to `docs/backlog.md`.

## Acceptance criteria

- Running the pipeline populates `review_queue`: INVOICE cases `pending`, FLAG cases `flagged`, with the correct client, amount, currency, VAT, and the draft email.
- The live Lovable URL shows the pending invoices and the flagged cases, in navy editorial.
- Approve & Send, Flag, and Reject each update the row's `status` and `decided_at`.
- Basic login works.
- The offline test suite still passes; determinism preserved.
- Deployed to a live URL (this clears Builder "ship v1").

## Explicitly out of Slice 2

Real Gmail send and real QuickBooks (Slice 3). The full metrics dashboard with cash-on-hand and agent-efficiency bars (that is v2, and it shows data you do not have). The eval suite and CI (Slice 4). Do not build these. The Slice 2 screen is the review queue only.

## Keep it minimal

One table, one screen, one login, one new store class on the Python side. No extra pages, no charts, no polish beyond the navy basics.
