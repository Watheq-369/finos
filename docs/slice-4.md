# Slice 4: Evals - the TRACE loop

**Related:** PRD v1, Slices 0-2 (done), the corpus golden set, the existing `score.py`. Build later; this is the spec.

Slice 1 gave you a scorer that grades the final answer (route, extraction, invented values). Slice 4 turns that into a real eval suite that also grades the path the agent took and the quality of the draft, buckets failures so you can see where it breaks, enforces must-pass gates, and runs in CI. This is the AI Engineering capstone's strongest surface, financial output is exactly where "looks right" fails and real evals matter.

## Map to TRACE (the course grades on this)

- **Trace.** The pipeline already writes `runs/trace.jsonl`, one full trajectory per email. That is the eval input, no new instrumentation needed.
- **Read.** Error analysis by hand first. Read the trajectories and outputs for the cases that fail, and understand how they fail before automating anything. Do not skip this for tooling.
- **Analyze.** Bucket every failure into a taxonomy: misroute, mis-extract, wrong-abstain, wrong-trajectory, bad-draft.
- **Codify.** Turn the findings into assertions (hard, exact truth) and validated judges (soft, fuzzy truth).
- **Enforce.** Gate on the must-pass metrics and run the suite on every change, in CI.

## What Slice 4 adds on top of the existing scorer

**1. Trajectory grading.** Grade the path, not just the answer. For each case, check the trace shows the correct sequence of stages for its route: INVOICE goes classify then extract then validate then dedup then draft; FLAG goes classify then extract then validate and abstains; internal REJECT short-circuits at classify before any LLM extract; the duplicate REJECTs at the dedup stage. A right answer reached by the wrong path is a fail (this is what caught the msg-020 "duplicate resolved at billing not routing" issue earlier). Derive the expected trajectory from the route, no new fixture fields needed.

**2. LLM-as-judge on draft quality.** This is the one fuzzy thing the deterministic scorer cannot grade. For each INVOICE draft, a judge scores: does it address the right client by name with no leftover placeholders, state the correct amount and currency, use the correct VAT language, and read as send-ready. Returns pass or fail plus a reason. This would have caught the Nordwind "Dear [Client's Name]" placeholder automatically, instead of relying on a human to spot it.

**3. Validate the judge.** Before trusting it, hand-label about six drafts as good or bad and confirm the judge agrees with you. A judge you have not checked against human labels is just another model guessing. Report the agreement rate.

**4. Failure taxonomy output.** For every failing case the suite prints which bucket it falls in, so you see where it breaks, not just a number that dropped.

**5. Must-pass gates and CI.** Hard gates: zero wrong invoices, zero invented values, 100 percent abstain correctness, all trajectories correct, no draft with a placeholder. The suite runs on every change and a change that violates a gate fails. Add CI (a GitHub Actions workflow, or a `make eval` target run by a pre-commit hook) that runs the offline parts on every commit.

## Determinism and cost

The pipeline's LLM calls are already cached. Cache the judge too, keyed on the case plus the exact draft text, so re-runs and CI are deterministic and free. The judge only spends tokens on a new or changed draft. The deterministic parts (route, extraction, trajectory, invented values) never touch the network.

## Eval dataset

The corpus golden set, already labeled for route and extraction. Trajectory is derived from route. Draft quality is judged, with the six human labels for alignment. No new corpus needed for this slice.

## Acceptance criteria

- One command runs the full suite and prints: route accuracy, extraction accuracy, invented values, trajectory pass rate, draft-quality pass rate, and a failure-taxonomy breakdown.
- The must-pass gates are enforced; a change that violates any of them fails the suite.
- The judge is validated against the hand labels, and its agreement rate is reported.
- CI runs the offline parts on every commit; the judge runs on demand or from cache.
- The suite catches the Nordwind placeholder draft, as a real test that the judge works.
- Determinism preserved; the offline suite still passes with no network.

## Explicitly out of Slice 4

LangGraph orchestration (that is the separate "make your capstone agentic" assignment; it gets its own spec). Real Gmail and QuickBooks (Slice 3). Memory (later). Do not build these here.

## Keep it minimal

Extend `score.py` into an eval module, or add a small `finos/evals/` package. Add the trajectory check, the judge with its cache, the taxonomy output, and one CI file. No new frameworks beyond what the judge call needs.
