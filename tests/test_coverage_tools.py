import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.coverage_utils import service, tool


def lcov(records="DA:1,2\nDA:2,0\n", path="src/app.py"):
    return f"SF:{path}\n{records}end_of_record\n"


def cobertura(lines='<line number="1" hits="2"/><line number="2" hits="0"/>', attributes="", extra=""):
    return f'<coverage {attributes}><packages><package name="demo"><classes><class name="App" filename="app.py">{extra}<lines>{lines}</lines></class></classes></package></packages></coverage>'


class CoverageToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("coverage-tests")
        tool.register(self.mcp)

    async def call(self, name, content, **arguments):
        result = await self.mcp.call_tool(name, {"content": content, **arguments})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def lcov(self, content, **arguments):
        return json.loads(await self.call("inspect_lcov_report", content, **arguments))

    async def cobertura(self, content, **arguments):
        return json.loads(await self.call("inspect_cobertura_report", content, **arguments))

    async def test_lcov_observed_lines_declared_counts_and_mismatches(self):
        result = await self.lcov('TN:smoke\n' + lcov("DA:1,2,checksum\nDA:2,0\nLF:3\nLH:1\n"))
        row = result["files"][0]
        self.assertEqual(row["test_name"], "smoke")
        self.assertEqual(row["observed"]["lines"], {"found": 2, "hit": 1, "unknown": 0, "coverage_percent": 50})
        self.assertEqual(row["declared"]["lines"], {"found": 3, "hit": 1})
        self.assertEqual(row["declared_mismatches"], ["lines.found"])
        self.assertEqual(result["mismatched_record_count"], 1)
        self.assertEqual(row["uncovered_lines"], [2])

    async def test_lcov_legacy_functions_with_commas_and_end_lines(self):
        report = lcov("FN:1,9,call(a,b)\nFNDA:2,call(a,b)\nFN:10,not_run\nFNDA:0,not_run\nFNF:2\nFNH:1\n")
        result = await self.lcov(report)
        row = result["files"][0]
        self.assertEqual(row["function_format"], "legacy")
        self.assertEqual(row["functions"][0]["name"], "call(a,b)")
        self.assertEqual(row["functions"][0]["end_line"], 9)
        self.assertEqual(row["observed"]["functions"]["coverage_percent"], 50)
        self.assertEqual(row["declared_mismatches"], [])

    async def test_lcov_missing_function_counts_stay_unknown(self):
        result = await self.lcov(lcov("FN:1,unknown\nFNDA:3,without_definition\n"))
        observed = result["files"][0]["observed"]["functions"]
        self.assertEqual(observed["found"], 2)
        self.assertEqual(observed["hit"], 1)
        self.assertEqual(observed["unknown"], 1)
        self.assertIsNone(observed["coverage_percent"])
        self.assertIsNone(result["files"][0]["functions"][1]["start_line"])

    async def test_lcov_grouped_functions_count_aliases_once(self):
        report = lcov("FNA:0,0,alias_one\nFNA:0,2,alias_two\nFNL:0,1,5\nFNL:1,6\nFNA:1,0,other\nFNF:2\nFNH:1\n")
        result = await self.lcov(report)
        row = result["files"][0]
        self.assertEqual(row["function_format"], "grouped")
        self.assertEqual(row["observed"]["functions"]["found"], 2)
        self.assertEqual(row["observed"]["functions"]["coverage_percent"], 50)
        self.assertEqual(row["functions"][0]["alias_count"], 2)
        self.assertTrue(row["functions"][0]["hit"])
        self.assertNotIn("execution_count", row["functions"][0])

    async def test_lcov_branches_unknown_taken_exclusions_and_expressions(self):
        report = lcov("BRDA:1,0,call(a,b),1\nBRDA:1,e0,!ready,0\nBRDA:2,0,other,-\nBRDA:3,fU0,excluded,0\nBRF:3\nBRH:1\n")
        result = await self.lcov(report)
        row = result["files"][0]
        self.assertEqual(row["branch_records"][0]["branch"], "call(a,b)")
        self.assertEqual(row["observed"]["branches"]["found"], 3)
        self.assertAlmostEqual(row["observed"]["branches"]["coverage_percent"], 100 / 3)
        self.assertEqual(row["unknown_branch_taken_count"], 1)
        self.assertEqual(row["excluded_branch_count"], 1)
        self.assertEqual(row["declared_mismatches"], [])

    async def test_lcov_repeated_files_are_separate_sections_not_merged(self):
        result = await self.lcov(lcov("DA:1,1\n") + lcov("DA:1,0\n"), limit=1)
        self.assertEqual(result["record_count"], 2)
        self.assertEqual(result["unique_file_count"], 1)
        self.assertEqual(result["observed_record_totals"]["lines"]["found"], 2)
        self.assertEqual(result["observed_record_totals"]["lines"]["coverage_percent"], 50)
        self.assertEqual(len(result["files"]), 1)
        self.assertTrue(result["truncated"])

    async def test_lcov_extensions_are_explicitly_ignored_without_returning_values(self):
        result = await self.lcov(lcov("VER:VERSION_SECRET\nMCDC:EXPRESSION_SECRET\nMCF:1\nMCH:0\n"))
        self.assertEqual(result["ignored_record_types"], {"MCDC": 1, "MCF": 1, "MCH": 1})
        self.assertNotIn("VERSION_SECRET", json.dumps(result))
        self.assertNotIn("EXPRESSION_SECRET", json.dumps(result))

    async def test_lcov_empty_comment_only_and_kf(self):
        for report in ("", "# comment\n\n"):
            result = await self.lcov(report)
            self.assertEqual(result["record_count"], 0)
            self.assertIsNone(result["observed_record_totals"]["lines"]["coverage_percent"])
        self.assertEqual((await self.lcov("KF:app.c\nend_of_record\n"))["files"][0]["file"], "app.c")

    async def test_lcov_limits_bound_uncovered_lines_functions_aliases_and_branches(self):
        report = lcov("DA:1,0\nDA:2,0\nFNL:0,1\nFNA:0,0,a\nFNA:0,0,b\nFNL:1,2\nFNA:1,0,c\nBRDA:1,0,0,0\nBRDA:2,0,0,0\n")
        row = (await self.lcov(report, limit=1))["files"][0]
        self.assertEqual(row["uncovered_line_count"], 2)
        self.assertEqual(row["uncovered_lines"], [1])
        self.assertEqual(len(row["functions"]), 1)
        self.assertEqual(len(row["functions"][0]["aliases"]), 1)
        self.assertEqual(row["functions"][0]["alias_count"], 2)
        self.assertEqual(len(row["branch_records"]), 1)

    async def test_lcov_rejects_misplaced_records_and_unterminated_sections(self):
        for report in ("DA:1,0\n", "end_of_record\n", "SF:a\n", "TN:pending\n", "TN:a\nTN:b\n", "SF:a\nSF:b\n",
                       lcov("TN:a\n"), "RAW_SECRET", "SF:\nend_of_record\n"):
            with self.subTest(report=report):
                text = await self.call("inspect_lcov_report", report)
                self.assertTrue(text.startswith("Error:"))
                self.assertNotIn("RAW_SECRET", text)

    async def test_lcov_rejects_duplicates_bad_numbers_mixed_formats_and_orphan_aliases(self):
        for records in ("DA:1,0\nDA:1,1\n", "DA:0,1\n", "DA:1,-1\n", "DA:1,NaN\n", "DA:1,1,2,3\n", "LF:2\nLH:3\n",
                        "LF:2\nLF:2\n", "FN:2,1,bad_range\n", "FN:1,a\nFN:2,a\n", "FNDA:0,a\nFNDA:1,a\n",
                        "FNL:0,1\n", "FNA:0,0,a\n", "FNL:0,1\nFNA:0,0,a\nFNDA:0,legacy\n",
                        "FNL:0,1\nFNA:0,0,a\nFNA:0,1,a\n", "BRDA:1,0,0,0\nBRDA:1,0,0,1\n",
                        "BRDA:1,bad,0,0\n", "BRDA:1,0,0,-2\n", "FNDA:1000000000001,a\n"):
            with self.subTest(records=records):
                self.assertTrue((await self.call("inspect_lcov_report", lcov(records))).startswith("Error:"))

    async def test_lcov_resource_limits_and_validation_beyond_returned_rows(self):
        for report in (lcov() * 201, "#x\n" * 5001, "#" + "x" * 10000, lcov(path="p" * 1001),
                       lcov() + lcov("DA:1,-1\n")):
            with self.subTest(size=len(report)):
                self.assertTrue((await self.call("inspect_lcov_report", report, limit=1)).startswith("Error:"))

    async def test_cobertura_observed_lines_declared_root_and_class_rates_separate(self):
        result = await self.cobertura(cobertura(attributes='lines-valid="10" lines-covered="9" line-rate="0.9" branch-rate="0"'))
        self.assertEqual(result["declared"]["lines"], {"found": 10, "hit": 9, "rate": 0.9})
        self.assertEqual(result["observed_class_lines"]["coverage_percent"], 50)
        self.assertEqual(result["classes"][0]["uncovered_lines"], [2])
        self.assertIsNone(result["classes"][0]["declared"]["lines"]["rate"])
        self.assertEqual(result["package_count"], 1)
        self.assertEqual(result["class_count"], 1)

    async def test_cobertura_method_line_copies_are_not_counted_twice(self):
        method = '<methods><method name="ignored"><lines><line number="1" hits="99"/></lines></method></methods>'
        result = await self.cobertura(cobertura(extra=method))
        self.assertEqual(result["observed_class_lines"]["found"], 2)
        self.assertEqual(result["observed_class_lines"]["hit"], 1)

    async def test_cobertura_branch_counts_use_explicit_counts_not_percentage_rounding(self):
        lines = '<line number="1" hits="1" branch="true" condition-coverage="66.7% (2/3)"/>'
        result = await self.cobertura(cobertura(lines))
        self.assertEqual(result["observed_class_branches"]["found"], 3)
        self.assertEqual(result["observed_class_branches"]["hit"], 2)
        self.assertAlmostEqual(result["observed_class_branches"]["coverage_percent"], 200 / 3)

    async def test_cobertura_missing_branch_counts_stay_unknown(self):
        result = await self.cobertura(cobertura('<line number="1" hits="1" branch="true"/><line number="2" hits="1" branch="true" condition-coverage="50% (1/2)"/>'))
        self.assertEqual(result["observed_class_branches"]["unknown"], 1)
        self.assertEqual(result["observed_class_branches"]["found"], 2)
        self.assertIsNone(result["observed_class_branches"]["coverage_percent"])

    async def test_cobertura_external_doctype_is_not_loaded_and_source_roots_omitted(self):
        report = '<!DOCTYPE coverage SYSTEM "https://example.com/DTD_SECRET">' + cobertura()
        report = report.replace('<packages>', '<sources><source>ROOT_SECRET</source></sources><packages>')
        with patch("builtins.open", side_effect=AssertionError("DTD/source files must not be opened")), \
             patch("socket.getaddrinfo", side_effect=AssertionError("DTD must not be fetched")):
            result = service.inspect_cobertura(report, 20)
        self.assertEqual(result["class_count"], 1)
        self.assertNotIn("ROOT_SECRET", json.dumps(result))
        self.assertNotIn("DTD_SECRET", json.dumps(result))

    async def test_cobertura_namespace_empty_reports_and_least_covered_classes(self):
        self.assertEqual((await self.cobertura('<coverage xmlns="urn:c"/>'))["class_count"], 0)
        report = cobertura().replace('<coverage ', '<coverage xmlns="urn:c" ')
        extra = '<class name="Empty" filename="empty.py"><lines><line number="4" hits="0"/></lines></class>'
        report = report.replace('</classes>', extra + '</classes>')
        result = await self.cobertura(report, limit=1)
        self.assertEqual(result["class_count"], 2)
        self.assertEqual(result["least_covered_classes"][0]["name"], "Empty")
        self.assertTrue(result["truncated"])

    async def test_cobertura_repeated_filenames_not_merged(self):
        report = cobertura().replace('</classes>', '<class filename="app.py"><lines><line number="1" hits="0"/></lines></class></classes>')
        result = await self.cobertura(report)
        self.assertEqual(result["unique_file_count"], 1)
        self.assertEqual(result["observed_class_lines"]["found"], 3)

    async def test_cobertura_rejects_entities_malformed_xml_and_bad_roots_without_echo(self):
        for report in ('<!DOCTYPE coverage [<!ENTITY x "RAW_SECRET">]><coverage>&x;</coverage>',
                       '<!DOCTYPE coverage [<!ENTITY x SYSTEM "file:///RAW_SECRET">]><coverage/>',
                       '<!DOCTYPE coverage [<!ENTITY % x SYSTEM "https://example.com/RAW_SECRET">%x;]><coverage/>',
                       '<coverage>RAW_SECRET', '<testsuite/>', ''):
            with self.subTest(report=report):
                text = await self.call("inspect_cobertura_report", report)
                self.assertTrue(text.startswith("Error:"))
                self.assertNotIn("RAW_SECRET", text)

    async def test_cobertura_rejects_invalid_selected_attributes_and_duplicate_lines(self):
        for lines in ('<line number="0" hits="1"/>', '<line number="1" hits="-1"/>', '<line number="1"/>',
                      '<line number="1" hits="1"/><line number="1" hits="0"/>',
                      '<line number="1" hits="1" branch="yes"/>',
                      '<line number="1" hits="1" branch="true" condition-coverage="50%"/>',
                      '<line number="1" hits="1" branch="true" condition-coverage="100% (3/2)"/>',
                      '<line number="1" hits="1" condition-coverage="101% (1/1)"/>'):
            with self.subTest(lines=lines):
                self.assertTrue((await self.call("inspect_cobertura_report", cobertura(lines))).startswith("Error:"))
        for attributes in ('line-rate="1.1"', 'branch-rate="NaN"', 'line-rate="-1"', 'lines-valid="1" lines-covered="2"'):
            self.assertTrue((await self.call("inspect_cobertura_report", cobertura(attributes=attributes))).startswith("Error:"))

    async def test_cobertura_resource_limits_and_validation_beyond_returned_rows(self):
        reports = ('<coverage>' + '<x/>' * 10000 + '</coverage>',
                   '<coverage>' + '<x>' * 50 + '</x>' * 50 + '</coverage>',
                   '<coverage><packages>' + '<package/>' * 201 + '</packages></coverage>',
                   cobertura().replace('</classes>', '<class filename="a"/>' * 1000 + '</classes>'),
                   cobertura(''.join(f'<line number="{i}" hits="0"/>' for i in range(1, 5002))),
                   cobertura().replace('</classes>', '<class filename="bad" line-rate="NaN"/></classes>'))
        for report in reports:
            with self.subTest(size=len(report)):
                self.assertTrue((await self.call("inspect_cobertura_report", report, limit=1)).startswith("Error:"))

    async def test_coverage_shared_limits_output_budget_and_no_execution(self):
        for name, report in (("inspect_lcov_report", lcov()), ("inspect_cobertura_report", cobertura())):
            for content, limit in (("x" * 200001, 20), (report, 0), (report, 51)):
                self.assertTrue((await self.call(name, content, limit=limit)).startswith("Error:"))
        for function, report in ((service.inspect_lcov, lcov()), (service.inspect_cobertura, cobertura())):
            with self.assertRaises(ValueError):
                function(report, True)
            with patch("builtins.open", side_effect=AssertionError("No files")), \
                 patch("socket.getaddrinfo", side_effect=AssertionError("No network")), \
                 patch("subprocess.run", side_effect=AssertionError("No execution")):
                function(report, 20)
        for function, name in (("inspect_lcov", "inspect_lcov_report"), ("inspect_cobertura", "inspect_cobertura_report")):
            with patch.object(service, function, return_value={"oversized": "x" * 100001}):
                self.assertIn("summary exceeds", await self.call(name, ""))

    async def test_real_coverage_output_budgets_can_be_narrowed(self):
        branches = ''.join(f'BRDA:{i},0,0,0\n' for i in range(1, 51))
        trace = lcov(branches) * 50
        classes = ''.join(f'<class name="{"n" * 950}" filename="file{i}{"p" * 950}"><lines><line number="1" hits="0"/></lines></class>' for i in range(30))
        xml = '<coverage><packages><package><classes>' + classes + '</classes></package></packages></coverage>'
        for name, content in (("inspect_lcov_report", trace), ("inspect_cobertura_report", xml)):
            with self.subTest(name=name):
                self.assertLessEqual(len(content), 200000)
                self.assertIn("summary exceeds", await self.call(name, content, limit=50))
                self.assertTrue(json.loads(await self.call(name, content, limit=1))["truncated"])


if __name__ == "__main__":
    unittest.main()
