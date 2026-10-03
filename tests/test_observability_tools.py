import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.report_utils import service, tool


def log(request="GET /health HTTP/1.1", status="200", size="12", timestamp="10/Oct/2000:13:55:36 -0700", combined=True):
    line = f'192.0.2.8 - private-user [{timestamp}] "{request}" {status} {size}'
    return line + ' "https://example.com/REFERRER_SECRET" "AGENT_SECRET"' if combined else line


class ObservabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("observability-tests")
        tool.register(self.mcp)

    async def call(self, name, content, **arguments):
        result = await self.mcp.call_tool(name, {"content": content, **arguments})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def metrics(self, content, **arguments):
        return json.loads(await self.call("inspect_prometheus_metrics", content, **arguments))

    async def logs(self, content, **arguments):
        return json.loads(await self.call("analyze_access_logs", content, **arguments))

    async def test_metric_counter_names_normalized_and_timestamps_in_seconds(self):
        result = await self.metrics('# HELP requests_total Processed requests\n# TYPE requests_total counter\nrequests_total{code="200"} 3 1500\n')
        self.assertEqual(result["family_count"], 1)
        self.assertEqual(result["type_counts"], {"counter": 1})
        family = result["families"][0]
        self.assertEqual(family["name"], "requests")
        self.assertEqual(family["samples"][0]["name"], "requests_total")
        self.assertEqual(family["samples"][0]["value"], 3)
        self.assertEqual(family["samples"][0]["timestamp_seconds"], 1.5)
        self.assertEqual(family["help"], "Processed requests")

    async def test_metric_gauge_histogram_summary_and_untyped(self):
        content = '# TYPE queue gauge\nqueue 2\n# TYPE latency histogram\nlatency_bucket{le="1"} 4\n'
        content += 'latency_bucket{le="+Inf"} 5\nlatency_sum 2\nlatency_count 5\n'
        content += '# TYPE payload summary\npayload{quantile="0.5"} 10\npayload_sum 25\npayload_count 2\nloose 7\n'
        result = await self.metrics(content)
        self.assertEqual(result["type_counts"], {"gauge": 1, "histogram": 1, "summary": 1, "untyped": 1})
        self.assertEqual(result["sample_count"], 9)
        self.assertEqual(result["families"][1]["label_names"], ["le"])
        self.assertNotIn("rate", result)
        self.assertNotIn("p95", result)

    async def test_metric_label_escapes_and_quoted_names(self):
        result = await self.metrics('g{note="first\\nsecond",quote="a\\\"b",slash="a\\\\b"} 1\n'
                                    '{"temperature.celsius",room="north"} 20\n')
        labels = result["families"][0]["samples"][0]["labels"]
        self.assertEqual(labels, {"note": "first\nsecond", "quote": 'a"b', "slash": 'a\\b'})
        self.assertEqual(result["families"][1]["samples"][0]["name"], "temperature.celsius")

    async def test_metric_nonfinite_values_are_json_strings(self):
        result = await self.metrics('a NaN\nb +Inf\nc -Inf\n')
        self.assertEqual([family["samples"][0]["value"] for family in result["families"]], ["NaN", "+Inf", "-Inf"])
        self.assertEqual(result["nonfinite_value_count"], 3)
        json.dumps(result, allow_nan=False)

    async def test_metric_duplicate_series_and_repeated_family_blocks(self):
        content = '# TYPE g gauge\ng{a="1",b="2"} 1\ng{b="2",a="1"} 2\n'
        content += '# TYPE other gauge\nother 1\n# TYPE g gauge\ng{a="1",b="2"} 3\n'
        result = await self.metrics(content)
        self.assertEqual(result["sample_count"], 4)
        self.assertEqual(result["unique_series_count"], 2)
        self.assertEqual(result["duplicate_sample_count"], 2)
        self.assertEqual(result["family_count"], 3)
        self.assertEqual(result["unique_family_count"], 2)

    async def test_metric_limits_apply_to_families_and_samples_but_count_all(self):
        result = await self.metrics('# TYPE a gauge\na{x="1"} 1\na{x="2"} 2\n# TYPE b gauge\nb 3\n', limit=1)
        self.assertEqual(result["family_count"], 2)
        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(len(result["families"]), 1)
        self.assertEqual(len(result["families"][0]["samples"]), 1)
        self.assertTrue(result["families"][0]["samples_truncated"])
        self.assertTrue(result["truncated"])

    async def test_metric_help_truncated_but_selected_labels_not_silently_changed(self):
        result = await self.metrics('# HELP a ' + 'h' * 1001 + '\na 1\n')
        self.assertEqual(len(result["families"][0]["help"]), 1000)
        self.assertTrue(result["truncated"])
        self.assertTrue((await self.call("inspect_prometheus_metrics", 'a{x="' + 'v' * 2001 + '"} 1')).startswith("Error:"))

    async def test_metric_empty_input_and_comment_only(self):
        for content in ("", "# comment\n"):
            result = await self.metrics(content)
            self.assertEqual(result["family_count"], 0)
            self.assertEqual(result["sample_count"], 0)
            self.assertFalse(result["truncated"])

    async def test_metric_parse_errors_no_source_echo_or_openmetrics(self):
        for content in ('a{bad="RAW_SECRET" 1', 'a{a="1",a="2"} 1', 'a RAW_SECRET',
                        '# TYPE a info\na 1', 'a 1 Inf', '# EOF\n', '# UNIT a seconds\na 1'):
            with self.subTest(content=content):
                text = await self.call("inspect_prometheus_metrics", content)
                self.assertTrue(text.startswith("Error:"))
                self.assertNotIn("RAW_SECRET", text)

    async def test_metric_resource_limits(self):
        labels = ','.join(f'x{i}="v"' for i in range(21))
        contents = ('a{' + labels + '} 1', 'a 1\n' * 5001, ''.join(f'# TYPE g{i} gauge\ng{i} 1\n' for i in range(501)),
                    'a 1\n' + '# ignored\n' * 5000, '#' + 'x' * 10000,
                    'a ' + '9' * 400, 'a{bad="' + 'x' * 2001 + '"} 1')
        for content in contents:
            with self.subTest(size=len(content)):
                self.assertTrue((await self.call("inspect_prometheus_metrics", content, limit=1)).startswith("Error:"))

    async def test_access_statuses_byte_totals_errors_and_utc_time(self):
        content = '\n'.join((log(), log("POST /health HTTP/1.1", "404", "-"),
                             log("GET /fail HTTP/1.1", "503", "8", "10/Oct/2000:14:55:36 -0700"),
                             log("GET /unknown HTTP/1.1", "-", "-")))
        result = await self.logs(content)
        self.assertEqual(result["parsed_entries"], 4)
        self.assertEqual(result["status_counts"], {"200": 1, "404": 1, "503": 1})
        self.assertEqual(result["client_error_count"], 1)
        self.assertEqual(result["server_error_count"], 1)
        self.assertAlmostEqual(result["error_response_fraction"], 2 / 3)
        self.assertEqual(result["unknown_status_count"], 1)
        self.assertEqual(result["total_reported_bytes"], 20)
        self.assertEqual(result["missing_bytes_count"], 2)
        self.assertEqual(result["timestamp_range"], {"first": "2000-10-10T20:55:36+00:00", "last": "2000-10-10T21:55:36+00:00"})
        self.assertEqual(result["unique_path_count"], 4)

    async def test_access_common_format_and_error_fraction_with_no_status(self):
        result = await self.logs(log(status="-", combined=False), format="common")
        self.assertEqual(result["parsed_entries"], 1)
        self.assertIsNone(result["error_response_fraction"])
        wrong_format = await self.logs(log(combined=False))
        self.assertEqual(wrong_format["invalid_entries"], 1)

    async def test_access_omits_query_fragment_authority_and_private_identity(self):
        content = '\n'.join((log("GET /health?QUERY_SECRET#FRAGMENT_SECRET HTTP/1.1"),
                             log("GET https://user:PASSWORD_SECRET@example.com/health?QUERY_SECRET HTTP/1.1"),
                             log("GET /health HTTP/1.1")))
        text = await self.call("analyze_access_logs", content)
        for secret in ("192.0.2.8", "private-user", "REFERRER_SECRET", "AGENT_SECRET", "QUERY_SECRET", "FRAGMENT_SECRET", "PASSWORD_SECRET"):
            self.assertNotIn(secret, text)
        self.assertEqual(json.loads(text)["paths"], [{"method": "GET", "path": "/health", "count": 3}])

    async def test_access_does_not_decode_percent_escapes_or_combine_methods(self):
        result = await self.logs('\n'.join((log("GET /a%2Fb HTTP/1.1"), log("GET /a/b HTTP/1.1"), log("POST /a/b HTTP/1.1"))))
        self.assertEqual(result["unique_path_count"], 3)
        self.assertEqual({row["path"] for row in result["paths"]}, {"/a%2Fb", "/a/b"})
        self.assertEqual(result["methods"][0], {"method": "GET", "count": 2})

    async def test_access_special_and_malformed_targets_still_count_observations(self):
        requests = ('OPTIONS * HTTP/1.1', 'CONNECT example.com:443 HTTP/1.1', 'GET relative HTTP/1.1',
                    '-', 'not a valid request', 'GET http:///broken HTTP/1.1', 'GET http://[invalid HTTP/1.1')
        result = await self.logs('\n'.join(log(request) for request in requests))
        self.assertEqual(result["parsed_entries"], 7)
        self.assertEqual(result["status_counts"], {"200": 7})
        self.assertEqual(result["total_reported_bytes"], 84)
        self.assertEqual(result["unclassified_request_target_count"], 6)
        self.assertEqual(result["paths"], [{"method": "OPTIONS", "path": "*", "count": 1}])

    async def test_access_invalid_lines_blank_lines_and_no_error_snippets(self):
        contents = ("RAW_SECRET", log(timestamp="31/Feb/2000:13:55:36 -0700"), log(status="999"), log(size="1000000000001"))
        result = await self.logs('\n'.join((*contents, "", log())), limit=1)
        self.assertEqual(result["invalid_entries"], 4)
        self.assertEqual(result["parsed_entries"], 1)
        self.assertEqual(result["blank_lines"], 1)
        self.assertEqual(result["invalid_samples"][0]["line"], 1)
        self.assertTrue(result["truncated"])
        self.assertNotIn("RAW_SECRET", json.dumps(result))

    async def test_access_top_paths_counts_all_entries_and_bounds_text(self):
        content = '\n'.join((log("GET /one HTTP/1.1"), log("GET /two HTTP/1.1"), log("GET /one HTTP/1.1")))
        result = await self.logs(content, limit=1)
        self.assertEqual(result["parsed_entries"], 3)
        self.assertEqual(result["unique_path_count"], 2)
        self.assertEqual(result["paths"], [{"method": "GET", "path": "/one", "count": 2}])
        self.assertTrue(result["truncated"])
        result = await self.logs(log("GET /" + 'p' * 1001 + " HTTP/1.1"))
        self.assertEqual(len(result["paths"][0]["path"]), 1000)
        self.assertTrue(result["truncated"])

    async def test_access_empty_input(self):
        result = await self.logs("")
        self.assertEqual(result["line_count"], 0)
        self.assertEqual(result["parsed_entries"], 0)
        self.assertIsNone(result["error_response_fraction"])
        self.assertEqual(result["timestamp_range"], {"first": None, "last": None})
        self.assertFalse(result["truncated"])

    async def test_observability_resource_and_output_budgets(self):
        for name in ("inspect_prometheus_metrics", "analyze_access_logs"):
            for content, limit in (("x" * 200001, 20), ("\n" * 5001, 20), ("x" * 10001, 20), ("", 0), ("", 51)):
                with self.subTest(name=name, size=len(content), limit=limit):
                    self.assertTrue((await self.call(name, content, limit=limit)).startswith("Error:"))
        self.assertTrue((await self.call("analyze_access_logs", "", format="custom")).startswith("Error:"))
        for function, name in (("inspect_metrics", "inspect_prometheus_metrics"), ("analyze_access", "analyze_access_logs")):
            with patch.object(service, function, return_value={"oversized": "x" * 100001}):
                self.assertIn("summary exceeds", await self.call(name, ""))

    async def test_observability_parsers_do_not_scrape_read_files_or_run_commands(self):
        with patch("builtins.open", side_effect=AssertionError("No files")), \
             patch("socket.getaddrinfo", side_effect=AssertionError("No network")), \
             patch("subprocess.run", side_effect=AssertionError("No commands")):
            self.assertEqual(service.inspect_metrics("a 1", 20)["sample_count"], 1)
            self.assertEqual(service.analyze_access(log(), "combined", 20)["parsed_entries"], 1)
        with self.assertRaises(ValueError):
            service.inspect_metrics("a 1", True)
        with self.assertRaises(ValueError):
            service.analyze_access(log(), "combined", True)

    async def test_real_metric_summary_enforces_output_budget_and_can_be_narrowed(self):
        labels = ','.join(f'x{i}="' + 'v' * 90 + '"' for i in range(19))
        content = '# TYPE g gauge\n' + ''.join(f'g{{{labels},row="{i}"}} 1\n' for i in range(50))
        self.assertLessEqual(len(content), 200000)
        self.assertIn("summary exceeds", await self.call("inspect_prometheus_metrics", content, limit=50))
        result = await self.metrics(content, limit=1)
        self.assertEqual(result["sample_count"], 50)
        self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
