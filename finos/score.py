"""Smoke test plus route scorer. One command that proves the pipeline runs and shows how close it is.

    python -m finos.score

Runs all 20 fixtures, checks nothing is missing, then compares each final route
to the expected_route in the corpus. Accuracy is not graded until Slice 1, this
is here so the number is visible while it improves.
"""

from finos.adapters.mock_inbox import MockInbox
from finos.run import run_all


def main() -> None:
    events = run_all()

    # Smoke test: the run finished, every email came out the other end with a route.
    assert len(events) == 20, f"expected 20 events, got {len(events)}"
    assert all(event.route for event in events), "some events finished with no route"
    print("\nsmoke test: 20 events, all routed, no crash")

    expected = {f"gmail:{email['message_id']}": email["expected_route"] for email in MockInbox().emails}

    print("\nroute scorer")
    matches = 0
    for event in events:
        want = expected[event.event_id]
        got = event.route.value
        if want == got:
            matches += 1
        else:
            print(f"  {event.event_id:24} expected {want:8} got {got}")

    print(f"\n{matches}/20 routes match the corpus")


if __name__ == "__main__":
    main()
