<!-- After the repo is on GitHub, replace OWNER/REPO below with your handle and repo name to show the live CI badge. -->
[![eval](https://github.com/Watheq-369/finos/actions/workflows/eval.yml/badge.svg)](https://github.com/Watheq-369/finos/actions/workflows/eval.yml)

# FinOS: an AI agent for revenue operations

FinOS turns an inbound contract message into a safe invoicing decision. It reads the message, decides whether to invoice, and drafts the invoice and the covering email for a human to approve. It never sends anything on its own.

It is built as an eval-driven system: every decision is graded against a labelled golden set, and a suite of must-pass gates decides whether a change is allowed to ship.

## The problem

When a signed contract lands in your inbox or a Slack channel, someone has to read it, pull out the client, the amount, the currency, the VAT treatment and the payment schedule, decide whether it is actually invoiceable, and raise the invoice. It is repetitive, it is error-prone, and a single wrong figure goes straight to a client. FinOS does the reading and the decision, and stops at the exact point where money or a client-facing message is involved, handing a ready-to-approve draft to a person.

## Three design ideas

**Three layers, kept separate.** A source adapter normalises whatever arrives, a tagged Slack message today, an email or a CRM deal later, into one canonical object carrying a trust level. The agent decides and drafts. Stripe is the billing system of record: it owns invoice numbering, tax and payment status, and is driven through its API with a restricted key, never rebuilt. New sources and new systems become a swap, not a rewrite.

**Automate, Augment, Abstain.** Every step is coloured by how much authority the machine is allowed to hold. Internal, reversible work is automated. Anything that puts money out or faces a client is augmented: the machine prepares, a human approves. Anything uncertain is abstained: the agent stops and escalates rather than guess.

**Fail safe, never silently wrong.** The north-star metric is zero wrong invoices. When the agent is unsure, a missing currency, an amount that lives only in an attachment, an email addressed to someone else, it flags and stops instead of inventing a value. A visible stop always beats a confident mistake.

## How it earns trust

The corpus is also the golden set: 20 contract emails in `fixtures/emails.json` and the tagged Slack messages in `fixtures/slack.json`, each carrying the correct route and the correct extracted fields. The eval suite in `finos/score.py` runs the whole pipeline and grades it several ways:

- the route it chose, against the expected one;
- the fields it extracted, against the golden values;
- the payment schedule it read, by instalment count, so a split cannot be quietly invented or collapsed;
- the values it invented, which must be zero;
- the path it took to reach the answer, graded as a trajectory, not just the final result;
- the quality of the covering emails, judged by an LLM;
- whether a smuggled instruction was obeyed, because an incoming message is untrusted text and must be read, not followed.

The judge is itself validated. Its verdicts are checked against a set of hand labels before the score is trusted, and a known-bad draft is kept frozen inside the suite so the judge is always measured against something it must fail. A judge that can only ever pass is worse than no judge.

Every model call runs at temperature 0 and is cached on disk, so re-runs are identical and cost nothing after the first. Determinism is verified by rebuilding the cache from scratch and confirming the metrics do not move.

A set of must-pass gates decides the exit code. If any gate fails, a wrong invoice, an invented value, a dropped abstain, a wrong payment schedule, a broken trajectory, or a placeholder left in a draft, the suite exits non-zero and CI goes red.

## Results (latest run)

Do not take these on faith. Run `python -m finos.score` and read them off yourself.

| Metric | Result |
|--------|--------|
| Route accuracy | 22/22 |
| Field extraction | 132/132 |
| Invented values | 0 |
| Injected instructions obeyed | 0 |
| Abstain correctness | 22/22 |
| Payment schedule (invoice cases) | 10/10 |
| Trajectory | 22/22 |
| Covering-email drafts passing the judge | 10/10 |
| Judge agreement with hand labels | 7/7 |
| Must-pass gates | all 7 pass |

## Layout

```
finos/
  models.py          canonical ContractEvent and the enums
  llm.py             OpenRouter wrapper, temperature 0, on-disk cache
  interfaces.py      source / billing / trace protocols
  adapters/          slack_mock (the live source), mock_inbox (the email corpus), gmail (dormant)
  pipeline/          classify, extract, dedup, validate, draft
  billing/           mock_billing (the default), stripe (real, Slice B)
  store/             local trace, and the ingest client for the review UI
  evals/             judge (+ hand labels), trajectory grading
  run.py             orchestrator over every source
  score.py           the eval suite and the must-pass gates
fixtures/            20 contract emails + tagged Slack messages, doubling as the golden set
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

The pipeline, the eval suite and a live review UI (an invoice queue with owner approval, behind authentication) work end to end. The pipeline feeds the UI through a scoped, authenticated ingest endpoint rather than a database root key, so no privileged key ever sits in a worker. Slack is the signal source and only a tagged message is ever picked up; the corpus carries a prompt-injection case that the suite gates on. The Slack read and the billing system are currently mocked. Next: a Stripe adapter behind an approval-gated worker, then both go real behind the same interfaces.

The repository also contains a small FastAPI research assistant (`main.py`) that predates FinOS; FinOS reuses its OpenRouter setup.
