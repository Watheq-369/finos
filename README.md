<!-- After the repo is on GitHub, replace OWNER/REPO below with your handle and repo name to show the live CI badge. -->
[![eval](https://github.com/Watheq-369/finos/actions/workflows/eval.yml/badge.svg)](https://github.com/Watheq-369/finos/actions/workflows/eval.yml)

# FinOS: an AI agent for revenue operations

FinOS turns an inbound contract message into a safe invoicing decision. It reads the message, decides whether to invoice, drafts the invoice and the covering email, and stops for a human to approve. Only after a person approves does a gated worker finalise that exact invoice in Stripe. Once an invoice is open and unpaid, a follow-up loop drafts the next payment reminder. At no point does FinOS send anything to a client on its own.

It is built as an eval-driven system: every decision is graded against a labelled golden set, and a suite of must-pass gates decides whether a change is allowed to ship.

## The problem

When a signed contract lands in your inbox or a Slack channel, someone has to read it, pull out the client, the amount, the currency, the VAT treatment and the payment schedule, decide whether it is actually invoiceable, and raise the invoice. Then, when it goes unpaid, someone has to chase it. It is repetitive, it is error-prone, and a single wrong figure goes straight to a client. FinOS does the reading, the decision and the chasing, and stops at the exact point where money or a client-facing message is involved, handing a ready-to-approve draft to a person.

## Three design ideas

**Three layers, kept separate.** A source adapter normalises whatever arrives, a tagged Slack message today, an email or a CRM deal later, into one canonical object carrying a trust level. The agent decides and drafts. Stripe is the billing system of record: it owns invoice numbering, tax and payment status, and is driven through its API with a restricted key, never rebuilt. New sources and new systems become a swap, not a rewrite.

**Automate, Augment, Abstain.** Every step is coloured by how much authority the machine is allowed to hold. Internal, reversible work is automated. Anything that puts money out or faces a client is augmented: the machine prepares, a human approves. Anything uncertain is abstained: the agent stops and escalates rather than guess.

**Fail safe, never silently wrong.** The north-star metric is zero wrong invoices. When the agent is unsure, a missing currency, an amount that lives only in an attachment, a message addressed to someone else, it flags and stops instead of inventing a value. A visible stop always beats a confident mistake.

## The loop, end to end

The full path runs automatically and has been proven with no hand-seeding: the pipeline reads the contract, extracts the fields, and pushes a draft invoice plus a covering email to a review queue through a scoped, authenticated endpoint. A human approves on the review screen. Only then does the worker act, and it is gated three independent ways: the queue returns only approved rows, a `--send` flag is required, and Stripe's own status is checked before anything is finalised. Finalising moves the invoice `draft` to `open` and never auto-emails the customer (`auto_advance=False`). It is idempotent: a finalised invoice cannot be finalised or re-invoiced twice.

Once an invoice is open and unpaid, the dunning loop takes over. It is a small LangGraph graph that, as of a date you pass in, decides the next reminder tier for one invoice and drafts the follow-up, escalating in tone from a gentle nudge to a formal escalation. It reads payment status behind a seam, it stops at a draft, and it never sends.

## How it earns trust

The corpus is also the golden set: contract emails in `fixtures/emails.json` and tagged Slack messages in `fixtures/slack.json`, 29 cases in all, each carrying the correct route and the correct extracted fields. The eval suite in `finos/score.py` runs the whole pipeline and grades it several ways:

- the route it chose, against the expected one;
- the fields it extracted, against the golden values;
- the VAT treatment, rate and tax id, graded per market (DE, ES, AE);
- the payment schedule it read, by instalment count, so a split cannot be quietly invented or collapsed;
- the values it invented, which must be zero;
- the path it took to reach the answer, graded as a trajectory, not just the final result;
- the quality of the covering emails, judged by an LLM;
- whether a smuggled instruction was obeyed, because an incoming message is untrusted text and must be read, not followed;
- the dunning tier it chose, one decision per scenario, so an escalation cannot fire early or late.

The judge is itself validated. Its verdicts are checked against a set of hand labels before the score is trusted, and two known-bad drafts are kept frozen inside the suite: one with a leftover placeholder, and one that is fluent and placeholder-free but bills the wrong number. The judge is measured against failures it must catch, not just template artefacts. A judge that can only ever pass is worse than no judge.

Every model call runs at temperature 0 and is cached on disk, so re-runs are identical and cost nothing after the first. Determinism is verified by rebuilding the cache from scratch and confirming the metrics do not move.

A set of must-pass gates decides the exit code. If any gate fails, a wrong invoice, an invented value, a dropped abstain, a wrong payment schedule, a broken trajectory, a placeholder or wrong number in a draft, an obeyed injection, or a wrong dunning tier, the suite exits non-zero and CI goes red.

## Results (latest run)

Do not take these on faith. Run `python -m finos.score` and read them off yourself.

| Metric | Result |
|--------|--------|
| Route accuracy | 29/29 |
| Wrong invoices | 0 |
| Field extraction | 174/174 |
| VAT by market (DE, ES, AE) | 15/15 |
| Payment schedule (invoice cases) | 14/14 |
| Invented values | 0 |
| Injected instructions obeyed | 0 |
| Abstain correctness | 29/29 |
| Trajectory | 29/29 |
| Covering-email drafts passing the judge | 14/14 |
| Judge agreement with hand labels | 8/8 |
| Dunning tier accuracy | 18/18 |
| Regression tests | 92 passed |
| Must-pass gates | all 8 pass |

## Layout

```
finos/
  models.py          canonical ContractEvent and the enums
  llm.py             OpenRouter wrapper, temperature 0, on-disk cache
  interfaces.py      source / billing / payment-status / trace protocols
  adapters/          slack_mock (the live source), mock_inbox (the email corpus), gmail (dormant)
  pipeline/          classify, extract, dedup, validate, draft
  billing/           stripe (real, restricted test key), mock_billing (the default)
  dunning/           the LangGraph follow-up loop that drafts payment reminders
  store/             local trace, the ingest client, and the HTTP review-queue client
  worker.py          the approval-gated finaliser (dry-run by default, --send to act)
  run.py             orchestrator over every source
  score.py           the eval suite and the must-pass gates
fixtures/            contract emails + tagged Slack messages, doubling as the golden set
tests/               regression tests
docs/                per-slice specs and the living backlog
```

## Run it

```
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest
cp .env.example .env      # add OPENROUTER_API_KEY for live runs; a fully cached run needs no key
```

Run the pipeline over every source (nothing is ever sent):

```
python -m finos.run --mock
```

Run the checks:

```
python -m finos.score            # full suite, judge included, replayed from cache
python -m finos.score --offline  # deterministic checks only, no network
python -m pytest tests/ -q       # regression tests
```

## Status

The pipeline, the eval suite, a live review UI (an invoice queue with owner approval, behind authentication), the approval-gated Stripe worker and the dunning loop all work end to end. The pipeline feeds the UI through a scoped, authenticated ingest endpoint rather than a database root key, so no privileged key ever sits in a worker, and the ingest is a partial update: each column is owned by exactly one writer, so a sync can never null a field it does not name. Slack is the signal source and only a tagged message is ever picked up; the corpus carries a prompt-injection case that the suite gates on.

The Slack read and the payment-status feed are currently mocked behind their interfaces; Stripe billing is real, in test mode, driven by a restricted key that hard-stops on anything that is not a test key. Next: wire the dunning loop to read open invoices from Stripe directly, and swap the mock Slack reader for a real read of a tagged message.

The repository also contains a small FastAPI research assistant (`main.py`) that predates FinOS; FinOS reuses its OpenRouter setup.
