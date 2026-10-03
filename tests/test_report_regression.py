import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.report_regression import service, tool


def sarif(results=None, *, tool_name="scanner", external=False):
    run = {"tool": {"driver": {"name": tool_name}}}
    if results is not None:
        run["results"] = results
    if external:
        run["externalPropertyFileReferences"] = {}
    return json.dumps({"version": "2.1.0", "runs": [run]})


def finding(value="fingerprint-secret", *, rule="R1", level="warning", **fields):
    return {"ruleId": rule, "message": {"text": "MESSAGE_SECRET"}, "level": level,
            "fingerprints": {"primaryLocationLineHash": value}, **fields}


def bom(components, **fields):
    return json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.7", "components": components, **fields})


def component(name="demo", ref="local", **fields):
    return {"type": "library", "name": name, "bom-ref": ref, **fields}


def access(status, path="/health?token=QUERY_SECRET", *, combined=True):
    line = (f'192.0.2.1 - PRIVATE_USER [10/Oct/2000:13:55:36 -0700] '
            f'"GET {path} HTTP/1.1" {status} 12')
    return line + (' "PRIVATE_REFERRER" "PRIVATE_AGENT"' if combined else '') + "\n"


class ReportRegressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("report-regressions")
        tool.register(self.mcp)

    async def call(self, name, before, after, **arguments):
        result = await self.mcp.call_tool(name, {"before": before, "after": after, **arguments})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def compare(self, name, before, after, **arguments):
        return json.loads(await self.call(name, before, after, **arguments))

    async def test_registers_four_tools(self):
        self.assertEqual({item.name for item in await self.mcp.list_tools()}, {
            "compare_sarif_reports", "compare_sboms", "compare_prometheus_metrics", "compare_access_logs"})

    async def test_sarif_matches_fingerprints_not_position_and_omits_raw_values(self):
        before = sarif([finding("one", locations=[{"physicalLocation": {"artifactLocation": {"uri": "src/a.py"}}}]),
                        finding("gone")])
        after = sarif([finding("new"), finding("one", level="error", kind="fail",
                                                  suppressions=[{"kind": "external", "status": "accepted"}])])
        output = await self.call("compare_sarif_reports", before, after)
        result = json.loads(output)
        self.assertEqual(result["matching"]["matched_count"], 1)
        self.assertEqual(result["matching"]["added_count"], 1)
        self.assertEqual(result["matching"]["removed_count"], 1)
        self.assertEqual(result["changed_count"], 1)
        self.assertEqual(result["changes"][0]["changed_fields"],
                         ["reported_level", "reported_kind", "suppression_state"])
        self.assertTrue(result["selected_results_completely_matchable"])
        self.assertEqual(len(result["changes"][0]["identity"]["fingerprint_sha256"]), 64)
        for secret in ("MESSAGE_SECRET", "primaryLocationLineHash", '"one"', '"gone"', '"new"'):
            self.assertNotIn(secret, output)

    async def test_sarif_missing_duplicate_and_unavailable_results_are_uncertain(self):
        unkeyed = {"ruleId": "R1", "message": {"text": "same"}}
        result = await self.compare("compare_sarif_reports", sarif([unkeyed, finding("duplicate"), finding("duplicate")]),
                                    sarif([finding("duplicate")]))
        self.assertEqual(result["matching"]["unmatchable_before_count"], 1)
        self.assertEqual(result["matching"]["ambiguous_count"], 1)
        self.assertEqual(result["matching"]["matched_count"], 0)
        self.assertFalse(result["selected_results_completely_matchable"])
        result = await self.compare("compare_sarif_reports", sarif(), sarif([]))
        self.assertFalse(result["before"]["inline_results_available"])
        self.assertFalse(result["selected_results_completely_matchable"])
        result = await self.compare("compare_sarif_reports", sarif([], external=True), sarif([]))
        self.assertFalse(result["selected_results_completely_matchable"])

    async def test_sarif_counts_all_results_beyond_display_limit(self):
        before = sarif([finding(str(index)) for index in range(80)])
        after = sarif([finding(str(index), level="error") for index in range(80)])
        result = await self.compare("compare_sarif_reports", before, after, limit=1)
        self.assertEqual(result["matching"]["matched_count"], 80)
        self.assertEqual(result["changed_count"], 80)
        self.assertEqual(len(result["changes"]), 1)
        self.assertTrue(result["truncated"])

    async def test_sbom_matches_versionless_purl_and_license_changes(self):
        old = component(ref="old", version="1.0", purl="pkg:npm/%40scope/demo@1.0?arch=x86",
                        licenses=[{"license": {"id": "MIT", "text": {"content": "LICENSE_SECRET"}}},
                                  {"license": {"id": "Apache-2.0"}}])
        new = component(ref="new", version="2.0", purl="pkg:npm/%40scope/demo@2.0?arch=x86",
                        licenses=[{"license": {"id": "Apache-2.0"}}, {"license": {"id": "MIT"}}])
        result = await self.compare("compare_sboms", bom([old]), bom([new]))
        self.assertEqual(result["matching"]["matched_count"], 1)
        self.assertEqual(result["version_change_count"], 1)
        self.assertEqual(result["license_change_count"], 0)
        self.assertEqual(result["changes"][0]["identity"]["basis"], "purl")
        self.assertNotIn("@1.0", result["changes"][0]["identity"]["purl_without_version"])
        output = await self.call("compare_sboms", bom([old]), bom([component(ref="new", version="2.0",
            purl="pkg:npm/%40scope/demo@2.0?arch=x86", licenses=[{"license": {"id": "BSD-3-Clause"}}])]))
        self.assertEqual(json.loads(output)["license_change_count"], 1)
        self.assertNotIn("LICENSE_SECRET", output)

    async def test_sbom_declared_identity_duplicates_invalid_purls_and_qualifiers(self):
        before = bom([component(ref="a", group="g", version="1"),
                      component("package", "p", purl="pkg:npm/package@1?arch=x86")])
        after = bom([component(ref="b", group="g", version="2"),
                     component("package", "q", purl="pkg:npm/package@2?arch=arm")])
        result = await self.compare("compare_sboms", before, after)
        self.assertEqual(result["matching"]["matched_count"], 1)
        self.assertEqual(result["matching"]["added_count"], 1)
        self.assertEqual(result["matching"]["removed_count"], 1)
        self.assertEqual(result["version_change_count"], 1)
        duplicate = bom([component(ref="a"), component(ref="b")])
        result = await self.compare("compare_sboms", duplicate, bom([component(ref="c")]))
        self.assertEqual(result["matching"]["ambiguous_count"], 1)
        self.assertEqual(result["matching"]["matched_count"], 0)
        invalid = bom([component(purl="not-a-purl")])
        result = await self.compare("compare_sboms", invalid, invalid)
        self.assertEqual(result["matching"]["unmatchable_before_count"], 1)

    async def test_sbom_counts_all_components_beyond_limit(self):
        before = bom([component(f"pkg-{index}", str(index), version="1") for index in range(70)])
        after = bom([component(f"pkg-{index}", str(index), version="2") for index in range(70)])
        result = await self.compare("compare_sboms", before, after, limit=1)
        self.assertEqual(result["matching"]["matched_count"], 70)
        self.assertEqual(result["version_change_count"], 70)
        self.assertEqual(len(result["version_changes"]), 1)
        self.assertTrue(result["truncated"])

    async def test_metrics_gauge_and_counter_snapshots_and_label_identity(self):
        before = ('# TYPE temperature gauge\n'
                  'temperature{room="west"} 20\n'
                  '# TYPE jobs_total counter\n'
                  'jobs_total{queue="a"} 10\n')
        after = ('# TYPE jobs_total counter\n'
                 'jobs_total{queue="a"} 3\n'
                 '# TYPE temperature gauge\n'
                 'temperature{room="west"} 22\n'
                 'temperature{room="east"} 10\n')
        result = await self.compare("compare_prometheus_metrics", before, after)
        self.assertEqual(result["series_matching"]["matched_count"], 2)
        self.assertEqual(result["series_matching"]["added_count"], 1)
        self.assertEqual(result["raw_counter_decrease_count"], 1)
        self.assertEqual(result["raw_counter_decreases"][0]["raw_counter_difference"], -7)
        gauge = next(row for row in result["series_comparisons"] if row["identity"]["family"] == "temperature")
        self.assertEqual(gauge["snapshot_delta"], 2)
        self.assertFalse(gauge["possible_counter_reset"])

    async def test_metrics_type_nonfinite_duplicates_and_full_count(self):
        before = '# TYPE temperature gauge\ntemperature 1\n'
        after = '# TYPE temperature untyped\ntemperature 2\n'
        result = await self.compare("compare_prometheus_metrics", before, after)
        self.assertEqual(result["family_type_change_count"], 1)
        self.assertIsNone(result["series_comparisons"][0]["snapshot_delta"])
        self.assertEqual(result["series_comparisons"][0]["reason"], "family_type_changed")
        result = await self.compare("compare_prometheus_metrics", '# TYPE temperature gauge\ntemperature NaN\n', before)
        self.assertEqual(result["series_comparisons"][0]["reason"], "nonfinite_value")
        duplicate = '# TYPE temperature gauge\ntemperature 1\ntemperature 2\n'
        result = await self.compare("compare_prometheus_metrics", duplicate, before)
        self.assertEqual(result["series_matching"]["ambiguous_count"], 1)
        lines = '# TYPE temperature gauge\n' + ''.join(f'temperature{{id="{index}"}} {index}\n' for index in range(70))
        result = await self.compare("compare_prometheus_metrics", lines, lines, limit=1)
        self.assertEqual(result["series_matching"]["matched_count"], 70)
        self.assertEqual(len(result["series_comparisons"]), 1)
        self.assertTrue(result["truncated"])

    async def test_access_counts_statuses_paths_and_omits_private_fields(self):
        before = access(200) + access(500) + access(404, "/old") + "not a log\n"
        after = access(500, "/health?token=DIFFERENT_SECRET") * 3 + access(200, "/new")
        output = await self.call("compare_access_logs", before, after)
        result = json.loads(output)
        self.assertEqual(result["before"]["invalid_entries"], 1)
        self.assertEqual(result["matching"]["matched_count"], 1)
        self.assertEqual(result["matching"]["added_count"], 1)
        self.assertEqual(result["matching"]["removed_count"], 1)
        self.assertEqual(result["status_changes"][2]["status"], "500")
        self.assertEqual(result["status_changes"][2]["delta"], 2)
        self.assertEqual(result["largest_path_error_count_increases"][0]["error_count"]["delta"], 2)
        self.assertAlmostEqual(result["error_fraction_change"]["delta"], 3 / 4 - 2 / 3)
        self.assertEqual(result["changed_paths"][0]["status_changes"][0]["status"], "200")
        for secret in ("PRIVATE_USER", "PRIVATE_REFERRER", "PRIVATE_AGENT", "QUERY_SECRET", "DIFFERENT_SECRET"):
            self.assertNotIn(secret, output)

    async def test_access_common_format_unknown_status_and_full_path_counts(self):
        before = access(200, combined=False) * 60
        after = access(500, combined=False) * 60
        result = await self.compare("compare_access_logs", before, after, format="common", limit=1)
        self.assertEqual(result["matching"]["matched_count"], 1)
        self.assertEqual(result["changed_paths"][0]["error_count"]["delta"], 60)
        self.assertEqual(result["after"]["parsed_entries"], 60)
        self.assertTrue(result["truncated"])

    async def test_access_status_only_shift_is_counted_before_display_limit(self):
        result = await self.compare("compare_access_logs", access(404), access(500), limit=1)
        self.assertEqual(result["changed_path_count"], 1)
        self.assertEqual(result["changed_paths"][0]["request_count"]["delta"], 0)
        self.assertEqual(result["changed_paths"][0]["error_count"]["delta"], 0)
        self.assertEqual(result["changed_paths"][0]["status_change_count"], 2)
        self.assertEqual(len(result["changed_paths"][0]["status_changes"]), 1)
        self.assertTrue(result["truncated"])

    async def test_invalid_inputs_and_limits_omit_source(self):
        cases = (("compare_sarif_reports", '{"hidden-marker'),
                 ("compare_sboms", '{"hidden-marker'),
                 ("compare_prometheus_metrics", "# EOF hidden-marker\n"),
                 ("compare_access_logs", "x" * 200001))
        for name, invalid in cases:
            with self.subTest(name=name):
                output = await self.call(name, invalid, invalid)
                self.assertTrue(output.startswith("Error:"))
                self.assertNotIn("hidden-marker", output)
        for name in ("compare_sarif_reports", "compare_sboms", "compare_prometheus_metrics", "compare_access_logs"):
            self.assertTrue((await self.call(name, "", "", limit=0)).startswith("Error:"))

    async def test_offline_comparison_does_not_use_files_network_or_commands(self):
        with patch("builtins.open", side_effect=AssertionError("Unexpected file access")), \
                patch("socket.create_connection", side_effect=AssertionError("Unexpected network access")), \
                patch("subprocess.run", side_effect=AssertionError("Unexpected execution")):
            self.assertEqual(service.compare_sarif(sarif([]), sarif([]), 20)["before"]["result_count"], 0)
            self.assertEqual(service.compare_sboms(bom([]), bom([]), 20)["before"]["component_count"], 0)
            self.assertEqual(service.compare_metrics("# TYPE x gauge\nx 1\n", "# TYPE x gauge\nx 2\n", 20)["before"]["sample_count"], 1)
            self.assertEqual(service.compare_access(access(200), access(500), "combined", 20)["before"]["parsed_entries"], 1)


if __name__ == "__main__":
    unittest.main()
