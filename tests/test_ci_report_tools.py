import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.report_utils import service, tool


def sarif(results=(), **fields):
    run = {"tool": {"driver": {"name": "demo"}}, "results": list(results) if isinstance(results, tuple) else results}
    run.update(fields)
    return json.dumps({"version": "2.1.0", "runs": [run]})


class CIReportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("ci-report-tests")
        tool.register(self.mcp)

    async def call(self, name, content, **arguments):
        result = await self.mcp.call_tool(name, {"content": content, **arguments})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def junit(self, content, **arguments):
        return json.loads(await self.call("inspect_junit_report", content, **arguments))

    async def sarif(self, content, **arguments):
        return json.loads(await self.call("inspect_sarif_report", content, **arguments))

    async def test_junit_observed_counts_do_not_sum_aggregate_declarations(self):
        report = '<testsuites tests="99"><testsuite name="outer" tests="3" time="20"><testcase name="ok" time="1"/>'
        report += '<testsuite name="inner" tests="2"><testcase name="failed" time="2"><failure message="assertion"/>'
        report += '</testcase><testcase name="skip"><skipped/></testcase></testsuite></testsuite></testsuites>'
        result = await self.junit(report)
        self.assertEqual(result["test_count"], 3)
        self.assertEqual(result["outcomes"], {"passed": 1, "failed": 1, "error": 0, "skipped": 1})
        self.assertEqual(result["suites"][0]["declared_counts"]["tests"], 3)
        self.assertEqual(result["suites"][0]["declared_time_seconds"], 20)
        self.assertEqual([item["observed_direct_test_count"] for item in result["suites"]], [1, 2])
        self.assertEqual(result["suites"][1]["parent_index"], 0)
        self.assertEqual(result["total_testcase_time_seconds"], 3)
        self.assertEqual(result["missing_time_count"], 1)
        self.assertEqual([item["name"] for item in result["slowest_tests"]], ["failed", "ok"])

    async def test_junit_namespaces_and_mixed_markers(self):
        result = await self.junit('<testsuite xmlns="urn:junit" xmlns:x="urn:other"><testcase name="mixed">'
                                  '<failure/><error/><skipped/><failure/></testcase><x:testcase/></testsuite>')
        self.assertEqual(result["test_count"], 1)
        self.assertEqual(result["mixed_outcome_count"], 1)
        self.assertEqual(result["attention_tests"][0]["outcome"], "error")
        self.assertEqual(result["attention_tests"][0]["markers"], {"failure": 2, "error": 1, "skipped": 1})

    async def test_junit_sensitive_bodies_properties_and_file_paths_omitted(self):
        report = '<testsuite><properties><property name="token" value="PROPERTY_SECRET"/></properties>'
        report += '<testcase name="broken" file="FILE_SECRET"><failure message="assert failed" type="AssertionError">'
        report += 'BODY_SECRET</failure><system-out>OUTPUT_SECRET</system-out><system-err>STDERR_SECRET</system-err>'
        report += '</testcase></testsuite>'
        text = await self.call("inspect_junit_report", report)
        for secret in ("PROPERTY_SECRET", "FILE_SECRET", "BODY_SECRET", "OUTPUT_SECRET", "STDERR_SECRET"):
            self.assertNotIn(secret, text)
        self.assertEqual(json.loads(text)["attention_tests"][0]["diagnostics"][0]["message"], "assert failed")

    async def test_junit_limits_preserve_totals_and_bound_diagnostics(self):
        report = '<testsuite><testcase name="one" time="1">' + '<failure/>' * 6 + '</testcase>'
        report += '<testcase name="two" time="2"><error/></testcase></testsuite>'
        result = await self.junit(report, limit=1)
        self.assertEqual(result["test_count"], 2)
        self.assertEqual(result["outcomes"]["error"], 1)
        self.assertEqual(len(result["attention_tests"]), 1)
        self.assertEqual(len(result["attention_tests"][0]["diagnostics"]), 5)
        self.assertEqual(result["slowest_tests"][0]["name"], "two")
        self.assertTrue(result["truncated"])

    async def test_junit_text_is_bounded_and_truncation_is_explicit(self):
        result = await self.junit('<testsuite name="' + 's' * 1001 + '"><testcase><failure message="' + 'm' * 1001 + '"/></testcase></testsuite>')
        self.assertEqual(len(result["suites"][0]["name"]), 1000)
        self.assertEqual(len(result["attention_tests"][0]["diagnostics"][0]["message"]), 1000)
        self.assertTrue(result["truncated"])

    async def test_junit_empty_valid_roots_and_missing_times(self):
        for report, suites in (("<testsuites/>", 0), ("<testsuite/>", 1)):
            with self.subTest(report=report):
                result = await self.junit(report)
                self.assertEqual(result["suite_count"], suites)
                self.assertEqual(result["test_count"], 0)
                self.assertFalse(result["truncated"])
        result = await self.junit('<testsuite><testcase/><testcase time="0"/></testsuite>')
        self.assertEqual(result["missing_time_count"], 1)
        self.assertEqual(result["timed_test_count"], 1)

    async def test_junit_rejects_dtd_entities_and_malformed_xml_without_echo(self):
        reports = ('<!DOCTYPE testsuite><testsuite/>',
                   '<!DOCTYPE testsuite [<!ENTITY secret "RAW_SECRET">]><testsuite>&secret;</testsuite>',
                   '<!DOCTYPE testsuite SYSTEM "https://example.com/RAW_SECRET"><testsuite/>',
                   '<testsuite>RAW_SECRET', '<other/>', '')
        for report in reports:
            with self.subTest(report=report):
                text = await self.call("inspect_junit_report", report)
                self.assertTrue(text.startswith("Error:"))
                self.assertNotIn("RAW_SECRET", text)

    async def test_junit_rejects_invalid_counts_times_and_overflow(self):
        for attribute in ('tests="-1"', 'tests="1.5"', 'errors="true"', 'skipped="1000000000001"',
                          'time="NaN"', 'time="inf"', 'time="-1"', 'time="bad"'):
            with self.subTest(attribute=attribute):
                self.assertTrue((await self.call("inspect_junit_report", f'<testsuite {attribute}/>')).startswith("Error:"))
        self.assertTrue((await self.call("inspect_junit_report", '<testsuite><testcase time="bad"/></testsuite>')).startswith("Error:"))
        self.assertIn("numeric range", await self.call("inspect_junit_report", '<testsuite><testcase time="1e308"/><testcase time="1e308"/></testsuite>'))

    async def test_junit_resource_bounds_validate_all_not_only_returned_rows(self):
        reports = ("<testsuite>" + "<x/>" * 10000 + "</testsuite>",
                   "<testsuite>" + "<x>" * 50 + "</x>" * 50 + "</testsuite>",
                   "<testsuites>" + "<testsuite/>" * 1001 + "</testsuites>",
                   "<testsuite>" + "<testcase/>" * 2001 + "</testsuite>",
                   '<testsuites><testsuite/><testsuite time="NaN"/></testsuites>')
        for report in reports:
            with self.subTest(size=len(report)):
                self.assertTrue((await self.call("inspect_junit_report", report, limit=1)).startswith("Error:"))

    async def test_sarif_explicit_levels_only_and_inline_rule_indexes(self):
        driver = {"driver": {"name": "scanner", "rules": [{"id": "R1", "defaultConfiguration": {"level": "error"}}]}}
        results = [{"ruleIndex": 0, "message": {"text": "one"}},
                   {"ruleId": "R1", "level": "warning", "kind": "fail", "message": {"markdown": "**two**"}}]
        result = await self.sarif(sarif(results, tool=driver))
        self.assertEqual(result["result_count"], 2)
        self.assertEqual(result["reported_level_counts"], {"unspecified": 1, "warning": 1})
        self.assertIsNone(result["results"][0]["reported_level"])
        self.assertEqual(result["results"][0]["rule_id"], "R1")
        self.assertEqual(result["results"][1]["message"], "**two**")
        self.assertEqual(result["rules"], [{"run_index": 0, "rule_id": "R1", "count": 2}])

    async def test_sarif_unavailable_results_not_reported_as_clean_scan(self):
        for run in ({"tool": {"driver": {"name": "demo"}}},
                    {"tool": {"driver": {"name": "demo"}}, "results": None}):
            result = await self.sarif(json.dumps({"version": "2.1.0", "runs": [run]}))
            self.assertFalse(result["runs"][0]["results_available"])
            self.assertEqual(result["result_count"], 0)
        self.assertTrue((await self.sarif(sarif()))["runs"][0]["results_available"])

    async def test_sarif_suppression_states_and_all_result_counts(self):
        values = (None, [], [{"kind": "inSource", "status": "accepted", "justification": "JUSTIFICATION_SECRET"}],
                  [{"kind": "external", "status": "rejected"}], [{"kind": "external", "status": "underReview"}],
                  [{"kind": "inSource"}], [{"status": "rejected"}, {"status": "accepted"}])
        result = await self.sarif(sarif([{"message": {"text": "reported"}, "suppressions": value} for value in values]))
        self.assertEqual([row["suppression_state"] for row in result["results"]],
                         ["unknown", "not_accepted", "accepted", "not_accepted", "pending_or_unspecified", "pending_or_unspecified", "accepted"])
        self.assertEqual(result["result_count"], 7)
        self.assertEqual(result["suppression_state_counts"]["accepted"], 2)
        self.assertNotIn("JUSTIFICATION_SECRET", json.dumps(result))

    async def test_sarif_artifact_index_and_unresolved_uri_base(self):
        location = {"physicalLocation": {"artifactLocation": {"index": 0}, "region": {"startLine": 8, "startColumn": 2}}}
        result = await self.sarif(sarif([{"message": {"text": "issue"}, "locations": [location]}],
                                        artifacts=[{"location": {"uri": "src/main.py", "uriBaseId": "%SRCROOT%"}}],
                                        originalUriBaseIds={"%SRCROOT%": {"uri": "file:///LOCAL_SECRET/"}}))
        row = result["results"][0]["locations"][0]
        self.assertEqual(row["uri"], "src/main.py")
        self.assertEqual(row["uri_base_id"], "%SRCROOT%")
        self.assertEqual(row["startLine"], 8)
        self.assertNotIn("LOCAL_SECRET", json.dumps(result))

    async def test_sarif_negative_sentinel_out_of_range_and_extension_indexes_not_resolved(self):
        rules = {"driver": {"name": "demo", "rules": [{"id": "wrong"}]}}
        results = [{"ruleIndex": -1, "message": {}, "locations": [{"physicalLocation": {"artifactLocation": {"index": -1}}}]},
                   {"ruleIndex": 100, "message": {}},
                   {"rule": {"index": 0, "toolComponent": {"index": 0}}, "message": {"id": "unexpanded", "arguments": ["ARG_SECRET"]}}]
        result = await self.sarif(sarif(results, tool=rules, artifacts=[{"location": {"uri": "wrong"}}]))
        self.assertTrue(all(row["rule_id"] is None for row in result["results"]))
        self.assertIsNone(result["results"][0]["locations"][0]["uri"])
        self.assertIsNone(result["results"][2]["message"])
        self.assertNotIn("ARG_SECRET", json.dumps(result))

    async def test_sarif_rules_from_different_runs_not_combined(self):
        run = {"tool": {"driver": {"name": "demo"}}, "results": [{"ruleId": "R", "message": {"text": "one"}}]}
        result = await self.sarif(json.dumps({"version": "2.1.0", "runs": [run, run]}), limit=1)
        self.assertEqual(result["run_count"], 2)
        self.assertEqual(result["result_count"], 2)
        self.assertEqual(result["rules"][0]["count"], 1)
        self.assertTrue(result["truncated"])

    async def test_sarif_truncates_text_and_locations_but_counts_all_results(self):
        location = {"physicalLocation": {"artifactLocation": {"uri": "p" * 2001}}}
        result = await self.sarif(sarif([{"message": {"text": "m" * 1001}, "locations": [location] * 6},
                                        {"level": "error", "message": {}}]), limit=1)
        self.assertEqual(result["result_count"], 2)
        self.assertEqual(result["reported_level_counts"]["error"], 1)
        self.assertEqual(len(result["results"][0]["message"]), 1000)
        self.assertEqual(len(result["results"][0]["locations"]), 5)
        self.assertEqual(len(result["results"][0]["locations"][0]["uri"]), 2000)
        self.assertTrue(result["truncated"])

    async def test_sarif_omits_snippets_fixes_flows_and_external_file_contents(self):
        result = await self.sarif(sarif([{"message": {"text": "issue"}, "fixes": "FIX_SECRET", "codeFlows": "FLOW_SECRET",
                                         "locations": [{"physicalLocation": {"region": {"snippet": {"text": "SNIPPET_SECRET"}}}}]}],
                                        externalPropertyFileReferences={"results": [{"location": {"uri": "https://example.com/EXTERNAL_SECRET"}}]}))
        self.assertTrue(result["runs"][0]["external_properties_declared"])
        for secret in ("FIX_SECRET", "FLOW_SECRET", "SNIPPET_SECRET", "EXTERNAL_SECRET"):
            self.assertNotIn(secret, json.dumps(result))

    async def test_sarif_rejects_bad_json_version_duplicates_and_nonfinite(self):
        for report in ('[]', '{RAW_SECRET', '{"version":"2.1.0","runs":[],"runs":[]}',
                       '{"version":"2.0.0","runs":[]}', '{"version":"2.1.0","runs":[],"x":NaN}',
                       '{"version":"2.1.0","runs":[],"x":1e999}', '{"version":"2.1.0","runs":null}'):
            with self.subTest(report=report):
                text = await self.call("inspect_sarif_report", report)
                self.assertTrue(text.startswith("Error:"))
                self.assertNotIn("RAW_SECRET", text)

    async def test_sarif_rejects_invalid_selected_fields_even_when_omitted(self):
        results = ({"level": "fatal"}, {"kind": "error"}, {"ruleIndex": True}, {"ruleIndex": -2},
                   {"ruleId": "bad\nname"}, {"message": "bad"}, {"message": {"text": 2}},
                   {"suppressions": [{"status": "yes"}]}, {"suppressions": [{"kind": "other"}]},
                   {"locations": [{"physicalLocation": {"region": {"startLine": 0}}}]},
                   {"locations": [{"physicalLocation": {"artifactLocation": {"index": -2}}}]})
        for fields in results:
            with self.subTest(fields=fields):
                raw = {"message": {}, **fields}
                self.assertTrue((await self.call("inspect_sarif_report", sarif([{"message": {}}, raw]), limit=1)).startswith("Error:"))
        for fields in ({"tool": {"driver": {"name": ""}}}, {"results": {}}, {"artifacts": [False]},
                       {"tool": {"driver": {"name": "demo", "rules": [{"id": "R"}, {"id": "R"}]}}}):
            with self.subTest(fields=fields):
                self.assertTrue((await self.call("inspect_sarif_report", sarif(**fields))).startswith("Error:"))

    async def test_sarif_resource_bounds(self):
        reports = (sarif([{"message": {}}] * 2001), sarif((), artifacts=[{}] * 1001),
                   sarif([{"message": {}, "locations": [{}] * 21}]),
                   sarif([{"message": {}, "suppressions": [{}] * 21}]),
                   json.dumps({"version": "2.1.0", "runs": [{}] * 21}),
                   '{"version":"2.1.0","runs":[],"x":' + '[' * 51 + '0' + ']' * 51 + '}',
                   json.dumps({"version": "2.1.0", "runs": [], "x": [0] * 20000}))
        for report in reports:
            with self.subTest(size=len(report)):
                self.assertTrue((await self.call("inspect_sarif_report", report, limit=1)).startswith("Error:"))

    async def test_shared_input_limit_and_output_budgets(self):
        for name, report in (("inspect_junit_report", "<testsuite/>"), ("inspect_sarif_report", sarif())):
            for limit in (0, 51):
                with self.subTest(name=name, limit=limit):
                    self.assertTrue((await self.call(name, report, limit=limit)).startswith("Error:"))
            self.assertTrue((await self.call(name, "x" * 200001)).startswith("Error:"))
        for function in ("inspect_junit", "inspect_sarif"):
            with patch.object(service, function, return_value={"oversized": "x" * 100001}):
                name = "inspect_junit_report" if function == "inspect_junit" else "inspect_sarif_report"
                self.assertIn("summary exceeds", await self.call(name, ""))

    async def test_ci_parsers_use_no_files_network_or_commands(self):
        with patch("builtins.open", side_effect=AssertionError("No file access")), \
             patch("socket.getaddrinfo", side_effect=AssertionError("No network")), \
             patch("subprocess.run", side_effect=AssertionError("No commands")):
            self.assertEqual(service.inspect_junit("<testsuite/>", 20)["test_count"], 0)
            self.assertEqual(service.inspect_sarif(sarif(), 20)["result_count"], 0)
        for function, report in ((service.inspect_junit, "<testsuite/>"), (service.inspect_sarif, sarif())):
            with self.assertRaises(ValueError):
                function(report, True)

    async def test_real_ci_summaries_enforce_output_budget_and_can_be_narrowed(self):
        text = "m" * 900
        case = f'<testcase name="{text}" classname="{text}" time="1"><failure message="{text}"/></testcase>'
        junit = '<testsuite>' + case * 50 + '</testsuite>'
        location = {"physicalLocation": {"artifactLocation": {"uri": "p" * 1900}}}
        report = sarif([{"message": {"text": text}, "locations": [location] * 2}] * 30)
        for name, content in (("inspect_junit_report", junit), ("inspect_sarif_report", report)):
            with self.subTest(name=name):
                self.assertLessEqual(len(content), 200000)
                self.assertIn("summary exceeds", await self.call(name, content, limit=50))
                result = json.loads(await self.call(name, content, limit=1))
                self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
