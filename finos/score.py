"""Smoke test plus scorer. One command, three numbers.

    python -m finos.score

Runs all 20 fixtures, then measures the pipeline against the golden set:
route accuracy, extraction accuracy, and the invented-values count. Invented
values is the north-star metric and the target is zero.
"""

from finos.adapters.mock_inbox import MockInbox
from finos.models import ContractEvent, Route, VatTreatment
from finos.run import run_all

# The fields the golden set pins down, compared case by case.
GRADED_FIELDS = ["client_name", "currency", "total_amount", "invoice_amount", "vat_treatment", "tax_id"]

# The narrower bar the spec sets for the clean invoice cases.
CORE_FIELDS = ["client_name", "currency", "invoice_amount"]


def actual_value(event: ContractEvent, field: str):
    """What the pipeline produced, normalised so it can be compared to the golden JSON."""
    value = getattr(event, field)
    if field == "vat_treatment":
        # "unknown" is how the model says "not stated", which the golden set writes as null.
        return None if value == VatTreatment.UNKNOWN else value.value
    if field in ("total_amount", "invoice_amount"):
        return None if value is None else float(value)
    return value


def golden_value(expected: dict, field: str):
    value = expected[field]
    if field in ("total_amount", "invoice_amount") and value is not None:
        return float(value)
    return value


def same(got, want) -> bool:
    if isinstance(got, str) and isinstance(want, str):
        return got.strip().lower() == want.strip().lower()
    return got == want


def main() -> None:
    events = run_all()

    assert len(events) == 20, f"expected 20 events, got {len(events)}"
    assert all(event.route for event in events), "some events finished with no route"
    print("\nsmoke test: 20 events, all routed, no crash")

    corpus = {f"gmail:{email['message_id']}": email for email in MockInbox().emails}

    print("\n--- ROUTE ---")
    route_matches = 0
    for event in events:
        want = corpus[event.event_id]["expected_route"]
        if want == event.route.value:
            route_matches += 1
        else:
            print(f"  {event.event_id:24} expected {want:8} got {event.route.value}")
    print(f"route accuracy: {route_matches}/20")

    wrong_invoices = [
        event.event_id
        for event in events
        if event.route == Route.INVOICE and corpus[event.event_id]["expected_route"] != "INVOICE"
    ]
    print(f"wrong invoices: {len(wrong_invoices)} {wrong_invoices or ''}")

    print("\n--- EXTRACTION ---")
    checked = matched = 0
    core_checked = core_matched = 0
    misses = []
    for event in events:
        expected = corpus[event.event_id]["expected"]
        is_clean_invoice = corpus[event.event_id]["expected_route"] == "INVOICE"
        for field in GRADED_FIELDS:
            got, want = actual_value(event, field), golden_value(expected, field)
            hit = same(got, want)
            checked += 1
            matched += hit
            if is_clean_invoice and field in CORE_FIELDS:
                core_checked += 1
                core_matched += hit
            if not hit:
                misses.append(f"  {event.event_id:24} {field:16} expected {want!r}, got {got!r}")
    for miss in misses:
        print(miss)
    print(f"extraction accuracy: {matched}/{checked} fields ({matched / checked:.0%})")
    print(f"  on the clean INVOICE cases, client/currency/amount: "
          f"{core_matched}/{core_checked} ({core_matched / core_checked:.0%})")

    print("\n--- INVENTED VALUES (north star, target 0) ---")
    invented = []
    for event in events:
        expected = corpus[event.event_id]["expected"]
        for field in GRADED_FIELDS:
            if golden_value(expected, field) is None and actual_value(event, field) is not None:
                invented.append(f"  {event.event_id:24} {field:16} invented {actual_value(event, field)!r}")
    for line in invented:
        print(line)
    print(f"invented values: {len(invented)}")


if __name__ == "__main__":
    main()
