"""Grade the path the agent took, not just the answer it reached.

A right answer reached by the wrong path is a fail. The two paths that matter most:
an email that is not a contract must never reach the extractor, and a duplicate must
be caught at dedup rather than quietly resolved later at billing.

The expected path is derived from the route, so the corpus needs no new fields.
"""

INVOICE_PATH = ["classify", "extract", "validate", "billing", "draft"]
ABSTAIN_PATH = ["classify", "extract", "validate"]
SHORT_CIRCUIT_PATH = ["classify", "validate"]


def expected_path(classify_route: str, final_route: str) -> list[str]:
    """What the trace should look like for one case."""
    if classify_route == "REJECT":
        # Not a contract at all. Stopping here is what keeps invented values at zero.
        return SHORT_CIRCUIT_PATH
    if final_route == "INVOICE":
        return INVOICE_PATH
    # FLAG, HOLD, and the duplicate caught at dedup all stop after validate.
    return ABSTAIN_PATH


def paths_from_trace(records: list[dict]) -> dict[str, list[str]]:
    """The stage sequence each event went through, in order."""
    paths: dict[str, list[str]] = {}
    for record in records:
        paths.setdefault(record["event_id"], []).append(record["stage"])
    return paths


def classify_routes_from_trace(records: list[dict]) -> dict[str, str]:
    """What the classifier said, before dedup or validate could change it."""
    return {
        record["event_id"]: record["payload"]["route"]
        for record in records
        if record["stage"] == "classify"
    }
