# Slice 0: Scaffold, Schema, and Mock Pipeline

> **Historical record of shipped work.** Written before the Slack/Stripe pivot, so it describes Gmail as the source and QuickBooks as the billing system of record. Kept as an accurate account of what was built and why. The current architecture is in CLAUDE.md.

**Related:** PRD v1 (the Spine), Contract Email Corpus v1 (now in `fixtures/emails.json`)

This is the first thing to build. It creates the skeleton of the FinOS agent and gets the whole pipeline running end to end against mock data, with no real Gmail and no real QuickBooks yet. Correctness is not the goal here. A wired, running spine is. Real extraction accuracy and the abstain rules come in Slice 1.

## Reuse what is already here

This folder already has a FastAPI "research-assistant" service (`main.py`) using OpenRouter. Do NOT touch it. FinOS is a new `finos/` package alongside it, and the LLM wrapper reuses the existing OpenRouter client (`OPENROUTER_API_KEY` is already in `.env`, base_url `https://openrouter.ai/api/v1`). Cheap model (`openai/gpt-4o-mini`) to classify, a stronger one to extract. No new API key.

## What "done" looks like

One command runs all 20 corpus emails through the pipeline: each is read into a ContractEvent, classified into a lane, and for the ones that look like signed contracts a mock invoice and a draft email are produced. Nothing touches real Gmail or QuickBooks. Every run writes a trace. Re-running does not create duplicate mock invoices. That is the whole bar: it runs end to end without crashing and produces the right shape of output.

## Sequencing note

Slice 0 is plain Python: an LLM service, typed outputs, and simple stage functions. It is deliberately NOT LangGraph yet. LangGraph is Week 3 material and its assignment is due 22 August (Slice 4). Write the pipeline as clean, separate stage functions now, so wrapping them into a LangGraph graph later is nearly free. Do not pull LangGraph in early.

## 1. Repo structure (added alongside the existing files)

```
main.py              # EXISTING research-assistant, leave alone
finos/
  __init__.py
  models.py          # ContractEvent and the enums
  interfaces.py      # SourceAdapter, BillingClient, TraceStore (Protocols)
  llm.py             # thin wrapper over the existing OpenRouter client
  pipeline/
    classify.py      # decide the route
    extract.py       # fill the ContractEvent fields
    validate.py      # checks + set FLAG on failure
    draft.py         # write the covering email
  adapters/
    mock_inbox.py    # reads fixtures/emails.json, emits ContractEvents
    gmail.py         # STUB for Slice 3
  billing/
    mock_billing.py  # logs instead of calling QuickBooks, dedups
    quickbooks.py    # STUB for Slice 3
  store/
    local_trace.py   # writes trace lines to runs/trace.jsonl
  run.py             # orchestrator (CLI)
fixtures/
  emails.json        # the 20 corpus emails (already here)
tests/
  test_pipeline.py
```

## 2. The ContractEvent schema

Build this first. It anchors everything.

```python
from enum import Enum
from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field

class Route(str, Enum):
    INVOICE = "INVOICE"   # signed contract, proceed to draft invoice
    HOLD    = "HOLD"      # unsigned proposal, wait
    REJECT  = "REJECT"    # not a contract, or a duplicate
    FLAG    = "FLAG"      # unsure, escalate to owner

class Source(str, Enum):
    GMAIL = "gmail"
    HUBSPOT = "hubspot"
    FORM = "form"
    STRIPE = "stripe"

class TrustLevel(str, Enum):
    UNTRUSTED = "untrusted"   # email, attacker-reachable
    TRUSTED   = "trusted"     # internal CRM deal

class VatTreatment(str, Enum):
    STANDARD = "standard"
    PLUS_VAT = "plus_vat"
    REVERSE_CHARGE = "reverse_charge"
    NONE = "none"
    UNKNOWN = "unknown"

class ScheduleItem(BaseModel):
    portion: str                    # "100%", "milestone 1", "50% upfront"
    trigger: Optional[str] = None   # "on signature", "2026-11-01", "on delivery"

class ContractEvent(BaseModel):
    # set by the adapter
    event_id: str                   # from source + message id
    source: Source
    trust_level: TrustLevel
    received_at: datetime
    raw_ref: str                    # pointer to the stored raw email

    # set by the pipeline
    route: Optional[Route] = None
    client_name: Optional[str] = None
    client_email: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None          # ISO 4217, e.g. EUR
    vat_treatment: VatTreatment = VatTreatment.UNKNOWN
    vat_rate: Optional[Decimal] = None
    tax_id: Optional[str] = None            # VAT number or TRN
    payment_terms: Optional[str] = None
    schedule: list[ScheduleItem] = Field(default_factory=list)
    confidence: dict[str, float] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
```

## 3. The interfaces

The mock and the real Gmail or QuickBooks both satisfy the same interface, so Slice 3 is a swap, not a rewrite.

```python
from typing import Protocol, Optional

class SourceAdapter(Protocol):
    def fetch(self) -> list["ContractEvent"]:
        """Return raw ContractEvents, fields empty except the adapter-set ones."""

class BillingClient(Protocol):
    def match_or_create_customer(self, name: str, email: Optional[str]) -> str:
        """Return a customer id. Idempotent on name."""
    def create_draft_invoice(self, event: "ContractEvent") -> str:
        """Return a draft invoice id. Refuses duplicates (see mock billing)."""

class TraceStore(Protocol):
    def write(self, event_id: str, stage: str, payload: dict) -> None:
        """Append one trace record."""
```

## 4. The LLM wrapper (reusing OpenRouter)

One thin function in `finos/llm.py` that reuses the OpenRouter client pattern already in `main.py`:

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)

MODEL_CLASSIFY = os.getenv("MODEL_CLASSIFY", "openai/gpt-4o-mini")
MODEL_EXTRACT  = os.getenv("MODEL_EXTRACT",  "openai/gpt-4o-mini")  # bump to a stronger model later
```

Add `MODEL_CLASSIFY` and `MODEL_EXTRACT` to `.env`. Keep the wrapper tiny.

## 5. The pipeline stages (Slice 0 behaviour)

Each stage is a plain function taking a ContractEvent and returning it. First-pass, not hardened.

- **classify(event).** One LLM call (MODEL_CLASSIFY) returning a Route: signed contract (INVOICE), unsigned proposal (HOLD), not a contract or a duplicate (REJECT), or unclear (FLAG). Store a confidence.
- **extract(event).** For INVOICE and FLAG candidates, one LLM call (MODEL_EXTRACT) using structured output that fits the ContractEvent shape. Fill client, amount, currency, vat_treatment, payment_terms, schedule. Missing values stay null, never invented.
- **validate(event).** Cheap rule checks, no LLM. If amount is null, currency is null, or a required field is missing, set route to FLAG and append a reason to flags. First-pass version of the six abstain rules; full set is Slice 1.
- **draft(event).** For INVOICE only, one LLM call to write the covering email.

**Orchestrator (run.py).** Fetch events from the mock adapter. For each: classify, then if INVOICE or FLAG-candidate extract, then validate. If final route is INVOICE, call the mock billing client (customer then draft invoice) and draft the email. Write a trace after every stage. Print a one-line summary per email.

## 6. The mock rails

- **Mock inbox.** `fixtures/emails.json` holds the 20 corpus emails. Each entry has `message_id`, `from`, `subject`, `body`, `expected_route`. The `expected_route` is for grading later, ignored by the pipeline. The adapter emits one ContractEvent per entry, setting event_id from message_id, source gmail, trust_level untrusted.
- **Mock billing.** In-memory store. `create_draft_invoice` keeps a set of content signatures (client_name + amount + currency). If a new draft matches a signature already seen, it treats it as a duplicate and creates nothing, returning the existing id. This is what makes the duplicate resend (corpus case 20) produce no second invoice, and it also makes re-running the whole set safe.
- **Local trace store.** Appends JSON lines to `runs/trace.jsonl`. Stands in for Supabase until Slice 2.

## 7. Acceptance criteria

- One command runs all 20 fixtures with no crash.
- Every email produces a ContractEvent with a route set.
- INVOICE cases reach a mock draft invoice and a draft email. HOLD, REJECT, FLAG do not.
- The duplicate resend (case 20) produces no second mock invoice. Re-running the whole set produces no duplicates.
- `runs/trace.jsonl` has a record for every stage of every email.
- Correctness accuracy is NOT graded yet. Wired and running is the bar.

## 8. Explicitly out of Slice 0

Real Gmail. Real QuickBooks. The full TRACE eval suite. The six hardened abstain rules. Memory. Payment follow-up. A polished UI. Do not build any of these now.

## 9. How to run

```
source .venv/bin/activate
pip install pydantic          # if not already present
python -m finos.run --mock
# then read runs/trace.jsonl to see what happened
```
