"""Broker/Feedbrain adapter: no database or external services required."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from info_hub.action_broker import (
    CapabilityBroker,
    ToolExecutionError,
    safe_error_code,
    safe_error_external_ref,
    safe_error_message,
)
from info_hub.action_workflow import WorkflowValidationError
from info_hub.feedbrain_adapter import FeedbrainSyncAdapter, _http_json


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.sleeps.append(seconds)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, timeout):
        self.calls.append((method, url, timeout))
        if not self.responses:
            raise AssertionError("Unexpected extra HTTP request")
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def queued(run_id=73, subscription_id=11):
    return (202, {"id": run_id, "subscription_id": subscription_id, "status": "queued"})


def run(status="completed", run_id=73, subscription_id=11, **changes):
    body = {
        "id": run_id, "subscription_id": subscription_id, "status": status,
        "items_seen": 3, "items_created": 2, "items_updated": 1,
    }
    body.update(changes)
    return (200, body)


def make_adapter(responses, **overrides):
    transport = FakeTransport(responses)
    clock = FakeClock()
    options = {
        "base_url": "http://api:8000",
        "transport": transport,
        "monotonic": clock.monotonic,
        "sleep": clock.sleep,
        "poll_interval": 2,
        "max_wait_seconds": 30,
        "request_timeout": 5,
    }
    options.update(overrides)
    return FeedbrainSyncAdapter(**options), transport, clock


def step(source=None, capability="information.sync", tool="feedbrain"):
    if source is None:
        source = {"type": "subscription", "id": 11}
    return {
        "id": "refresh", "tool": tool, "capability": capability,
        "with": {"source": source},
    }


class BrokerTests(unittest.TestCase):
    def test_successful_dispatch_waits_until_completed(self):
        adapter, http, clock = make_adapter(
            [queued(), run("queued"), run("running"), run("completed")],
        )
        result = CapabilityBroker([adapter]).dispatch_step(step())
        self.assertEqual(result.step_id, "refresh")
        self.assertEqual(result.tool, "feedbrain")
        self.assertEqual(result.capability, "information.sync")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.external_run_ref, "feedbrain:ingestion_run:73")
        self.assertEqual(result.details["counts"]["items_created"], 2)
        self.assertEqual(result.details["source"], {"type": "subscription", "id": 11})
        self.assertEqual(
            [(method, url) for method, url, _ in http.calls],
            [
                ("POST", "http://api:8000/subscriptions/11/sync"),
                ("GET", "http://api:8000/runs/73"),
                ("GET", "http://api:8000/runs/73"),
                ("GET", "http://api:8000/runs/73"),
            ],
        )
        self.assertEqual(clock.sleeps, [2, 2])

    def test_accepted_external_reference_is_reported_before_polling(self):
        notifications = []
        adapter, http, _ = make_adapter([queued(), run()])
        result = CapabilityBroker([adapter]).dispatch_step(
            step(), on_external_ref=notifications.append,
        )
        self.assertEqual(notifications, ["feedbrain:ingestion_run:73"])
        self.assertEqual(result.external_run_ref, notifications[0])
        self.assertEqual(len(http.calls), 2)

    def test_unsupported_source_type_is_rejected_without_http(self):
        adapter, http, _ = make_adapter([])
        with self.assertRaises(ToolExecutionError) as exc:
            CapabilityBroker([adapter]).dispatch_step(step({"type": "collection", "id": 11}))
        self.assertEqual(exc.exception.code, "invalid_source")
        self.assertEqual(http.calls, [])

    def test_preflight_accepts_saved_workflow_without_schedule(self):
        adapter, http, _ = make_adapter([])
        broker = CapabilityBroker([adapter])
        normalized = {
            "name": "On-demand sync", "instruction": "Sync when requested",
            "workflow": {"schema": 1, "steps": [step()]},
            "schedule": None,
        }
        steps = broker.preflight(normalized)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["tool"], "feedbrain")
        self.assertEqual(http.calls, [])

    def test_preflight_rejects_unknown_source_before_any_step(self):
        adapter, http, _ = make_adapter([])
        broker = CapabilityBroker([adapter])
        definition = {
            "name": "Check feeds", "instruction": "Collect data",
            "workflow": {
                "schema": 1, "steps": [
                    step(), {"id": "next", "tool": "feedbrain",
                             "capability": "information.sync",
                             "with": {"source": {"type": "collection", "id": 11}}},
                ],
            },
        }
        with self.assertRaises(ToolExecutionError) as error:
            broker.preflight(definition)
        self.assertEqual(error.exception.code, "invalid_source")
        self.assertEqual(http.calls, [])

    def test_missing_capability_is_rejected_before_http(self):
        adapter, http, _ = make_adapter([])
        with self.assertRaisesRegex(WorkflowValidationError, "Capabilities not available"):
            CapabilityBroker([adapter]).dispatch_step(step(capability="data.delete"))
        self.assertEqual(http.calls, [])

    def test_instruction_instead_of_tool_is_not_run(self):
        adapter, http, _ = make_adapter([])
        with self.assertRaises(ToolExecutionError):
            CapabilityBroker([adapter]).dispatch_step({
                "id": "bad", "tool": "feedbrain", "capability": "information.sync",
                "with": {
                    "source": {"type": "subscription", "id": 11},
                    "url": "https://untrusted.invalid",
                },
            })
        self.assertEqual(http.calls, [])

    def test_malicious_step_field_is_rejected(self):
        adapter, http, _ = make_adapter([])
        bad = step()
        bad["shell"] = "echo never"
        with self.assertRaises(WorkflowValidationError):
            CapabilityBroker([adapter]).dispatch_step(bad)
        self.assertEqual(http.calls, [])

    def test_duplicate_capability_binding_is_rejected(self):
        adapter, _, _ = make_adapter([])
        with self.assertRaisesRegex(ValueError, "Duplicate tool adapter"):
            CapabilityBroker([adapter, adapter])

    def test_empty_broker_is_allowed(self):
        broker = CapabilityBroker([])
        self.assertEqual(broker.capabilities, frozenset())
        with self.assertRaises(WorkflowValidationError):
            broker.dispatch_step(step())

    def test_failed_external_run_preserves_reference(self):
        adapter, _, _ = make_adapter([queued(), run("failed", error="private RSS error")])
        with self.assertRaises(ToolExecutionError) as exc:
            CapabilityBroker([adapter]).dispatch_step(step())
        self.assertEqual(exc.exception.code, "external_run_failed")
        self.assertEqual(exc.exception.external_run_ref, "feedbrain:ingestion_run:73")
        self.assertNotIn("private RSS error", str(exc.exception))

    def test_timeout_records_external_run(self):
        adapter, http, clock = make_adapter(
            [queued(), run("running"), run("running")],
            max_wait_seconds=4,
        )
        with self.assertRaises(ToolExecutionError) as exc:
            CapabilityBroker([adapter]).dispatch_step(step())
        self.assertEqual(exc.exception.code, "timeout")
        self.assertEqual(exc.exception.external_run_ref, "feedbrain:ingestion_run:73")
        self.assertEqual(len(http.calls), 3)
        self.assertEqual(clock.now, 4)

    def test_post_http_error(self):
        adapter, _, _ = make_adapter([
            ToolExecutionError("http_error", "Feedbrain returned HTTP 409", tool="feedbrain")
        ])
        with self.assertRaises(ToolExecutionError) as exc:
            CapabilityBroker([adapter]).dispatch_step(step())
        self.assertEqual(exc.exception.code, "http_error")
        self.assertIsNone(exc.exception.external_run_ref)

    def test_get_transport_failure_retains_run_reference(self):
        adapter, _, _ = make_adapter([
            queued(),
            ToolExecutionError("transport_error", "GET failed", tool="feedbrain"),
        ])
        with self.assertRaises(ToolExecutionError) as exc:
            CapabilityBroker([adapter]).dispatch_step(step())
        self.assertEqual(exc.exception.code, "transport_error")
        self.assertEqual(exc.exception.external_run_ref, "feedbrain:ingestion_run:73")

    def test_wrong_post_subscription_is_rejected(self):
        adapter, http, _ = make_adapter([queued(subscription_id=222)])
        with self.assertRaises(ToolExecutionError) as exc:
            CapabilityBroker([adapter]).dispatch_step(step())
        self.assertEqual(exc.exception.code, "invalid_response")
        self.assertEqual(len(http.calls), 1)

    def test_wrong_run_identity_is_rejected(self):
        for response in (run(run_id=99), run(subscription_id=12)):
            with self.subTest(response=response):
                adapter, _, _ = make_adapter([queued(), response])
                with self.assertRaises(ToolExecutionError) as exc:
                    CapabilityBroker([adapter]).dispatch_step(step())
                self.assertEqual(exc.exception.code, "invalid_response")
                self.assertEqual(
                    exc.exception.external_run_ref, "feedbrain:ingestion_run:73",
                )

    def test_unrecognized_status_fails(self):
        adapter, _, _ = make_adapter([queued(), run("almost-complete")])
        with self.assertRaises(ToolExecutionError) as exc:
            CapabilityBroker([adapter]).dispatch_step(step())
        self.assertEqual(exc.exception.code, "invalid_response")

    def test_malformed_run_counts_fail(self):
        for invalid in (-1, None, True, "3"):
            with self.subTest(invalid=invalid):
                adapter, _, _ = make_adapter([queued(), run(items_seen=invalid)])
                with self.assertRaises(ToolExecutionError) as exc:
                    CapabilityBroker([adapter]).dispatch_step(step())
                self.assertEqual(exc.exception.code, "invalid_response")

    def test_post_must_return_202(self):
        adapter, _, _ = make_adapter([(200, queued()[1])])
        with self.assertRaises(ToolExecutionError) as exc:
            CapabilityBroker([adapter]).dispatch_step(step())
        self.assertEqual(exc.exception.code, "invalid_response")

    def test_post_must_return_positive_integer_run_id(self):
        for invalid in (True, None, 0, -4, "73"):
            with self.subTest(invalid=invalid):
                adapter, _, _ = make_adapter([(202, {
                    "id": invalid, "subscription_id": 11,
                })])
                with self.assertRaises(ToolExecutionError) as exc:
                    CapabilityBroker([adapter]).dispatch_step(step())
                self.assertEqual(exc.exception.code, "invalid_response")

    def test_adapter_direct_validation(self):
        adapter, http, _ = make_adapter([])
        for params in (
            {},
            {"source": {"type": "subscription", "id": 11}, "url": "http://example.org"},
        ):
            with self.subTest(params=params):
                with self.assertRaises(ToolExecutionError):
                    adapter.execute("information.sync", params)
        with self.assertRaises(ToolExecutionError):
            adapter.execute("misc.other", {"source": {"type": "subscription", "id": 11}})
        self.assertEqual(http.calls, [])


class SourceAndToolSelectionTests(unittest.TestCase):
    def test_invalid_feedbrain_source_types_and_ids_are_rejected(self):
        invalid = (
            {}, "ai_articles", 11, True, [],
            {"type": "collection", "id": 11},
            {"type": "subscription", "id": 0},
            {"type": "subscription", "id": True},
            {"type": "subscription", "id": "11"},
            {"type": "subscription", "id": 2_147_483_648},
            {"type": "subscription", "id": 11, "url": "https://evil.invalid"},
        )
        for source in invalid:
            with self.subTest(source=source):
                adapter, http, _ = make_adapter([])
                with self.assertRaises(ToolExecutionError) as exc:
                    CapabilityBroker([adapter]).dispatch_step(step(source))
                self.assertEqual(exc.exception.code, "invalid_source")
                self.assertEqual(http.calls, [])

    def test_tool_selection_cannot_be_overridden_by_http_url(self):
        adapter, http, _ = make_adapter([])
        with self.assertRaises(ToolExecutionError) as exc:
            CapabilityBroker([adapter]).dispatch_step(step(tool="other_tool"))
        self.assertEqual(exc.exception.code, "tool_unavailable")
        self.assertEqual(http.calls, [])

    def test_other_tool_can_support_same_capability(self):
        class OtherAdapter:
            name = "other_tool"
            capabilities = frozenset({"information.sync"})

            def validate_parameters(self, capability, parameters):
                if parameters.get("source") != {"type": "file", "id": "report.txt"}:
                    raise ToolExecutionError("invalid_source", "Requires a file")

            def execute(self, capability, parameters, on_external_ref=None):
                return {
                    "status": "completed",
                    "external_run_ref": "other_tool:resource:1",
                    "source": parameters["source"],
                }

        adapter, feedbrain_http, _ = make_adapter([])
        broker = CapabilityBroker([adapter, OtherAdapter()])
        result = broker.dispatch_step(
            step(source={"type": "file", "id": "report.txt"}, tool="other_tool"),
        )
        self.assertEqual(result.tool, "other_tool")
        self.assertEqual(result.details["source"], {"type": "file", "id": "report.txt"})
        self.assertEqual(feedbrain_http.calls, [])

    def test_base_url_must_be_trusted_service_root(self):
        for url in ("javascript:console.log(1)", "http://user:pass@api:8000",
                    "http://api:8000/some/path", "http://api:8000/?source=x",
                    "file:///etc/passwd", "http://"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    FeedbrainSyncAdapter(base_url=url)


class ResultSafetyTests(unittest.TestCase):
    """The Action history stores a bounded receipt, not provider-owned payloads."""

    @staticmethod
    def dispatch(payload, *, report_ref=None, callback=None):
        class ResultAdapter:
            name = "sample"
            capabilities = frozenset({"information.sync"})

            def validate_parameters(self, capability, parameters):
                pass

            def execute(self, capability, parameters, on_external_ref=None):
                if report_ref is not None:
                    on_external_ref(report_ref)
                return payload

        return CapabilityBroker([ResultAdapter()]).dispatch_step(
            step(tool="sample"), on_external_ref=callback,
        )

    def test_small_json_receipt_is_preserved(self):
        receipt = {
            "status": "completed",
            "external_run_ref": "sample:run:5",
            "resource": {"id": "file-27", "mime_type": "application/pdf"},
            "counts": [1, 2, 3],
        }
        outcome = self.dispatch(receipt)
        self.assertEqual(outcome.external_run_ref, "sample:run:5")
        self.assertEqual(
            outcome.details, {
                "resource": {"id": "file-27", "mime_type": "application/pdf"},
                "counts": [1, 2, 3],
            },
        )

    def test_sensitive_fields_removed_at_any_nesting_level(self):
        outcome = self.dispatch({
            "status": "completed", "external_run_ref": "sample:run:5",
            "credentials": {"password": "never-save", "apiKey": "bad-value"},
            "items": [
                {"id": "safe", "access_token": "token-secret"},
                {"value": {"client_secret": "also-secret", "name": "visible"}},
            ],
            "notes": "ordinary text",
        })
        rendered = json.dumps(outcome.details)
        for secret in ("never-save", "bad-value", "token-secret", "also-secret"):
            self.assertNotIn(secret, rendered)
        self.assertEqual(outcome.details["items"][0], {"id": "safe"})
        self.assertEqual(outcome.details["items"][1]["value"], {"name": "visible"})
        self.assertEqual(outcome.details["notes"], "ordinary text")
        self.assertTrue(outcome.details["_action_result_redacted"])

    def test_credential_looking_strings_and_signed_urls_are_redacted(self):
        outcome = self.dispatch({
            "status": "completed",
            "instructions": ["Authorization: Bearer verysecret123", "read this"],
            "link": "https://example.invalid/file?access_token=abcdef",
            "ordinary_url": "https://example.invalid/file?id=24",
            "url_with_userinfo": "https://user:password@example.invalid/private",
            "token": "sample-sensitive",
        })
        self.assertEqual(outcome.details["instructions"], ["[REDACTED]", "read this"])
        self.assertEqual(outcome.details["link"], "[REDACTED]")
        self.assertEqual(outcome.details["ordinary_url"], "https://example.invalid/file?id=24")
        self.assertEqual(outcome.details["url_with_userinfo"], "[REDACTED]")
        self.assertNotIn("token", outcome.details)
        self.assertTrue(outcome.details["_action_result_redacted"])

    def test_large_response_is_omitted_but_external_ref_and_success_remain(self):
        outcome = self.dispatch({
            "status": "completed",
            "external_run_ref": "sample:run:8",
            "large": ["x" * 1000 for _ in range(60)],
        })
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.external_run_ref, "sample:run:8")
        self.assertEqual(outcome.details, {"_action_result_omitted": "too_large"})

    def test_too_many_nodes_or_nested_levels_are_omitted(self):
        for value in (
            [[{"value": "x"} for _ in range(90)] for _ in range(8)],
            {"next": {"next": {"next": {"next": {"next": {"next": 5}}}}}},
        ):
            with self.subTest(value=str(value)[:45]):
                outcome = self.dispatch({"status": "completed", "data": value})
                self.assertEqual(outcome.details, {"_action_result_omitted": "too_large"})

    def test_malformed_json_response_is_omitted_without_failing_completed_job(self):
        for value in (set([1, 2]), object(), float("nan"), {"a": object()}):
            with self.subTest(type=type(value).__name__):
                outcome = self.dispatch({
                    "status": "completed", "external_run_ref": "sample:run:12",
                    "data": value,
                })
                self.assertEqual(outcome.status, "completed")
                self.assertEqual(outcome.external_run_ref, "sample:run:12")
                self.assertEqual(
                    outcome.details, {"_action_result_omitted": "not_json_compatible"},
                )

    def test_secret_filter_handles_reserved_fields_and_nonstr_keys(self):
        outcome = self.dispatch({
            "status": "completed",
            "_action_result_omitted": "some claimed reason",
            "data": {"status": "okay"},
        })
        self.assertEqual(outcome.details["data"], {"status": "okay"})
        self.assertNotIn("_action_result_omitted", outcome.details)
        self.assertTrue(outcome.details["_action_result_redacted"])
        outcome = self.dispatch({"status": "completed", "data": {1: "bad"}})
        self.assertEqual(outcome.details, {"_action_result_omitted": "not_json_compatible"})

    def test_invalid_external_references_are_never_forwarded_or_returned(self):
        for ref in (
            "", "x" * 241, "sample:run:8\nBAD",
            "https://sample.invalid/run?token=secret",
            "sample:run:8#token",
        ):
            with self.subTest(ref=ref[:40]):
                for via_callback in (False, True):
                    observed = []
                    result = {
                        "status": "completed",
                        "external_run_ref": "sample:run:1" if via_callback else ref,
                    }
                    with self.assertRaises(ToolExecutionError) as raised:
                        self.dispatch(
                            result,
                            report_ref=ref if via_callback else None,
                            callback=observed.append,
                        )
                    self.assertEqual(raised.exception.code, "invalid_tool_result")
                    self.assertEqual(observed, [])

    def test_valid_external_reference_callback_still_runs(self):
        observed = []
        outcome = self.dispatch(
            {"status": "completed", "external_run_ref": "sample:run:18"},
            report_ref="sample:run:18", callback=observed.append,
        )
        self.assertEqual(observed, ["sample:run:18"])
        self.assertEqual(outcome.external_run_ref, observed[0])

    def test_error_ref_and_message_checked_before_persistence(self):
        self.assertEqual(safe_error_code("external_run_failed"), "external_run_failed")
        self.assertEqual(safe_error_code("x" * 200), "tool_error")
        self.assertEqual(safe_error_code("password=example"), "tool_error")
        self.assertEqual(
            safe_error_external_ref("sample:job:3", "sample"), "sample:job:3",
        )
        for unsafe in (
            "https://bob:password@example.invalid/run",
            "https://sample.invalid/job?token=secret",
            "sample:job:3\nINJECT", "x" * 241,
        ):
            with self.subTest(ref=unsafe[:40]):
                self.assertIsNone(safe_error_external_ref(unsafe, "sample"))
        self.assertEqual(safe_error_message("Feedbrain returned HTTP 503"),
                         "Feedbrain returned HTTP 503")
        self.assertEqual(
            safe_error_message("Authorization: Bearer protected_value"),
            "Tool error details omitted",
        )
        self.assertEqual(
            safe_error_message("x" * 1100), "Tool error details omitted",
        )


class LocalHttpAdapterTests(unittest.TestCase):
    def test_actual_http_roundtrip_without_external_feedbrain(self):
        requests_seen = []

        class FakeFeedbrainHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests_seen.append(("POST", self.path))
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(queued()[1]).encode())

            def do_GET(self):
                requests_seen.append(("GET", self.path))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(run()[1]).encode())

            def log_message(self, *_args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeFeedbrainHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            adapter = FeedbrainSyncAdapter(base_url=base)
            outcome = CapabilityBroker([adapter]).dispatch_step(step())
            self.assertEqual(outcome.external_run_ref, "feedbrain:ingestion_run:73")
            self.assertEqual(requests_seen, [
                ("POST", "/subscriptions/11/sync"), ("GET", "/runs/73"),
            ])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_redirect_does_not_follow(self):
        class RedirectHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302)
                self.send_header("Location", "http://example.com/")
                self.end_headers()

            def log_message(self, *_args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            with self.assertRaises(ToolExecutionError) as exc:
                _http_json("POST", f"{base}/subscriptions/11/sync", 3)
            self.assertEqual(exc.exception.code, "http_error")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
