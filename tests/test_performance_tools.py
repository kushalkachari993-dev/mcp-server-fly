import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.performance_utils import service, tool


def entry(**fields):
    value = {"request": {"method": "GET", "url": "https://example.com/health?token=QUERY_SECRET"},
             "response": {"status": 200, "bodySize": 10, "content": {"mimeType": "text/html", "size": 15}},
             "time": 50, "startedDateTime": "2026-10-03T12:00:00Z",
             "timings": {"dns": 2, "connect": 5, "ssl": 3, "send": 1, "wait": 40, "receive": 4, "blocked": -1}}
    value.update(fields)
    return value


def har(entries=(), **fields):
    return json.dumps({"log": {"version": "1.2", "entries": list(entries), **fields}})


def metric(kind="counter", values=None, **fields):
    return {"type": kind, "contains": "default", "values": {"count": 10, "rate": 2} if values is None else values, **fields}


def legacy(metrics=None, **fields):
    return json.dumps({"metrics": {"http_reqs": metric()} if metrics is None else metrics,
                       "state": {"testRunDurationMs": 5000}, **fields})


def machine(metrics=(), checks=None, **fields):
    results = {"metrics": list(metrics)}
    if checks is not None:
        results["checks"] = checks
    return json.dumps({"version": "1.0.0", "metadata": {"k6Version": "1.5.0", "generatedAt": "2026-10-03T12:00:00Z"},
                       "config": {"duration": 5, "execution": "local"}, "results": results, **fields})


class PerformanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("performance-tests")
        tool.register(self.mcp)

    async def call(self, name, content, **arguments):
        result = await self.mcp.call_tool(name, {"content": content, **arguments})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def har(self, content, **arguments):
        return json.loads(await self.call("inspect_har", content, **arguments))

    async def k6(self, content, **arguments):
        return json.loads(await self.call("inspect_k6_summary", content, **arguments))

    async def test_har_statuses_timing_statistics_and_response_sizes(self):
        result = await self.har(har([entry(), entry(response={"status": 404, "bodySize": -1}, time=100),
                                          entry(response={"status": 503, "bodySize": 20}),
                                          entry(response={"status": 0, "bodySize": -1, "content": {"mimeType": ""}})]))
        self.assertEqual(result["entry_count"], 4)
        self.assertEqual(result["status_counts"], {"0": 1, "200": 1, "404": 1, "503": 1})
        self.assertEqual(result["client_error_count"], 1)
        self.assertEqual(result["server_error_count"], 1)
        self.assertEqual(result["zero_status_count"], 1)
        self.assertEqual(result["duration_ms"]["mean"], 62.5)
        self.assertEqual(result["duration_ms"]["median"], 50)
        self.assertEqual(result["slowest_requests"][0]["time_ms"], 100)
        self.assertEqual(result["response_body_bytes"], {"reported_total": 30, "unknown_count": 2})
        self.assertEqual(result["response_content_bytes"], {"reported_total": 15, "unknown_count": 3})
        self.assertEqual(len(result["error_requests"]), 3)

    async def test_har_credentials_headers_cookies_bodies_and_queries_omitted(self):
        raw = entry(request={"method": "GET", "url": "https://user:PASSWORD_SECRET@example.com:8443/path?QUERY_SECRET#FRAGMENT_SECRET",
                             "headers": [{"name": "Authorization", "value": "AUTH_SECRET"}], "cookies": "COOKIE_SECRET", "postData": "POST_SECRET"},
                    response={"status": 200, "headers": "HEADER_SECRET", "cookies": "RESPONSE_COOKIE_SECRET",
                              "redirectURL": "REDIRECT_SECRET", "content": {"mimeType": "text/plain", "text": "BODY_SECRET"}},
                    comment="COMMENT_SECRET", serverIPAddress="SERVER_IP_SECRET")
        text = await self.call("inspect_har", har([raw], pages=[{"title": "PAGE_SECRET", "id": "PAGE_ID_SECRET"}]))
        for secret in ("PASSWORD_SECRET", "QUERY_SECRET", "FRAGMENT_SECRET", "AUTH_SECRET", "COOKIE_SECRET", "POST_SECRET",
                       "HEADER_SECRET", "RESPONSE_COOKIE_SECRET", "REDIRECT_SECRET", "BODY_SECRET", "COMMENT_SECRET", "SERVER_IP_SECRET",
                       "PAGE_SECRET", "PAGE_ID_SECRET"):
            self.assertNotIn(secret, text)
        self.assertEqual(json.loads(text)["entries"][0]["target"],
                         {"supported": True, "scheme": "https", "host": "example.com", "port": 8443, "path": "/path"})

    async def test_har_unknown_timings_sizes_and_duration_not_zero(self):
        result = await self.har(har([entry(time=None, timings={"wait": -1}, startedDateTime=None,
                                          response={"status": 0, "bodySize": -1, "content": {}})]))
        self.assertIsNone(result["duration_ms"]["mean"])
        self.assertEqual(result["missing_duration_count"], 1)
        self.assertIsNone(result["entries"][0]["timings_ms"]["wait"])
        self.assertEqual(result["timing_stages_ms"]["wait"]["count"], 0)
        self.assertEqual(result["missing_start_time_count"], 1)
        self.assertIsNone(result["timestamp_range"]["first"])
        self.assertEqual(result["response_body_bytes"]["unknown_count"], 1)

    async def test_har_ssl_is_separate_without_double_counting_and_zero_is_measured(self):
        result = await self.har(har([entry(time=0)]))
        self.assertEqual(result["duration_ms"]["count"], 1)
        self.assertEqual(result["duration_ms"]["mean"], 0)
        self.assertEqual(result["timing_stages_ms"]["connect"]["mean"], 5)
        self.assertEqual(result["timing_stages_ms"]["ssl"]["mean"], 3)
        self.assertNotIn("page_load_time", result)

    async def test_har_timestamp_range_normalized_to_utc_and_percent_escapes_preserved(self):
        rows = [entry(startedDateTime="2026-10-03T14:00:00+02:00"),
                entry(request={"method": "GET", "url": "https://EXAMPLE.COM/a%2Fb"}, startedDateTime="2026-10-03T12:30:00Z")]
        result = await self.har(har(rows))
        self.assertEqual(result["timestamp_range"], {"first": "2026-10-03T12:00:00+00:00", "last": "2026-10-03T12:30:00+00:00"})
        self.assertEqual(result["hosts"], [{"host": "example.com", "count": 2}])
        self.assertEqual(result["entries"][1]["target"]["path"], "/a%2Fb")

    async def test_har_non_http_targets_not_returned_and_never_resolved(self):
        for url in ("data:text/plain,BODY_SECRET", "file:///PATH_SECRET", "relative_PATH_SECRET"):
            with self.subTest(url=url):
                result = await self.har(har([entry(request={"method": "GET", "url": url})]))
                self.assertEqual(result["unsupported_url_count"], 1)
                self.assertIsNone(result["entries"][0]["target"]["path"])
                self.assertNotIn("SECRET", json.dumps(result))
        self.assertEqual((await self.har(har([entry(request={"method": "GET", "url": "http://127.0.0.1/"})])))["hosts"][0]["host"], "127.0.0.1")

    async def test_har_limits_preserve_totals_sort_slowest_and_bound_paths(self):
        result = await self.har(har([entry(), entry(time=200)]), limit=1)
        self.assertEqual(result["entry_count"], 2)
        self.assertEqual(result["duration_ms"]["count"], 2)
        self.assertEqual(len(result["entries"]), 1)
        self.assertEqual(result["slowest_requests"][0]["index"], 1)
        self.assertTrue(result["truncated"])
        result = await self.har(har([entry(request={"method": "GET", "url": "https://example.com/" + 'p' * 1001})]))
        self.assertEqual(len(result["entries"][0]["target"]["path"]), 1000)
        self.assertTrue(result["truncated"])

    async def test_har_empty_report(self):
        result = await self.har(har())
        self.assertEqual(result["entry_count"], 0)
        self.assertIsNone(result["duration_ms"]["mean"])
        self.assertFalse(result["truncated"])

    async def test_har_rejects_bad_selected_types_ranges_and_urls_without_echo(self):
        rows = (entry(time=-1), entry(time=True), entry(time="RAW_SECRET"), entry(timings={"ssl": -0.5}),
                entry(timings={"ssl": -2}), entry(startedDateTime="RAW_SECRET"), entry(startedDateTime="2026-10-03T12:00:00"),
                entry(response={"status": 99}), entry(response={"status": 600}), entry(response={"status": True}),
                entry(response={"status": 200, "bodySize": -2}), entry(response={"status": 200, "content": {"size": -1}}),
                entry(request={"method": "GET BAD", "url": "https://example.com"}),
                entry(request={"method": "GET", "url": "https://RAW_SECRET@[bad/"}),
                entry(request={"method": "GET", "url": "https://RAW_SECRET@example.com:bad/"}),
                entry(request={"method": "GET", "url": "https://example.com/RAW_SECRET\n"}))
        for row in rows:
            with self.subTest(row=row):
                text = await self.call("inspect_har", har([row]))
                self.assertTrue(text.startswith("Error:"))
                self.assertNotIn("RAW_SECRET", text)

    async def test_har_resource_bounds_and_errors_beyond_returned_limit(self):
        reports = (har([entry()] * 1001), har(pages=[{}] * 201), har([entry(), entry(time=-1)]),
                   har([entry(request={"method": "GET", "url": "https://example.com/" + 'p' * 10000})]),
                   '{"log":{"version":"1.1","entries":[]}}', '{"log":{"version":"1.2","entries":null}}')
        for report in reports:
            with self.subTest(size=len(report)):
                self.assertTrue((await self.call("inspect_har", report, limit=1)).startswith("Error:"))

    async def test_k6_legacy_values_duration_thresholds_and_individual_checks(self):
        metrics = {"http_reqs": metric(), "http_req_duration": metric("trend", {"p(95)": 120, "p(99.9)": 200, "avg": 50},
                    contains="time", thresholds={"p(95)<100": {"ok": False}}),
                   "http_req_failed": metric("rate", {"rate": 0.1, "passes": 1, "fails": 9})}
        report = legacy(metrics, root_group={"name": "", "checks": [{"name": "status 200", "passes": 9, "fails": 1}], "groups": []})
        result = await self.k6(report)
        self.assertEqual(result["format"], "legacy_handle_summary")
        self.assertEqual(result["duration_seconds"], 5)
        self.assertEqual(result["metrics"][1]["values"]["p(99.9)"], 200)
        self.assertEqual(result["threshold_counts"], {"passed": 0, "failed": 1, "unknown": 0})
        self.assertFalse(result["all_reported_thresholds_passed"])
        self.assertEqual(result["attention_checks"][0]["failure_fraction"], 0.1)
        self.assertEqual(result["check_totals"]["reported_fails"], 1)

    async def test_k6_machine_v1_metrics_check_metrics_and_no_invented_threshold_success(self):
        report = machine([metric(values={"count": 100}, name="http_reqs")],
                         checks={"metrics": [metric("rate", {"matches": 9, "total": 10, "rate": 0.9}, name="checks_succeeded")],
                                 "results": [{"name": "status 200", "passes": 9, "fails": 1}]})
        result = await self.k6(report)
        self.assertEqual(result["format"], "machine_v1")
        self.assertEqual(result["schema_version"], "1.0.0")
        self.assertEqual(result["metadata"]["execution"], "local")
        self.assertEqual(result["metric_count"], 2)
        self.assertEqual(result["metrics"][1]["source"], "check_metrics")
        self.assertEqual(result["metrics"][1]["values"]["rate"], 0.9)
        self.assertIsNone(result["all_reported_thresholds_passed"])
        self.assertNotIn("rate", result["metrics"][0]["values"])

    async def test_k6_nested_group_checks_count_once_and_missing_check_values_stay_incomplete(self):
        group = {"name": "root", "checks": [{"name": "unknown", "passes": None, "fails": 2}],
                 "groups": [{"name": "inner", "checks": [{"name": "known", "passes": 3, "fails": 0}]}]}
        result = await self.k6(legacy(root_group=group))
        self.assertEqual(result["check_result_count"], 2)
        self.assertEqual(result["check_totals"], {"reported_passes": 3, "reported_fails": 2, "incomplete_count": 1})
        self.assertIsNone(result["checks"][0]["failure_fraction"])
        self.assertEqual(result["checks"][1]["group"], "inner")

    async def test_k6_absent_empty_and_unknown_threshold_metadata(self):
        for fields, counts, outcome in (({}, {"passed": 0, "failed": 0, "unknown": 0}, None),
                                       ({"thresholds": {}}, {"passed": 0, "failed": 0, "unknown": 0}, None),
                                       ({"thresholds": {"count>0": {}}}, {"passed": 0, "failed": 0, "unknown": 1}, None),
                                       ({"thresholds": {"count>0": {"ok": True}}}, {"passed": 1, "failed": 0, "unknown": 0}, True)):
            result = await self.k6(legacy({"m": metric(**fields)}))
            self.assertEqual(result["threshold_counts"], counts)
            self.assertIs(result["all_reported_thresholds_passed"], outcome)

    async def test_k6_omits_setup_data_options_paths_ids_and_does_not_evaluate_thresholds(self):
        report = legacy({"m": metric(thresholds={"__import__('os').system('never')": {"ok": False}})},
                        setup_data="SETUP_SECRET", options={"summaryTimeUnit": "s", "token": "OPTION_SECRET"},
                        root_group={"name": "root", "path": "PATH_SECRET", "id": "ID_SECRET", "checks": []})
        with patch("subprocess.run", side_effect=AssertionError("No threshold execution")):
            result = service.inspect_k6(report, 20)
        self.assertFalse(result["all_reported_thresholds_passed"])
        self.assertEqual(result["metrics"][0]["values"]["rate"], 2)
        for secret in ("SETUP_SECRET", "OPTION_SECRET", "PATH_SECRET", "ID_SECRET"):
            self.assertNotIn(secret, json.dumps(result))
        report = json.loads(machine())
        report["config"]["script"] = "SCRIPT_SECRET"
        self.assertNotIn("SCRIPT_SECRET", await self.call("inspect_k6_summary", json.dumps(report)))

    async def test_k6_limit_counts_all_metrics_and_retains_failed_thresholds(self):
        metrics = {"one": metric(thresholds={"count>0": {"ok": True}}),
                   "two": metric(thresholds={"count>20": {"ok": False}})}
        result = await self.k6(legacy(metrics), limit=1)
        self.assertEqual(result["metric_count"], 2)
        self.assertEqual(result["threshold_count"], 2)
        self.assertEqual(result["failed_thresholds"][0]["metric"], "two")
        self.assertEqual(len(result["metrics"]), 1)
        self.assertTrue(result["truncated"])

    async def test_k6_duplicate_metric_names_in_arrays_rejected_but_separate_collections_preserved(self):
        raw = metric(name="same")
        self.assertTrue((await self.call("inspect_k6_summary", machine([raw, raw]))).startswith("Error:"))
        result = await self.k6(machine([raw], checks={"metrics": [raw]}))
        self.assertEqual(result["metric_count"], 2)
        self.assertFalse(result["check_results_available"])

    async def test_k6_missing_duration_empty_metrics_and_signed_gauge(self):
        result = await self.k6(legacy({}, state={}))
        self.assertEqual(result["metric_count"], 0)
        self.assertIsNone(result["duration_seconds"])
        self.assertFalse(result["check_results_available"])
        result = await self.k6(legacy({"temperature": metric("gauge", {"value": -10, "min": -20, "max": 5})}))
        self.assertEqual(result["metrics"][0]["values"]["value"], -10)
        self.assertFalse(result["truncated"])
        self.assertFalse((await self.k6(legacy(root_group=None)))["check_results_available"])

    async def test_k6_rejects_unsupported_variants_and_selected_field_shapes(self):
        reports = ('{}', '{"metrics":{"http":{"http_reqs":{}}}}', '{"metrics":{"http_reqs":{"count":10}}}',
                   machine(version="2.0.0"), legacy(groups={}), legacy(scenarios={}), legacy(thresholds={}),
                   legacy({"x": metric("unsupported")}), legacy({"x": metric(values={"count": True})}),
                   legacy({"x": metric(values={"count": "RAW_SECRET"})}), legacy({"x": metric(values={"count": -1})}),
                   legacy({"x": metric("rate", {"rate": 1.1})}), legacy({"x": metric(thresholds={"count>0": {"ok": "true"}})}),
                   legacy({"x": metric(contains="wrong")}), legacy({"x": metric(values={"count": 1e16})}),
                   legacy(root_group={"checks": [{"name": "bad", "passes": True}]}),
                   machine([metric("rate", {"matches": 3, "total": 2, "rate": 0.5}, name="bad")]),
                   machine([metric("rate", {"matches": 1.5, "total": 2, "rate": 0.5}, name="bad")]))
        for report in reports:
            with self.subTest(report=report[:100]):
                text = await self.call("inspect_k6_summary", report)
                self.assertTrue(text.startswith("Error:"))
                self.assertNotIn("RAW_SECRET", text)

    async def test_k6_resource_limits_validate_all_not_only_returned_rows(self):
        reports = (legacy({f'm{i}': metric() for i in range(501)}),
                   legacy({"x": metric(values={f'stat{i}': 1 for i in range(51)})}),
                   legacy({"x": metric(thresholds={f'count>{i}': {"ok": True} for i in range(51)})}),
                   legacy({f'm{i}': metric(thresholds={f'count>{j}': {"ok": True} for j in range(50)}) for i in range(21)}),
                   legacy(root_group={"groups": [{}] * 200}),
                   legacy(root_group={"checks": [{"name": "check", "passes": 1, "fails": 0}] * 1001}),
                   legacy({"ok": metric(), "bad": metric("rate", {"rate": 2})}))
        for report in reports:
            with self.subTest(size=len(report)):
                self.assertTrue((await self.call("inspect_k6_summary", report, limit=1)).startswith("Error:"))

    async def test_performance_shared_json_input_output_limits_and_sanitized_errors(self):
        reports = ('[1]', '{RAW_SECRET', '{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}',
                   '{"x":' + '[' * 51 + '0' + ']' * 51 + '}', json.dumps({"x": [0] * 20000}))
        for name in ("inspect_har", "inspect_k6_summary"):
            for report in reports:
                with self.subTest(name=name, size=len(report)):
                    text = await self.call(name, report)
                    self.assertTrue(text.startswith("Error:"))
                    self.assertNotIn("RAW_SECRET", text)
            for report, limit in (("x" * 200001, 20), ("{}", 0), ("{}", 51)):
                self.assertTrue((await self.call(name, report, limit=limit)).startswith("Error:"))
        for function, name in (("inspect_har", "inspect_har"), ("inspect_k6", "inspect_k6_summary")):
            with patch.object(service, function, return_value={"oversized": "x" * 100001}):
                self.assertIn("summary exceeds", await self.call(name, ""))

    async def test_performance_parsers_use_no_files_network_or_commands(self):
        for function, report in ((service.inspect_har, har([entry()])), (service.inspect_k6, legacy())):
            with patch("builtins.open", side_effect=AssertionError("No files")), \
                 patch("socket.getaddrinfo", side_effect=AssertionError("No network")), \
                 patch("subprocess.run", side_effect=AssertionError("No commands")):
                function(report, 20)
            with self.assertRaises(ValueError):
                function(report, True)

    async def test_real_performance_output_budgets_can_be_narrowed(self):
        archive = har([entry(request={"method": "GET", "url": "https://example.com/" + 'p' * 950},
                             response={"status": 500})] * 40)
        metrics = {f'm{i}': metric("trend", {f'stat{j}' + 'x' * 65: 1 for j in range(50)}) for i in range(40)}
        for name, content in (("inspect_har", archive), ("inspect_k6_summary", legacy(metrics))):
            with self.subTest(name=name):
                self.assertLessEqual(len(content), 200000)
                self.assertIn("summary exceeds", await self.call(name, content, limit=50))
                self.assertTrue(json.loads(await self.call(name, content, limit=1))["truncated"])


if __name__ == "__main__":
    unittest.main()
