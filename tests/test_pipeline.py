"""Tests for the parts that do not call the LLM: the adapter, the rules, dedup, billing, and ingest.

Nothing here touches the network. The ingest client's HTTP call is stubbed.
"""

import json

import httpx
import pytest

from datetime import datetime, timezone
from decimal import Decimal

from finos.adapters.mock_inbox import MockInbox
from finos.adapters.slack_mock import PICKUP_TAG, SlackMock
from finos.billing.mock_billing import MockBilling
from finos.billing import stripe as stripe_billing
from finos.billing.stripe import StripeBilling, _minor_units, _signature
from finos.models import ContractEvent, Route, Source, TrustLevel
from finos.pipeline.classify import is_internal
from finos.pipeline.dedup import check_duplicate
from finos.pipeline.validate import validate
from finos.run import sources
from finos.score import GRADED_FIELDS
from finos.evals.judge import (
    FROZEN_DRAFTS,
    FROZEN_WRONG_AMOUNT_DRAFT,
    agreement,
    has_placeholder,
    load_labels,
)
from finos.evals.trajectory import (
    ABSTAIN_PATH,
    INVOICE_PATH,
    SHORT_CIRCUIT_PATH,
    classify_routes_from_trace,
    expected_path,
    paths_from_trace,
)
from finos.store import ingest
from finos.store import http_queue
from finos.store.http_queue import HttpReviewQueue, base_url
from finos.store.stub_queue import StubReviewQueue
from finos.worker import process
from finos.store.ingest import IngestClient, rows_for


def make_event(**overrides) -> ContractEvent:
    fields = {
        "event_id": "gmail:test-001",
        "source": Source.GMAIL,
        "trust_level": TrustLevel.UNTRUSTED,
        "received_at": datetime.now(timezone.utc),
        "raw_ref": "fixtures/emails.json#test-001",
        "route": Route.INVOICE,
        "client_name": "Test GmbH",
        "total_amount": Decimal("1000"),
        "invoice_amount": Decimal("1000"),
        "currency": "EUR",
    }
    return ContractEvent(**{**fields, **overrides})


def test_mock_inbox_emits_one_event_per_email():
    inbox = MockInbox()
    events = inbox.fetch()

    assert len(events) == 27
    assert events[0].event_id == "gmail:msg-001"
    assert events[0].trust_level == TrustLevel.UNTRUSTED
    assert "Nordwind" in inbox.read_raw(events[0].raw_ref)


def test_internal_mail_is_recognised_by_sender_domain():
    assert is_internal("From: Sami K. <sami@younesmotasam.com>\nSubject: hi")
    assert not is_internal("From: Petra <p.lang@nordwind-logistics.de>\nSubject: hi")


def test_validate_flags_a_missing_amount():
    event = validate(make_event(invoice_amount=None))

    assert event.route == Route.FLAG
    assert "no amount to invoice" in event.flags


def test_validate_flags_a_missing_currency():
    event = validate(make_event(currency=None))

    assert event.route == Route.FLAG
    assert "no currency" in event.flags


def test_validate_turns_an_extractor_problem_into_a_flag():
    event = validate(make_event(flags=["amount is a range"]))

    assert event.route == Route.FLAG


def test_validate_flags_low_confidence():
    event = validate(make_event(confidence={"classify": 0.3}))

    assert event.route == Route.FLAG
    assert "low confidence on the route" in event.flags


def test_validate_clears_the_invoice_amount_when_not_invoicing():
    assert validate(make_event(route=Route.HOLD)).invoice_amount is None


def test_validate_leaves_a_complete_invoice_alone():
    event = validate(make_event())

    assert event.route == Route.INVOICE
    assert event.invoice_amount == Decimal("1000")


def test_a_resend_of_an_invoiced_contract_is_rejected(tmp_path):
    billing = MockBilling(store_path=tmp_path / "invoices.json")
    billing.create_draft_invoice(make_event())

    resend = check_duplicate(make_event(event_id="gmail:test-002"), billing)

    assert resend.route == Route.REJECT
    assert "duplicate of gmail:test-001" in resend.flags[0]


def test_the_same_event_seen_again_is_not_a_duplicate_of_itself(tmp_path):
    """Re-running the corpus must not reject everything it invoiced last time."""
    billing = MockBilling(store_path=tmp_path / "invoices.json")
    billing.create_draft_invoice(make_event())

    rerun = check_duplicate(make_event(), billing)

    assert rerun.route == Route.INVOICE


def test_billing_refuses_a_second_invoice_for_the_same_thing(tmp_path):
    billing = MockBilling(store_path=tmp_path / "invoices.json")

    first = billing.create_draft_invoice(make_event())
    second = billing.create_draft_invoice(make_event(event_id="gmail:test-002"))

    assert first == second
    assert len(billing.invoices) == 1


# --- ingest: only what a human must review leaves the machine ---


def test_only_invoice_and_flag_cases_reach_the_review_queue():
    events = [
        make_event(event_id="gmail:a", route=Route.INVOICE),
        make_event(event_id="gmail:b", route=Route.FLAG),
        make_event(event_id="gmail:c", route=Route.HOLD),
        make_event(event_id="gmail:d", route=Route.REJECT),
    ]

    rows = rows_for(events, drafts={"gmail:a": "Hi there, invoice attached."})

    assert [row["event_id"] for row in rows] == ["gmail:a", "gmail:b"]
    assert [row["status"] for row in rows] == ["pending", "flagged"]


def test_an_invoice_row_carries_the_billing_facts_and_its_draft():
    row = rows_for([make_event()], drafts={"gmail:test-001": "Hi there."})[0]

    assert row["client_name"] == "Test GmbH"
    assert row["invoice_amount"] == 1000.0
    assert row["currency"] == "EUR"
    assert row["draft_email"] == "Hi there."


def test_a_flagged_row_carries_its_reasons_and_no_draft():
    event = validate(make_event(invoice_amount=None))

    row = rows_for([event], drafts={})[0]

    assert row["status"] == "flagged"
    assert "no amount to invoice" in row["flags"]
    assert row["draft_email"] is None


def test_push_sends_a_bearer_token_and_the_rows(monkeypatch):
    """The HTTP call is stubbed, so the suite stays offline."""
    monkeypatch.setenv("INGEST_URL", "https://example.test/ingest")
    monkeypatch.setenv("INGEST_SECRET", "test-secret")
    sent = {}

    class StubResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"inserted": 1, "updated": 0}

    def stub_post(url, json, headers, timeout):
        sent.update(url=url, rows=json, headers=headers)
        return StubResponse()

    monkeypatch.setattr(ingest.httpx, "post", stub_post)

    result = IngestClient().push([{"event_id": "gmail:a"}])

    assert sent["url"] == "https://example.test/ingest"
    assert sent["headers"]["Authorization"] == "Bearer test-secret"
    assert sent["rows"] == [{"event_id": "gmail:a"}]
    assert result == {"inserted": 1, "updated": 0}


# --- evals: the path is graded, not just the answer ---


def test_an_invoice_must_go_all_the_way_to_a_draft():
    assert expected_path("INVOICE", "INVOICE") == INVOICE_PATH


def test_an_abstain_stops_after_validate():
    assert expected_path("INVOICE", "FLAG") == ABSTAIN_PATH
    assert expected_path("INVOICE", "HOLD") == ABSTAIN_PATH


def test_a_non_contract_must_never_reach_the_extractor():
    """Extracting from marketing and internal mail is what produced invented values."""
    assert expected_path("REJECT", "REJECT") == SHORT_CIRCUIT_PATH
    assert "extract" not in expected_path("REJECT", "REJECT")


def test_a_duplicate_must_be_caught_at_dedup_not_at_billing():
    """The classifier said contract; dedup overturned it. It must stop before billing."""
    path = expected_path("INVOICE", "REJECT")

    assert path == ABSTAIN_PATH
    assert "billing" not in path


def test_trace_is_read_back_as_one_path_per_event():
    records = [
        {"event_id": "gmail:a", "stage": "classify", "payload": {"route": "INVOICE"}},
        {"event_id": "gmail:b", "stage": "classify", "payload": {"route": "REJECT"}},
        {"event_id": "gmail:a", "stage": "extract", "payload": {}},
        {"event_id": "gmail:a", "stage": "validate", "payload": {}},
    ]

    assert paths_from_trace(records) == {
        "gmail:a": ["classify", "extract", "validate"],
        "gmail:b": ["classify"],
    }
    assert classify_routes_from_trace(records) == {"gmail:a": "INVOICE", "gmail:b": "REJECT"}


# --- evals: draft quality ---


def test_a_leftover_placeholder_is_caught_without_an_llm():
    assert has_placeholder("Dear [Client's Name],\n\nPlease find attached.")
    assert has_placeholder("Amount: {{invoice_amount}}")
    assert not has_placeholder("Dear Petra,\n\nPlease find attached the invoice for 24,000 EUR.")


def test_the_wrong_amount_frozen_draft_is_hard_for_the_right_reason():
    """It must fail on the number, not on anything the regex could have caught.

    If this draft carried a placeholder, a judge could score it correctly while being
    blind to factual errors, and the label would prove nothing.
    """
    frozen = FROZEN_WRONG_AMOUNT_DRAFT

    assert not has_placeholder(frozen["draft"])
    assert "19,800" in frozen["draft"]
    assert "18000 EUR" in frozen["facts"]
    assert load_labels()[frozen["event_id"]]["label"] == "fail"


def test_every_frozen_draft_is_labelled():
    """A frozen draft the labels do not mention is judged and then silently ignored."""
    labels = load_labels()

    for frozen in FROZEN_DRAFTS:
        assert frozen["event_id"] in labels


def test_the_hand_labels_cover_both_verdicts():
    """A judge validated only against passes has not been validated."""
    labels = load_labels()

    assert len(labels) >= 6
    assert {label["label"] for label in labels.values()} == {"pass", "fail"}


def test_judge_agreement_counts_only_the_labelled_cases():
    labels = {"gmail:a": {"label": "pass"}, "gmail:b": {"label": "fail"}}
    verdicts = {
        "gmail:a": {"verdict": "pass", "reason": ""},
        "gmail:b": {"verdict": "pass", "reason": "looked fine"},
        "gmail:c": {"verdict": "fail", "reason": "unlabelled, ignored"},
    }

    matched, checked, disagreements = agreement(verdicts, labels)

    assert (matched, checked) == (1, 2)
    assert "gmail:b" in disagreements[0]


# --- the Slack source: only tagged messages become work ---


def test_slack_adapter_emits_only_tagged_messages():
    slack = SlackMock()

    events = slack.fetch()

    assert len(slack.messages) == 3, "the fixture must include untagged chatter to test the filter"
    assert len(events) == 2
    assert [event.event_id for event in events] == list(slack.corpus())
    assert all(event.event_id.startswith("slack:") for event in events)
    assert all(event.source == Source.SLACK for event in events)
    assert all(event.trust_level == TrustLevel.UNTRUSTED for event in events)


def test_every_adapter_mints_the_ids_it_fetches():
    """The scorer keys the golden set off corpus(); it must match what the run produced."""
    for adapter in sources().values():
        assert {event.event_id for event in adapter.fetch()} == set(adapter.corpus())


def test_event_ids_do_not_collide_across_sources():
    corpora = [adapter.corpus() for adapter in sources().values()]

    merged = {key: value for corpus in corpora for key, value in corpus.items()}

    assert len(merged) == sum(len(corpus) for corpus in corpora)


def test_every_event_can_be_read_back_by_its_own_adapter():
    """What run_all's dispatch relies on, checked without an LLM call."""
    adapters = sources()
    for source, adapter in adapters.items():
        for event in adapter.fetch():
            assert event.source is source
            assert adapters[event.source].read_raw(event.raw_ref)


def test_slack_sender_line_is_built_only_from_what_slack_vouches_for():
    """is_internal reads line one. Nothing a sender types may reach it."""
    slack = SlackMock()

    for event in slack.fetch():
        first_line = slack.read_raw(event.raw_ref).splitlines()[0]

        assert first_line.startswith("From: ")
        assert "attacker" not in first_line
        assert not is_internal(slack.read_raw(event.raw_ref))


def test_a_slack_post_from_our_own_domain_is_still_internal():
    assert is_internal("From: sami@younesmotasam.com (Slack #contracts-inbound)")


def test_the_pickup_tag_never_reaches_the_model():
    """A subject line hinting 'invoice' would bias the very classifier we are testing."""
    slack = SlackMock()

    for event in slack.fetch():
        assert PICKUP_TAG not in slack.read_raw(event.raw_ref).splitlines()[1]


def test_every_golden_case_has_the_fields_the_scorer_reads():
    """golden_value() does expected[field]; a missing key is a KeyError halfway through a run."""
    for adapter in sources().values():
        for event_id, fixture in adapter.corpus().items():
            assert "expected_route" in fixture, event_id
            missing = [f for f in GRADED_FIELDS if f not in fixture["expected"]]
            assert not missing, f"{event_id} is missing {missing}"


def test_the_injection_case_names_what_must_never_appear():
    cases = [f for f in SlackMock().corpus().values() if f["expected"].get("must_not_appear")]

    assert len(cases) == 1
    injection = cases[0]
    assert "attacker@x.com" in injection["expected"]["must_not_appear"]
    assert "attacker@x.com" in injection["text"], "the bait must really be in the message"
    assert injection["expected_route"] in {"HOLD", "FLAG"}, "never a route that bills"


# --- Stripe billing client: offline. Nothing here constructs a live session. ---


def test_stripe_refuses_a_missing_key(monkeypatch):
    monkeypatch.delenv("STRIPE_RESTRICTED_KEY", raising=False)

    with pytest.raises(RuntimeError, match="must be set"):
        StripeBilling()


def test_stripe_refuses_a_live_key():
    """The one mistake that cannot be undone is billing a real client from a test run."""
    for live_key in ["sk_live_abc123", "rk_live_abc123"]:
        with pytest.raises(RuntimeError, match="not a Stripe TEST key"):
            StripeBilling(api_key=live_key)


def test_stripe_refuses_anything_that_is_not_a_stripe_key():
    with pytest.raises(RuntimeError, match="not a Stripe TEST key"):
        StripeBilling(api_key="c29tZS1vdGhlci1zZXJ2aWNlLXNlY3JldA==")


def test_stripe_accepts_a_test_key():
    assert StripeBilling(api_key="rk_test_abc123").api_key == "rk_test_abc123"


def test_stripe_and_mock_agree_on_what_makes_two_invoices_the_same():
    """Both dedup on client|amount|currency. If these drift, one of them double-bills."""
    from finos.billing.mock_billing import _signature as mock_signature

    event = make_event()

    assert _signature(event) == mock_signature(event)


def test_amounts_are_converted_to_the_smallest_currency_unit():
    assert _minor_units(Decimal("12500")) == 1250000
    assert _minor_units(Decimal("6000.50")) == 600050
    assert _minor_units(Decimal("0.01")) == 1


def test_both_billing_clients_implement_the_whole_interface():
    """The point of the seam: Stripe drops in behind BillingClient without a rewrite."""
    required = ["match_or_create_customer", "invoiced_by", "create_draft_invoice"]

    for client in (MockBilling, StripeBilling):
        missing = [name for name in required if not callable(getattr(client, name, None))]
        assert not missing, f"{client.__name__} is missing {missing}"


def test_the_scorer_never_bills_through_stripe():
    """score.py calls run_all() with no arguments; billing must default to the mock."""
    import inspect

    from finos.run import run_all

    assert inspect.signature(run_all).parameters["use_stripe"].default is False


def test_stripe_reads_metadata_the_only_way_that_works(monkeypatch):
    """Regression: Stripe returns metadata as a StripeObject, not a dict.

    It has no .get() and dict() on it raises, so the obvious `(meta or {}).get(k)` blows up.
    This only fires once the account already holds invoices, i.e. on the SECOND run, which
    is exactly the run that proves we do not bill a client twice.
    """

    class StripeObjectStub:
        """Mimics the real thing: subscriptable and to_dict()-able, but no .get()."""

        def __init__(self, data):
            self._data = data

        def __getattr__(self, name):
            raise AttributeError(name)  # .get() must fail, as it does in the SDK

        def to_dict(self):
            return dict(self._data)

    class InvoiceStub:
        id = "in_existing"
        metadata = StripeObjectStub({
            "finos_event_id": "slack:C1-123.456",
            "finos_signature": "velasco partners s.l.|12500|EUR",
        })

    class Listing:
        def __init__(self, items):
            self.items = items

        def auto_paging_iter(self):
            return iter(self.items)

    monkeypatch.setattr(stripe_billing.stripe_sdk.Customer, "list",
                        lambda **kwargs: Listing([]))
    monkeypatch.setattr(stripe_billing.stripe_sdk.Invoice, "list",
                        lambda **kwargs: Listing([InvoiceStub()]))

    billing = StripeBilling(api_key="rk_test_abc123")
    event = make_event(client_name="Velasco Partners S.L.",
                       invoice_amount=Decimal("12500"), currency="EUR")

    # The whole point: a re-run finds the existing draft instead of creating a second one.
    assert billing.invoiced_by(event) == "slack:C1-123.456"
    assert billing.create_draft_invoice(event) == "in_existing"


# --- the worker: nothing moves without a human approval and an explicit flag ---


def queue_with(tmp_path, rows) -> StubReviewQueue:
    path = tmp_path / "review_queue.json"
    path.write_text(json.dumps(rows))
    return StubReviewQueue(store_path=path)


def billing_with_draft(tmp_path, invoice_id="inv-001") -> MockBilling:
    billing = MockBilling(store_path=tmp_path / "invoices.json")
    billing.create_draft_invoice(make_event())
    assert billing.invoice_status(invoice_id) == "draft"
    return billing


ROW = {"event_id": "gmail:test-001", "client_name": "Test GmbH", "invoice_amount": 1000,
       "currency": "EUR", "stripe_invoice_id": "inv-001"}


def test_the_queue_returns_only_approved_rows(tmp_path):
    """The approval gate. Everything else in the worker depends on this filter."""
    queue = queue_with(tmp_path, [
        {**ROW, "event_id": "a", "status": "approved"},
        {**ROW, "event_id": "b", "status": "pending"},
        {**ROW, "event_id": "c", "status": "flagged"},
        {**ROW, "event_id": "d", "status": "rejected"},
        {**ROW, "event_id": "e", "status": "sent"},
    ])

    assert [row["event_id"] for row in queue.approved_rows()] == ["a"]


def test_a_dry_run_changes_nothing(tmp_path):
    queue = queue_with(tmp_path, [{**ROW, "status": "approved"}])
    billing = billing_with_draft(tmp_path)

    tally = process(queue, billing, send=False)

    assert tally == {"approved": 1, "finalised": 0, "skipped": 0, "would_finalise": 1}
    assert billing.invoice_status("inv-001") == "draft"       # untouched
    assert queue.rows[0]["status"] == "approved"              # untouched


def test_send_finalises_the_invoice_and_marks_the_row(tmp_path):
    queue = queue_with(tmp_path, [{**ROW, "status": "approved"}])
    billing = billing_with_draft(tmp_path)

    tally = process(queue, billing, send=True)

    assert tally["finalised"] == 1
    assert billing.invoice_status("inv-001") == "open"
    assert queue.rows[0]["status"] == "sent"
    assert queue.rows[0]["stripe_invoice_id"] == "inv-001"


def test_running_twice_never_finalises_twice(tmp_path):
    """The idempotency proof, offline. A re-run must be a safe no-op."""
    queue = queue_with(tmp_path, [{**ROW, "status": "approved"}])
    billing = billing_with_draft(tmp_path)

    process(queue, billing, send=True)
    second = process(queue, billing, send=True)

    assert second == {"approved": 0, "finalised": 0, "skipped": 0, "would_finalise": 0}
    assert billing.invoice_status("inv-001") == "open"


def test_an_already_open_invoice_is_skipped_even_if_the_row_says_approved(tmp_path):
    """Belt and braces: if the row and Stripe disagree, Stripe's status wins."""
    queue = queue_with(tmp_path, [{**ROW, "status": "approved"}])
    billing = billing_with_draft(tmp_path)
    billing.finalise_invoice("inv-001")

    tally = process(queue, billing, send=True)

    assert tally == {"approved": 1, "finalised": 0, "skipped": 1, "would_finalise": 0}
    assert queue.rows[0]["status"] == "approved"  # not marked sent, because nothing was sent


def test_a_row_with_no_invoice_id_is_skipped_not_guessed(tmp_path):
    queue = queue_with(tmp_path, [{**ROW, "status": "approved", "stripe_invoice_id": None}])
    billing = billing_with_draft(tmp_path)

    tally = process(queue, billing, send=True)

    assert tally["skipped"] == 1 and tally["finalised"] == 0


def test_both_billing_clients_can_finalise():
    """Same seam as before: the worker must not care which one it holds."""
    from finos.billing.stripe import StripeBilling

    for client in (MockBilling, StripeBilling):
        for name in ("invoice_status", "finalise_invoice"):
            assert callable(getattr(client, name, None)), f"{client.__name__}.{name}"


# --- the live review queue: HTTP stubbed, so the suite stays offline ---


def test_the_app_host_is_derived_from_the_ingest_url(monkeypatch):
    """One host, two secrets. Nothing hardcoded."""
    monkeypatch.delenv("REVIEW_APP_URL", raising=False)
    monkeypatch.setenv("INGEST_URL", "https://app.example.test/api/public/ingest")

    assert base_url() == "https://app.example.test"


def test_an_explicit_review_app_url_wins(monkeypatch):
    monkeypatch.setenv("REVIEW_APP_URL", "https://other.example.test/")
    monkeypatch.setenv("INGEST_URL", "https://app.example.test/api/public/ingest")

    assert base_url() == "https://other.example.test"


def test_the_queue_refuses_to_start_without_the_send_secret(monkeypatch):
    monkeypatch.delenv("SEND_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="SEND_SECRET"):
        HttpReviewQueue(base="https://app.example.test")


def test_approved_rows_sends_the_bearer_and_returns_the_rows(monkeypatch):
    sent = {}

    class StubResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return [{"event_id": "gmail:a", "status": "approved"}]

    def stub_get(url, headers, timeout):
        sent.update(url=url, headers=headers)
        return StubResponse()

    monkeypatch.setattr(http_queue.httpx, "get", stub_get)

    rows = HttpReviewQueue(base="https://app.example.test", secret="s3cret").approved_rows()

    assert sent["url"] == "https://app.example.test/api/public/approved"
    assert sent["headers"]["Authorization"] == "Bearer s3cret"
    assert rows == [{"event_id": "gmail:a", "status": "approved"}]


def test_mark_sent_posts_the_event_and_invoice_id(monkeypatch):
    sent = {}

    class StubResponse:
        def raise_for_status(self):
            pass

    def stub_post(url, json, headers, timeout):
        sent.update(url=url, body=json, headers=headers)
        return StubResponse()

    monkeypatch.setattr(http_queue.httpx, "post", stub_post)

    HttpReviewQueue(base="https://app.example.test", secret="s3cret").mark_sent("gmail:a", "in_1")

    assert sent["url"] == "https://app.example.test/api/public/mark-sent"
    assert sent["body"] == {"event_id": "gmail:a", "stripe_invoice_id": "in_1"}
    assert sent["headers"]["Authorization"] == "Bearer s3cret"


def test_a_non_list_response_is_refused_rather_than_acted_on(monkeypatch):
    """Never act on a shape we do not understand."""

    class StubResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"error": "something went wrong"}

    monkeypatch.setattr(http_queue.httpx, "get", lambda url, headers, timeout: StubResponse())

    with pytest.raises(RuntimeError, match="list of rows"):
        HttpReviewQueue(base="https://app.example.test", secret="s3cret").approved_rows()


def test_a_failed_read_stops_the_worker_before_it_finalises_anything(monkeypatch, tmp_path):
    """A 401 must never be treated as 'no approved rows'."""

    class Boom:
        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "401", request=httpx.Request("GET", "https://app.example.test"),
                response=httpx.Response(401))

        def json(self):
            return []

    monkeypatch.setattr(http_queue.httpx, "get", lambda url, headers, timeout: Boom())
    queue = HttpReviewQueue(base="https://app.example.test", secret="wrong")
    billing = billing_with_draft(tmp_path)

    with pytest.raises(httpx.HTTPStatusError):
        process(queue, billing, send=True)

    assert billing.invoice_status("inv-001") == "draft"  # nothing was touched


# --- the row carries the invoice the worker will finalise ---


def test_an_invoice_row_carries_its_stripe_invoice_id():
    rows = rows_for([make_event()], drafts={}, invoice_ids={"gmail:test-001": "in_abc123"})

    assert rows[0]["stripe_invoice_id"] == "in_abc123"


def test_a_flagged_row_carries_no_invoice_id():
    event = validate(make_event(invoice_amount=None))

    row = rows_for([event], drafts={}, invoice_ids={})[0]

    assert row["status"] == "flagged"
    assert row["stripe_invoice_id"] is None


def test_rows_without_invoice_ids_still_build():
    """The mock path pushes no ids at all; the field must simply be null, not missing."""
    row = rows_for([make_event()], drafts={})[0]

    assert "stripe_invoice_id" in row
    assert row["stripe_invoice_id"] is None


def test_a_finalised_invoice_still_counts_as_already_invoiced(monkeypatch):
    """Regression: once the worker finalises an invoice it is no longer a draft.

    If the index only held drafts, the next pipeline run would not see it, would believe
    the contract was never invoiced, and would raise a SECOND invoice for the same client,
    amount and currency. That is a wrong invoice.
    """
    listed = {}

    class StripeObjectStub:
        def __init__(self, data):
            self._data = data

        def __getattr__(self, name):
            raise AttributeError(name)

        def to_dict(self):
            return dict(self._data)

    class OpenInvoice:
        id = "in_already_open"
        status = "open"
        metadata = StripeObjectStub({
            "finos_event_id": "gmail:test-001",
            "finos_signature": "test gmbh|1000|EUR",
        })

    class Listing:
        def __init__(self, items):
            self.items = items

        def auto_paging_iter(self):
            return iter(self.items)

    def spy_list(**kwargs):
        listed.update(kwargs)
        return Listing([OpenInvoice()])

    monkeypatch.setattr(stripe_billing.stripe_sdk.Customer, "list", lambda **kw: Listing([]))
    monkeypatch.setattr(stripe_billing.stripe_sdk.Invoice, "list", spy_list)

    billing = StripeBilling(api_key="rk_test_abc123")
    event = make_event()

    assert billing.invoiced_by(event) == "gmail:test-001"
    assert billing.create_draft_invoice(event) == "in_already_open"
    # Checked after the lazy load has actually run, or it proves nothing.
    assert "status" not in listed, "the listing must not filter to drafts only"
