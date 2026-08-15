# Slice C: go real behind the interfaces (tagged Slack in, Stripe test mode out)

**Related:** the pivot in CLAUDE.md, Slices 0-2 and 4 (done), Slice A (Slack source, mock-first), Slice B (Stripe adapter + approval-gated worker, mock-first). Build only after A and B are green.

This slice changes no logic. Both mocks are swapped for the real thing behind interfaces that already exist, one at a time. If the seams were drawn correctly in A and B, this is two adapter swaps and a config change, not a rewrite. That is the whole point of the slice.

## Goal

A real contract message posted in Slack, tagged by the owner, produces a draft in the review queue. The owner approves it in the Lovable UI. A real Stripe test-mode invoice is created and sent. Verified by looking at the actual Stripe dashboard, not by trusting a log line.

## 1. Real Slack read, TAGGED only

Swap `SlackMock` for a real reader behind the same `SourceAdapter` shape (`fetch`, `read_raw`). One line changes in `run.sources()`.

**The tag is the trigger, and this is a safety rule, not a convenience.** A message is picked up only when it is explicitly marked: a specific emoji reaction added by the owner, or a post in one designated channel. Reading "the latest message in a channel" is forbidden. Random channel chatter must never become an invoice. The mock already models this: `SlackMock.corpus()` emits only messages whose `tag` matches `PICKUP_TAG`, and `fixtures/slack.json` carries an untagged message that must never appear as an event.

Rules the real reader must keep:

- **The first line of `read_raw` is built only from what Slack vouches for** (the poster's account email and the channel), never from message text. `classify.is_internal()` reads that line, so anything a sender can type on it is attacker-controlled routing.
- **The pickup tag never reaches the model.** A subject hinting "invoice" biases the classifier.
- **Trust level stays `untrusted`.** Slack is attacker-reachable free text.
- **`event_id` stays `slack:{channel}-{ts}`.** Slack's own message identity, so a re-read of the same message is the same event and dedup keeps working.

**Known constraint to resolve here:** `is_internal` REJECTs anything whose sender is on `OWN_DOMAIN`. Slice A's fixtures model an external client posting in a shared channel, which works. If the real pickup story is "the owner pastes or forwards a contract into Slack", the poster is on our own domain and every such message is REJECTed for free before any LLM call. Decide the real posting story first; if it is self-posted, `is_internal` needs a source-aware rule and that is its own change.

Config: `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`, `SLACK_PICKUP_TAG` in `.env`. Read-only scopes only.

## 2. Real Stripe, TEST MODE

Swap the mock `BillingClient` for `StripeBilling` in the worker only. The test suite keeps `MockBilling` as its default so tests stay deterministic, offline and free.

- **Restricted key, test mode.** `STRIPE_RESTRICTED_KEY` scoped to invoicing only, in the worker's `.env`. Never a root key, never in the browser, never in the Lovable frontend.
- **Stripe owns the money data.** Invoice numbering, tax, payment status. We do not reimplement any of it.
- **Idempotency.** An approved row must produce exactly one invoice. Use the `event_id` as the idempotency key so a retried worker run cannot double-bill. This is the single most important property in the slice.

## 3. One real end-to-end pass

Post a contract in Slack, tag it, run the pipeline, see the draft in the review queue, approve it in Lovable, run the worker, confirm a real test-mode invoice exists in Stripe with the right customer, amount and currency, and that the row flipped to `sent` with its `stripe_invoice_id` stored.

Verify it actually worked by opening the Stripe dashboard and the Supabase row. Do not claim success from a log line.

## Acceptance criteria

- A tagged Slack message becomes a draft in the review queue; an untagged message in the same channel does not.
- Approving in Lovable, then running the worker, creates and sends exactly one real Stripe test-mode invoice.
- Re-running the worker on the same approved row creates nothing new (idempotency holds).
- The Stripe key is restricted, test mode, and present only in the worker environment.
- The offline suite still passes with no network, still on the mocks, and all gates stay green.
- Determinism preserved: the cached corpus run is unchanged by any of this.

## Explicitly out of Slice C

The deepened eval suite and CI hardening (that is the old Slice 4 work, resumed after this). The v1.5 payment-follow-up and reminder loop. LangGraph. Real payment webhooks. Memory. Do not build these here.

## Keep it minimal

Two adapter swaps, one config block, one idempotency key. No new abstractions. If this slice needs more than that, the seams in A and B were drawn wrong and that is the thing to fix.
