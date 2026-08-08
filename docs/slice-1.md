# Slice 1: Correctness - Abstain Rules, Duplicate Detection, Extraction Grading

**Related:** PRD v1 (the Spine), Slice 0 (done), fixtures/emails.json (golden set with `expected` blocks)

Slice 0 wired the pipeline. Slice 1 makes it get the right answer. The north star is **zero invented values** and every FLAG case actually flagging. Still plain Python, still mock rails. No LangGraph, no real integrations yet.

## What "done" looks like

- Route matches `expected_route` for all 20 (target), and, non-negotiable, **zero wrong invoices**: no INVOICE produced for anything that is not a genuine signed contract.
- All six FLAG cases route FLAG. msg-014 (internal email) routes REJECT. msg-020 (resend) routes REJECT, caught at routing, not just by the billing dedup.
- **Zero invented values:** wherever the golden `expected` field is null, the pipeline leaves it null. No inferring currency from a domain, no picking a number out of a range.
- Extraction on the clean INVOICE cases matches the golden set (client, amount, currency, VAT) at high accuracy.
- `score.py` now prints route accuracy, extraction accuracy, and an invented-values count. Tests pass. Determinism preserved.

## The work (extend what exists, do not rebuild)

**1. Stop the extractor inventing (extract.py).** This is the core fix. Instruct the model: extract only values explicitly present in the email. Specifically:
- If the currency is not explicitly written, return null. Never infer it from the email domain, the country, or names (the msg-005 AED bug).
- If two currencies appear, one quoted and one requested for billing, return null and add a `currency conflict` flag (msg-006).
- If the amount is given as a range, return null and add an `amount is a range` flag (msg-015).
- If the amount or figures are said to be in an attachment or order form, return null and add an `amount in attachment` flag (msg-004).
- Capture `vat_treatment` and `tax_id` only where stated: plus VAT (msg-007), UAE 5% with TRN (msg-008), reverse charge with VAT number (msg-009).
- Missing stays null, always. The extractor detects problems and raises flags; it does not decide the route.

**2. The six abstain rules (validate.py).** After extraction, route to FLAG with the reason when any of these holds. Keep it rule-based, no LLM:
- amount is null (covers attachment and range).
- currency is null (covers unknown and conflict).
- the email references terms in an external document (an MSA) and no terms are in the email (msg-016).
- the salutation addresses someone other than the owner (msg-018, "Hi Marcus").
- any required field is below the confidence threshold.
The extractor surfaces the signal (a flag), validate turns it into the FLAG route. Extractor detects, validate decides.

**3. Duplicate detection at routing (new, small).** Before billing, check the incoming contract's signature (client + amount + currency) against the already-invoiced signatures in the store. If it matches one already invoiced, route REJECT with a `duplicate` reason. This catches msg-020 at the right layer. Billing keeps its own guard as a backstop, but routing should no longer depend on it.

**4. Internal email rule (classify or adapter).** If the sender's domain is the owner's own domain, the message is internal and routes REJECT (msg-014). Add `OWN_DOMAIN` to `.env`. Cheap, deterministic, no LLM needed.

**5. Grow score.py.** Keep the route tally and mismatch list, and add:
- Extraction accuracy: for each case, compare `client_name`, `currency`, `amount`, `vat_treatment` to the golden `expected`. Print the field-level match rate.
- **Invented-values count:** how many fields the pipeline filled where the golden `expected` is null. Target zero. Print this prominently, it is the north-star metric.

## Acceptance criteria

- Route: 20/20 against `expected_route`, and zero wrong invoices (hard requirement, not a target).
- All six FLAG cases FLAG. msg-014 REJECT. msg-020 REJECT at routing.
- Invented values: 0.
- Extraction: client, amount, currency correct on the clean INVOICE cases, at least 95%.
- Tests green, determinism preserved (temperature 0, cache), one commit.

## Explicitly out of Slice 1

LangGraph (Slice 4). Real Gmail or QuickBooks (Slice 3). The LLM-judge eval suite and CI (Slice 4). Memory, follow-up, UI. Do not build these.

## Keep it minimal

Extend `extract.py` and `validate.py`, add one small dedup check, add the internal-domain rule, grow `score.py`. No new frameworks, no new dependencies.
