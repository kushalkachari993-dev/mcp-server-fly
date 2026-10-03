import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.coverage_utils import service as coverage
from app.tools.performance_utils import service as performance
from app.tools.report_utils import service as reports
from app.tools.report_comparison import service, tool


def lcov(lines="DA:1,1\n", file="app.py", test=None, extra=""):
    return (f"TN:{test}\n" if test is not None else "") + f"SF:{file}\n{lines}{extra}end_of_record\n"


def cobertura(classes):
    return '<coverage><packages><package name="demo"><classes>' + "".join(classes) + '</classes></package></packages></coverage>'


def cls(lines='<line number="1" hits="1"/>', name="App", file="app.py"):
    return f'<class name="{name}" filename="{file}"><lines>{lines}</lines></class>'


def junit(cases, name="suite"):
    return f'<testsuite name="{name}">' + "".join(cases) + '</testsuite>'


def case(name="test", outcome="passed", time="1", classname="App"):
    marker = {"passed": "", "failed": '<failure message="MESSAGE_SECRET">BODY_SECRET</failure>',
              "error": '<error/>', "skipped": '<skipped/>'}[outcome]
    duration = f' time="{time}"' if time is not None else ""
    return f'<testcase name="{name}" classname="{classname}"{duration}>{marker}</testcase>'


def entry(url="https://example.com/path?QUERY_SECRET", time=10, status=200, size=5, **fields):
    value = {"request": {"method": "GET", "url": url}, "response": {"status": status, "bodySize": size}, "time": time}
    value.update(fields)
    return value


def har(entries):
    return json.dumps({"log": {"version": "1.2", "entries": entries}})


def metric(values=None, kind="trend", contains="time", **fields):
    return {"type": kind, "contains": contains, "values": {"avg": 10, "p(95)": 20} if values is None else values, **fields}


def k6(metrics, **fields):
    return json.dumps({"metrics": metrics, **fields})


def machine(metrics, check_metrics=()):
    return json.dumps({"version": "1.0.0", "metadata": {}, "config": {},
                       "results": {"metrics": metrics, "checks": {"metrics": list(check_metrics)}}})


class ReportComparisonTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("report-comparisons")
        tool.register(self.mcp)

    async def call(self, name, before, after, **arguments):
        result = await self.mcp.call_tool(name, {"before": before, "after": after, **arguments})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def compare(self, name, before, after, **arguments):
        return json.loads(await self.call(name, before, after, **arguments))

    async def test_registers_exactly_four_tools(self):
        self.assertEqual({item.name for item in await self.mcp.list_tools()}, {
            "compare_coverage_reports", "compare_junit_reports", "compare_har_reports", "compare_k6_summaries"})

    async def test_lcov_line_transitions_and_percentage_points(self):
        result = await self.compare("compare_coverage_reports", lcov("DA:1,1\nDA:2,0\nDA:3,1\n"),
                                    lcov("DA:1,0\nDA:2,2\nDA:4,0\n"))
        row = result["comparisons"][0]
        self.assertEqual(row["newly_uncovered_lines"], [1])
        self.assertEqual(row["newly_covered_lines"], [2])
        self.assertEqual(row["added_lines"], [4])
        self.assertEqual(row["removed_lines"], [3])
        self.assertEqual(row["uncovered_added_lines"], [4])
        self.assertAlmostEqual(row["coverage"]["lines"]["percentage_point_delta"], -100 / 3)
        self.assertEqual(result["line_change_counts"], row["line_change_counts"])
        self.assertEqual(result["observed_total_changes"]["lines"]["hit_delta"], -1)

    async def test_lcov_added_removed_files_and_exact_paths(self):
        result = await self.compare("compare_coverage_reports", lcov(file="./app.py"), lcov(file="app.py"))
        self.assertEqual(result["matching"]["matched_count"], 0)
        self.assertEqual(result["added_files"], ["app.py"])
        self.assertEqual(result["removed_files"], ["./app.py"])
        self.assertEqual(result["matching"]["added_count"], 1)
        self.assertEqual(result["line_change_counts"]["newly_uncovered_lines"], 0)

    async def test_lcov_test_names_are_separate_identities(self):
        result = await self.compare("compare_coverage_reports", lcov(test="unit") + lcov(test="integration"),
                                    lcov("DA:1,0\n", test="integration"))
        self.assertEqual(result["matching"]["matched_count"], 1)
        self.assertEqual(result["comparisons"][0]["identity"]["test_name"], "integration")
        self.assertEqual(result["matching"]["removed"][0]["test_name"], "unit")
        self.assertEqual(result["removed_file_count"], 0)

    async def test_lcov_duplicates_are_ambiguous_even_if_only_on_one_side(self):
        for before, after in ((lcov() * 2, lcov("DA:1,0\n")), (lcov() * 2, "")):
            result = await self.compare("compare_coverage_reports", before, after)
            self.assertEqual(result["matching"]["ambiguous_count"], 1)
            self.assertEqual(result["matching"]["matched_count"], 0)
            self.assertEqual(result["matching"]["removed_count"], 0)
            self.assertEqual(result["matching"]["ambiguous"][0]["before_count"], 2)

    async def test_lcov_full_sections_and_line_maps_not_inspector_samples(self):
        before = lcov("".join(f"DA:{number},1\n" for number in range(1, 101)))
        after = lcov("".join(f"DA:{number},0\n" for number in range(1, 101)))
        result = await self.compare("compare_coverage_reports", before, after, limit=1)
        self.assertEqual(result["line_change_counts"]["newly_uncovered_lines"], 100)
        self.assertEqual(result["comparisons"][0]["newly_uncovered_lines"], [1])
        before = "".join(lcov(file=f"{number}.py") for number in range(60))
        result = await self.compare("compare_coverage_reports", before, before, limit=1)
        self.assertEqual(result["matching"]["matched_count"], 60)
        self.assertEqual(len(result["comparisons"]), 1)
        self.assertTrue(result["truncated"])

    async def test_lcov_unknown_functions_and_function_format_changes(self):
        result = await self.compare("compare_coverage_reports", lcov(extra="FN:1,f\n"), lcov(extra="FN:1,f\nFNDA:1,f\n"))
        self.assertIsNone(result["comparisons"][0]["coverage"]["functions"]["hit_delta"])
        result = await self.compare("compare_coverage_reports", lcov(extra="FN:1,f\nFNDA:1,f\n"),
                                    lcov(extra="FNL:0,1\nFNA:0,0,f\n"))
        self.assertIsNone(result["comparisons"][0]["coverage"]["functions"]["percentage_point_delta"])
        self.assertFalse(result["observed_total_changes"]["functions"]["comparable"])

    async def test_lcov_declared_values_do_not_replace_observed_coverage(self):
        result = await self.compare("compare_coverage_reports", lcov(extra="LF:99\nLH:99\n"), lcov("DA:1,0\n", extra="LF:99\nLH:99\n"))
        self.assertEqual(result["before"]["mismatched_record_count"], 1)
        self.assertEqual(result["comparisons"][0]["coverage"]["lines"]["percentage_point_delta"], -100)

    async def test_lcov_mixed_format_aggregate_functions_not_compared(self):
        before = lcov(file="old.py", extra="FN:1,f\nFNDA:1,f\n") + lcov(file="new.py", extra="FNL:0,1\nFNA:0,0,f\n")
        result = await self.compare("compare_coverage_reports", before, before)
        self.assertFalse(result["observed_total_changes"]["functions"]["comparable"])
        self.assertIsNone(result["observed_total_changes"]["functions"]["hit_delta"])
        self.assertEqual(result["comparisons"][0]["coverage"]["functions"]["hit_delta"], 0)
        self.assertEqual(result["comparisons"][1]["coverage"]["functions"]["hit_delta"], 0)

    async def test_cobertura_class_identity_and_observed_counts(self):
        result = await self.compare("compare_coverage_reports", cobertura([cls(), cls(name="Other")]),
                                    cobertura([cls('<line number="1" hits="0"/>'), cls(name="New")]), format="cobertura")
        self.assertEqual(result["matching"]["matched_count"], 1)
        self.assertEqual(result["matching"]["added"][0]["class"], "New")
        self.assertEqual(result["matching"]["removed"][0]["class"], "Other")
        self.assertEqual(result["added_file_count"], 0)
        self.assertEqual(result["comparisons"][0]["newly_uncovered_lines"], [1])
        self.assertNotIn("functions", result["comparisons"][0]["coverage"])

    async def test_cobertura_unknown_branches_and_duplicate_classes(self):
        before = cobertura([cls('<line number="1" hits="1" branch="true"/>')])
        after = cobertura([cls('<line number="1" hits="1" branch="true" condition-coverage="50% (1/2)"/>')])
        result = await self.compare("compare_coverage_reports", before, after, format="cobertura")
        self.assertIsNone(result["comparisons"][0]["coverage"]["branches"]["hit_delta"])
        result = await self.compare("compare_coverage_reports", cobertura([cls(), cls()]), after, format="cobertura")
        self.assertEqual(result["matching"]["ambiguous_count"], 1)

    async def test_cobertura_missing_and_long_identity_do_not_collide(self):
        before = cobertura([cls().replace('name="App"', '')])
        result = await self.compare("compare_coverage_reports", before, before, format="cobertura")
        self.assertEqual(result["matching"]["unmatchable_before_count"], 1)
        long = "x" * 1000
        before, after = cobertura([cls(name=long + "A")]), cobertura([cls(name=long + "B")])
        result = await self.compare("compare_coverage_reports", before, after, format="cobertura")
        self.assertEqual(result["matching"]["matched_count"], 0)
        self.assertEqual(result["matching"]["unmatchable_after_count"], 1)

    async def test_junit_outcome_transitions_added_removed_and_duration(self):
        before = junit([case("bad"), case("fixed", "error"), case("skip"), case("removed")])
        after = junit([case("bad", "failed", "3"), case("fixed"), case("skip", "skipped"), case("added", "failed")])
        result = await self.compare("compare_junit_reports", before, after)
        self.assertEqual(result["newly_failing_count"], 1)
        self.assertEqual(result["newly_failing_tests"][0]["identity"]["name"], "bad")
        self.assertEqual(result["recovered_count"], 1)
        self.assertEqual(result["outcome_changed_count"], 3)
        self.assertEqual(result["matching"]["added"][0]["name"], "added")
        delta = result["largest_duration_increases"][0]["duration_seconds"]
        self.assertEqual(delta["delta"], 2)
        self.assertEqual(delta["relative_percent"], 200)

    async def test_junit_nested_suite_ancestry_not_position(self):
        child = junit([case()], name="child")
        before = '<testsuites>' + junit([child], name="one") + junit([child], name="two") + '</testsuites>'
        after = '<testsuites>' + junit([child], name="two") + junit([child], name="one") + '</testsuites>'
        result = await self.compare("compare_junit_reports", before, after)
        self.assertEqual(result["matching"]["matched_count"], 2)
        self.assertEqual(result["comparisons"][0]["identity"]["suite_path"], ["one", "child"])

    async def test_junit_duplicate_tests_missing_identity_and_oversized_names(self):
        result = await self.compare("compare_junit_reports", junit([case(), case()]), junit([case("test", "failed")]))
        self.assertEqual(result["matching"]["ambiguous_count"], 1)
        self.assertEqual(result["newly_failing_count"], 0)
        for content in (junit([case(name="x" * 1001)]), '<testsuite><testcase name="x"/></testsuite>',
                        junit(['<testcase classname="App"/>'])):
            result = await self.compare("compare_junit_reports", content, content)
            self.assertEqual(result["matching"]["unmatchable_before_count"], 1)
            self.assertEqual(result["matching"]["matched_count"], 0)

    async def test_junit_unknown_and_zero_duration_remain_distinct(self):
        result = await self.compare("compare_junit_reports", junit([case("missing", time=None), case("zero", time="0")]),
                                    junit([case("missing"), case("zero", time="2")]))
        missing, zero = [row["duration_seconds"] for row in result["comparisons"]]
        self.assertIsNone(missing["delta"])
        self.assertEqual(missing["reason"], "missing_measurement")
        self.assertEqual(zero["delta"], 2)
        self.assertIsNone(zero["relative_percent"])

    async def test_junit_mixed_markers_are_uncertain_and_diagnostics_omitted(self):
        mixed = case(outcome="failed").replace('</testcase>', '<skipped/>TAIL_SECRET</testcase>')
        text = await self.call("compare_junit_reports", junit([case()]), junit([mixed]))
        result = json.loads(text)
        self.assertEqual(result["uncertain_outcome_count"], 1)
        self.assertEqual(result["newly_failing_count"], 0)
        self.assertFalse(result["comparisons"][0]["outcome_comparable"])
        for secret in ("MESSAGE_SECRET", "BODY_SECRET", "TAIL_SECRET"):
            self.assertNotIn(secret, text)

    async def test_junit_all_passed_cases_and_counts_beyond_output_limit(self):
        before = junit([case(f"test{number}") for number in range(100)])
        after = junit([case(f"test{number}", "failed") for number in range(100)])
        result = await self.compare("compare_junit_reports", before, after, limit=1)
        self.assertEqual(result["matching"]["matched_count"], 100)
        self.assertEqual(result["newly_failing_count"], 100)
        self.assertEqual(len(result["newly_failing_tests"]), 1)
        self.assertTrue(result["truncated"])

    async def test_junit_namespace_and_extreme_finite_duration(self):
        before = junit([case(time="1e-300")]).replace('<testsuite ', '<testsuite xmlns="urn:junit" ')
        result = await self.compare("compare_junit_reports", before, junit([case(time="1e300")]))
        delta = result["comparisons"][0]["duration_seconds"]
        self.assertTrue(delta["comparable"])
        self.assertEqual(delta["delta"], 1e300)
        self.assertIsNone(delta["relative_percent"])

    async def test_har_grouping_statuses_sizes_and_observed_duration(self):
        before = har([entry(time=10), entry(time=30), entry(url="https://example.com/old")])
        after = har([entry(time=40, status=500, size=10), entry(url="https://example.com/new")])
        result = await self.compare("compare_har_reports", before, after)
        row = result["comparisons"][0]
        self.assertEqual(row["entry_count"]["delta"], -1)
        self.assertEqual(row["duration_ms"]["mean"]["delta"], 20)
        self.assertEqual(row["duration_ms"]["median"]["before"], 20)
        self.assertEqual(row["status_counts"]["200"]["delta"], -2)
        self.assertEqual(row["status_counts"]["500"]["delta"], 1)
        self.assertEqual(row["body_bytes"]["total_delta"], 0)
        self.assertIsNone(row["content_bytes"]["total_delta"])
        self.assertEqual(result["matching"]["added_count"], 1)
        self.assertEqual(result["matching"]["removed_count"], 1)

    async def test_har_queries_merge_and_effective_default_ports_normalize(self):
        result = await self.compare("compare_har_reports", har([entry(url="https://EXAMPLE.com/path?a=1")]),
                                    har([entry(url="https://example.com:443/path?a=2"), entry(url="https://example.com/path?a=3")]))
        self.assertEqual(result["matching"]["matched_count"], 1)
        self.assertEqual(result["comparisons"][0]["entry_count"]["after"], 2)
        self.assertEqual(result["comparisons"][0]["identity"]["port"], 443)

    async def test_har_credentials_headers_cookies_and_bodies_omitted(self):
        raw = entry(url="https://user:PASSWORD_SECRET@example.com/path?QUERY_SECRET#FRAGMENT_SECRET",
                    request={"method": "GET", "url": "https://user:PASSWORD_SECRET@example.com/path?QUERY_SECRET#FRAGMENT_SECRET",
                             "headers": "AUTH_SECRET", "cookies": "COOKIE_SECRET", "postData": "POST_SECRET"},
                    response={"status": 200, "headers": "HEADER_SECRET", "content": {"text": "BODY_SECRET"}, "redirectURL": "REDIRECT_SECRET"})
        text = await self.call("compare_har_reports", har([raw]), har([raw]))
        for secret in ("PASSWORD_SECRET", "QUERY_SECRET", "FRAGMENT_SECRET", "AUTH_SECRET", "COOKIE_SECRET", "POST_SECRET",
                       "HEADER_SECRET", "BODY_SECRET", "REDIRECT_SECRET"):
            self.assertNotIn(secret, text)
        self.assertEqual(json.loads(text)["matching"]["matched_count"], 1)

    async def test_har_full_paths_match_before_display_truncation(self):
        prefix = "https://example.com/" + "x" * 1000
        result = await self.compare("compare_har_reports", har([entry(url=prefix + "a")]), har([entry(url=prefix + "b")]))
        self.assertEqual(result["matching"]["matched_count"], 0)
        self.assertEqual(result["matching"]["added_count"], 1)
        self.assertEqual(result["matching"]["removed_count"], 1)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["matching"]["added"][0]["path"]), 1000)

    async def test_har_method_scheme_port_and_escapes_are_distinct(self):
        base = entry()
        for other in (entry(url="http://example.com/path"), entry(url="https://example.com:8443/path"),
                      entry(url="https://example.com/%70ath"), entry(request={"method": "POST", "url": "https://example.com/path"})):
            result = await self.compare("compare_har_reports", har([base]), har([other]))
            self.assertEqual(result["matching"]["matched_count"], 0)

    async def test_har_unsupported_targets_and_missing_values(self):
        before = har([entry(url="data:PRIVATE_PAYLOAD"), entry(time=None, size=-1, status=0)])
        after = har([entry(url="file:///PRIVATE_PATH"), entry(time=0, size=0)])
        text = await self.call("compare_har_reports", before, after)
        result = json.loads(text)
        self.assertNotIn("PRIVATE_PAYLOAD", text)
        self.assertNotIn("PRIVATE_PATH", text)
        self.assertEqual(result["before"]["unsupported_url_count"], 1)
        self.assertIsNone(result["comparisons"][0]["duration_ms"]["mean"]["delta"])
        self.assertIsNone(result["comparisons"][0]["body_bytes"]["total_delta"])
        self.assertEqual(result["comparisons"][0]["status_counts"]["0"]["delta"], -1)

    async def test_har_all_entries_not_inspector_samples(self):
        before = har([entry(url=f"https://example.com/{number}") for number in range(60)])
        result = await self.compare("compare_har_reports", before, before, limit=1)
        self.assertEqual(result["matching"]["matched_count"], 60)
        self.assertEqual(len(result["comparisons"]), 1)
        self.assertTrue(result["truncated"])

    async def test_k6_value_deltas_percentiles_thresholds_and_added_removed(self):
        before = k6({"latency": metric(thresholds={"p(95)<30": {"ok": True}, "avg<15": {"ok": False}}), "old": metric()})
        after = k6({"latency": metric({"avg": 12, "p(95)": 40}, thresholds={"p(95)<30": {"ok": False}, "avg<15": {"ok": True}}), "new": metric()})
        result = await self.compare("compare_k6_summaries", before, after)
        row = result["metric_comparisons"][0]
        self.assertEqual(row["values"][1]["name"], "p(95)")
        self.assertEqual(row["values"][1]["delta"], 20)
        self.assertEqual(row["values"][1]["relative_percent"], 100)
        self.assertEqual(result["newly_failing_threshold_count"], 1)
        self.assertEqual(result["recovered_threshold_count"], 1)
        self.assertEqual(result["matching"]["added"][0]["name"], "new")
        self.assertEqual(result["matching"]["removed"][0]["name"], "old")

    async def test_k6_missing_values_zero_and_negative_baselines(self):
        result = await self.compare("compare_k6_summaries", k6({"g": metric({"value": -5, "zero": 0, "old": 1}, kind="gauge", contains="default")}),
                                    k6({"g": metric({"value": -3, "zero": 2, "new": 1}, kind="gauge", contains="default")}))
        values = {row["name"]: row for row in result["metric_comparisons"][0]["values"]}
        self.assertEqual(values["value"]["relative_percent"], 40)
        self.assertEqual(values["zero"]["delta"], 2)
        self.assertIsNone(values["zero"]["relative_percent"])
        self.assertIsNone(values["old"]["delta"])
        self.assertIsNone(values["new"]["delta"])
        self.assertEqual(result["unknown_value_comparison_count"], 2)

    async def test_k6_dimension_and_type_changes_are_unknown(self):
        for candidate in (metric(contains="data"), metric(contains=None), metric(kind="gauge")):
            result = await self.compare("compare_k6_summaries", k6({"m": metric()}), k6({"m": candidate}))
            row = result["metric_comparisons"][0]
            self.assertFalse(row["dimensions_comparable"])
            self.assertIsNone(row["values"][0]["delta"])
            self.assertEqual(row["values"][0]["reason"], "incompatible_or_unknown_dimension")

    async def test_k6_cross_format_is_not_unit_or_field_translation(self):
        result = await self.compare("compare_k6_summaries", k6({"m": metric()}), machine([{"name": "m", **metric()}]))
        self.assertFalse(result["same_format"])
        self.assertEqual(result["matching"]["matched_count"], 1)
        self.assertIsNone(result["metric_comparisons"][0]["values"][0]["delta"])

    async def test_k6_machine_check_metrics_are_separate_sources(self):
        before = machine([{"name": "same", **metric()}], [{"name": "same", **metric()}])
        after = machine([{"name": "same", **metric({"avg": 20})}], [{"name": "same", **metric({"avg": 5})}])
        result = await self.compare("compare_k6_summaries", before, after)
        self.assertEqual(result["matching"]["matched_count"], 2)
        self.assertEqual([row["identity"]["source"] for row in result["metric_comparisons"]], ["metrics", "check_metrics"])
        self.assertEqual(result["metric_comparisons"][0]["values"][0]["delta"], 10)
        self.assertEqual(result["metric_comparisons"][1]["values"][0]["delta"], -5)

    async def test_k6_unknown_added_removed_changed_thresholds_not_passed(self):
        before = k6({"m": metric(thresholds={"known": {"ok": True}, "removed": {"ok": False}})})
        after = k6({"m": metric(thresholds={"known": {}, "added": {"ok": False}})})
        result = await self.compare("compare_k6_summaries", before, after)
        self.assertFalse(result["threshold_comparisons"][0]["comparable"])
        self.assertEqual(result["newly_failing_threshold_count"], 0)
        self.assertEqual(result["recovered_threshold_count"], 0)
        self.assertEqual(result["threshold_matching"]["added"][0]["expression"], "added")
        self.assertEqual(result["threshold_matching"]["removed"][0]["expression"], "removed")
        result = await self.compare("compare_k6_summaries", k6({"m": metric()}), k6({"m": metric(thresholds={})}))
        self.assertIsNone(result["before"]["all_reported_thresholds_passed"])
        self.assertEqual(result["threshold_matching"]["matched_count"], 0)

    async def test_k6_incompatible_threshold_dimension_not_new_failure(self):
        before = k6({"m": metric(thresholds={"expr": {"ok": True}})})
        after = k6({"m": metric(contains="data", thresholds={"expr": {"ok": False}})})
        result = await self.compare("compare_k6_summaries", before, after)
        self.assertEqual(result["newly_failing_threshold_count"], 0)
        self.assertFalse(result["threshold_comparisons"][0]["comparable"])

    async def test_k6_all_metrics_thresholds_and_fields_before_limiting(self):
        before = k6({f"m{number}": metric(thresholds={"expr": {"ok": True}}) for number in range(60)})
        after = k6({f"m{number}": metric(thresholds={"expr": {"ok": False}}) for number in range(60)})
        result = await self.compare("compare_k6_summaries", before, after, limit=1)
        self.assertEqual(result["matching"]["matched_count"], 60)
        self.assertEqual(result["value_comparison_count"], 120)
        self.assertEqual(result["newly_failing_threshold_count"], 60)
        self.assertEqual(len(result["metric_comparisons"][0]["values"]), 1)
        self.assertEqual(len(result["newly_failing_thresholds"]), 1)
        self.assertTrue(result["truncated"])

    async def test_k6_does_not_evaluate_expressions_or_return_setup_data(self):
        content = k6({"m": metric(thresholds={"__import__('os').system('COMMAND_SECRET')": {"ok": None}})}, setup_data="SETUP_SECRET", options={"key": "OPTION_SECRET"})
        with patch("builtins.eval", side_effect=AssertionError("eval")), patch("os.system", side_effect=AssertionError("command")):
            result = await self.call("compare_k6_summaries", content, content)
        self.assertNotIn("SETUP_SECRET", result)
        self.assertNotIn("OPTION_SECRET", result)
        self.assertEqual(json.loads(result)["newly_failing_threshold_count"], 0)

    async def test_empty_reports_are_valid_without_invented_percentages(self):
        for name, content, arguments in (("compare_coverage_reports", "", {}),
                                          ("compare_coverage_reports", '<coverage/>', {"format": "cobertura"}),
                                          ("compare_junit_reports", '<testsuites/>', {}),
                                          ("compare_har_reports", har([]), {}),
                                          ("compare_k6_summaries", k6({}), {})):
            result = await self.compare(name, content, content, **arguments)
            self.assertEqual(result["matching"]["matched_count"], 0)
            self.assertFalse(result["truncated"])

    async def test_invalid_input_after_first_output_row_still_rejected(self):
        inputs = (("compare_coverage_reports", lcov(), lcov() + 'SF:b.py\nDA:bad,1\nend_of_record\n', {}),
                  ("compare_junit_reports", junit([case()]), junit([case(), case("bad", time="NaN")]), {}),
                  ("compare_har_reports", har([entry()]), har([entry(), entry(status=99)]), {}),
                  ("compare_k6_summaries", k6({"m": metric()}), k6({"m": metric(), "bad": metric({"avg": float("nan")})}), {}))
        for name, before, after, arguments in inputs:
            self.assertTrue((await self.call(name, before, after, limit=1, **arguments)).startswith("Error:"))

    async def test_malformed_and_forbidden_documents_have_sanitized_errors(self):
        values = (("compare_coverage_reports", 'SF:app.py\nPRIVATE_SOURCE', {}),
                  ("compare_coverage_reports", '<!DOCTYPE coverage [<!ENTITY x SYSTEM "file:///PRIVATE_SOURCE">]><coverage>&x;</coverage>', {"format": "cobertura"}),
                  ("compare_junit_reports", '<!DOCTYPE testsuite SYSTEM "PRIVATE_SOURCE"><testsuite/>', {}),
                  ("compare_har_reports", '{"PRIVATE_SOURCE":', {}),
                  ("compare_k6_summaries", '{"metrics": {}, "metrics": "PRIVATE_SOURCE"}', {}))
        for name, content, arguments in values:
            result = await self.call(name, content, content, **arguments)
            self.assertTrue(result.startswith("Error:"))
            self.assertNotIn("PRIVATE_SOURCE", result)

    async def test_unsupported_formats_and_k6_shapes_rejected(self):
        for format in ("LCOV", "auto", "junit"):
            self.assertTrue((await self.call("compare_coverage_reports", lcov(), lcov(), format=format)).startswith("Error:"))
        for content in ('{"version":"2.0.0"}', '{"metrics":{"old":{"avg":1}}}', '{"metrics":{},"groups":{}}'):
            self.assertTrue((await self.call("compare_k6_summaries", content, content)).startswith("Error:"))

    async def test_input_and_limit_bounds_on_both_sides(self):
        calls = ((service.compare_coverage, (lcov(), lcov(), "lcov")),
                 (service.compare_junit, (junit([]), junit([]))),
                 (service.compare_har, (har([]), har([]))), (service.compare_k6, (k6({}), k6({}))))
        for function, arguments in calls:
            for limit in (True, 0, 51, 1.5, "1"):
                with self.assertRaises(ValueError):
                    function(*arguments, limit)
            for position in (0, 1):
                for value in (None, {}, "x" * 200001):
                    oversized = list(arguments)
                    oversized[position] = value
                    with self.assertRaises(ValueError):
                        function(*oversized, 1)

    async def test_no_file_network_dns_or_subprocess_access(self):
        samples = ((service.compare_coverage, (lcov(file="C:/PRIVATE_SOURCE"),) * 2 + ("lcov", 1)),
                   (service.compare_junit, (junit([case()]),) * 2 + (1,)),
                   (service.compare_har, (har([entry(url="https://127.0.0.1/path")]),) * 2 + (1,)),
                   (service.compare_k6, (k6({"m": metric()}),) * 2 + (1,)))
        with patch("builtins.open", side_effect=AssertionError("file")), patch("socket.getaddrinfo", side_effect=AssertionError("DNS")), \
                patch("requests.get", side_effect=AssertionError("network")), patch("subprocess.run", side_effect=AssertionError("process")):
            for function, arguments in samples:
                self.assertEqual(function(*arguments)["matching"]["matched_count"], 1)

    async def test_inspector_collectors_preserve_default_public_summaries(self):
        for function, content, records in ((coverage.inspect_lcov, lcov(), []),
                                            (coverage.inspect_cobertura, cobertura([cls()]), []),
                                            (reports.inspect_junit, junit([case()]), []),
                                            (performance.inspect_har, har([entry()]), []),
                                            (performance.inspect_k6, k6({"m": metric()}), {})):
            self.assertEqual(function(content, 1), function(content, 1, _records=records))
            self.assertTrue(records)

    async def test_real_output_caps_and_smaller_limit_recovery(self):
        long = "x" * 700
        samples = (("compare_coverage_reports", "".join(lcov(file=f"{long}{number}.py") for number in range(60))),
                   ("compare_junit_reports", junit([case(name=f"{long}{number}", classname=long) for number in range(60)], name=long)),
                   ("compare_har_reports", har([entry(url=f"https://example.com/{long}{number}") for number in range(70)])),
                   ("compare_k6_summaries", k6({f"{long}{number}": metric({f"field{index}": index for index in range(25)}) for number in range(70)})))
        for name, content in samples:
            result = await self.call(name, content, content, limit=50)
            self.assertTrue(result.startswith("Error: Report summary exceeds 100000"), name)
            small = await self.compare(name, content, content, limit=1)
            self.assertTrue(small["truncated"])


if __name__ == "__main__":
    unittest.main()
