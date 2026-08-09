# RESUME - where we are and what to do next

**Last session:** Slices 0, 1, 2 and 4 shipped, tested, committed. A live published review app (invoice-review-queue.lovable.app) with the pipeline feeding it end to end through a secure ingest endpoint. The repo now has a README and a live CI workflow (`.github/workflows/eval.yml`) that runs the whole suite from the committed LLM cache on every push and pull request. Backlog is current.

## Done: Slice 4 - Evals (the TRACE loop)

Built per `docs/slice-4.md`: trajectory grading, an LLM judge on draft quality validated against hand labels, a failure taxonomy, and six must-pass gates. `python -m finos.score` exits 0 with all gates passing; 23 tests green offline.

The msg-002 schedule blind spot is closed: the extractor was copying the "50% upfront" example onto a three-milestone contract. Schedule is now graded by instalment count against the golden set and is 9/9, with a must-pass gate.

## Next build: Slice 3 - real Gmail + QuickBooks

Not started. OAuth is the friction point.

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

- Your decision: unknown-VAT domestic invoices, abstain or let QuickBooks default them at Slice 3.
- Free security hardening in Lovable ("Try to fix all") before demo day.

## Also outstanding, minor

- Optional: click Approve on a row in the review app to confirm the status flips (that fully closes Slice 2).
