import csv
import io
import json
import unittest
from unittest.mock import MagicMock, patch

from mcp.server.fastmcp import FastMCP

from app.tools.csv_quality import service, tool
from app.tools.csv_utils import service as csv_service, tool as csv_tools
from app.tools.schema_utils import service as schemas


def table(headers, rows=(), delimiter=","):
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue()


def parsed(content, delimiter=","):
    return list(csv.reader(io.StringIO(content, newline=""), delimiter=delimiter, strict=True))


class CsvQualityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("csv-quality-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def result(self, name, **arguments):
        text = await self.call(name, **arguments)
        self.assertFalse(text.startswith("Error:"), text)
        return json.loads(text)

    async def test_registers_four_tools_with_defaults(self):
        tools = {item.name: item for item in await self.mcp.list_tools()}
        self.assertEqual(set(tools), {"profile_csv", "validate_csv_schema", "compare_csv_tables", "redact_csv_columns"})
        self.assertEqual(tools["compare_csv_tables"].inputSchema["required"], ["before", "after", "key_columns_json"])
        self.assertEqual(tools["redact_csv_columns"].inputSchema["properties"]["mask"]["default"], "[REDACTED]")
        self.assertEqual(tools["validate_csv_schema"].inputSchema["properties"]["required_columns_json"]["default"], "[]")

    async def test_profile_exact_counts_empty_whitespace_unique_and_duplicate_rows(self):
        content = table(["id", "note"], [["001", "private-value"], ["001", "private-value"], ["002", ""], ["003", "  "]])
        data = await self.result("profile_csv", csv_text=content)
        self.assertEqual(data["row_count"], 4)
        self.assertEqual(data["column_count"], 2)
        self.assertEqual(data["unique_row_count"], 3)
        self.assertEqual(data["duplicate_row_count"], 1)
        note = data["columns"][1]
        self.assertEqual(note["empty_count"], 1)
        self.assertEqual(note["nonempty_count"], 3)
        self.assertEqual(note["whitespace_only_count"], 1)
        self.assertEqual(note["distinct_value_count"], 3)
        self.assertEqual(note["distinct_nonempty_value_count"], 2)
        self.assertEqual(note["min_length"], 0)
        self.assertEqual(note["max_length"], len("private-value"))
        self.assertNotIn("private-value", json.dumps(data))
        self.assertNotIn("001", json.dumps(data))

    async def test_profile_case_sensitive_strings_and_unicode_code_point_lengths(self):
        content = table(["value"], [["A"], ["a"], ["01"], ["1"], ["e\u0301"], ["\u00e9"]])
        data = await self.result("profile_csv", csv_text=content)
        column = data["columns"][0]
        self.assertEqual(column["distinct_value_count"], 6)
        self.assertEqual(column["min_length"], 1)
        self.assertEqual(column["max_length"], 2)
        self.assertEqual(column["mean_length"], 8 / 6)

    async def test_profile_header_only_has_unknown_lengths_and_zero_counts(self):
        data = await self.result("profile_csv", csv_text="id,note\n")
        self.assertEqual(data["row_count"], 0)
        self.assertEqual(data["duplicate_row_count"], 0)
        self.assertIsNone(data["columns"][0]["min_length"])
        self.assertIsNone(data["columns"][0]["mean_length"])
        self.assertEqual(data["columns"][0]["distinct_value_count"], 0)

    async def test_profile_bom_tsv_quoted_newlines_and_blank_records(self):
        content = '\ufeffid\tnote\r\n001\t"one\r\ntwo"\r\n\r\n002\t"a\t\"\"quote\"\""\r\n'
        data = await self.result("profile_csv", csv_text=content, delimiter="\t")
        self.assertEqual(data["row_count"], 2)
        self.assertEqual(data["columns"][1]["max_length"], len('a\t"quote"'))

    async def test_profile_all_columns_counted_before_display_limit(self):
        content = table([f"c{index}" for index in range(100)], [[""] * 100] * 3)
        data = await self.result("profile_csv", csv_text=content, limit=1)
        self.assertEqual(data["column_count"], 100)
        self.assertEqual(data["duplicate_row_count"], 2)
        self.assertEqual(len(data["columns"]), 1)
        self.assertTrue(data["truncated"])

    async def test_compare_added_removed_changed_rows_by_explicit_key(self):
        data = await self.result("compare_csv_tables", before="id,value\n001,old\n002,same\n003,removed\n",
                                 after="id,value\n002,same\n001,new\n004,added\n", key_columns_json='["id"]')
        self.assertEqual(data["matched_row_count"], 2)
        self.assertEqual(data["changed_row_count"], 1)
        self.assertEqual(data["unchanged_row_count"], 1)
        self.assertEqual(data["added_rows"], [{"key": {"id": "004"}, "row": 3}])
        self.assertEqual(data["removed_rows"], [{"key": {"id": "003"}, "row": 3}])
        change = data["changes"][0]
        self.assertEqual(change["before_row"], 1)
        self.assertEqual(change["after_row"], 2)
        self.assertEqual(change["changes"], [{"column": "value", "type": "changed", "before_present": True,
                                             "after_present": True, "before": "old", "after": "new"}])
        self.assertFalse(data["equal"])
        self.assertIsNone(data["row_order_changed"])

    async def test_compare_exact_composite_keys_no_join_collision_or_trimming(self):
        content = table(["one", "two", "value"], [["a,b", "c", "first"], ["a", "b,c", "second"], [" 01 ", "x", "third"]])
        data = await self.result("compare_csv_tables", before=content, after=content, key_columns_json='["one","two"]')
        self.assertTrue(data["equal"])
        self.assertEqual(data["matched_row_count"], 3)
        changed = table(["one", "two", "value"], [["a,b", "c", "first"], ["a", "b,c", "second"], ["01", "x", "third"]])
        data = await self.result("compare_csv_tables", before=content, after=changed, key_columns_json='["one","two"]')
        self.assertEqual(data["added_row_count"], 1)
        self.assertEqual(data["removed_rows"][0]["key"]["one"], " 01 ")

    async def test_compare_leading_zeros_case_and_literals_remain_distinct(self):
        before = "id,value\n001,true\n1,001\nA,null\na,1.0\n"
        after = "id,value\n001,True\n1,1\nA,\na,1\n"
        data = await self.result("compare_csv_tables", before=before, after=after, key_columns_json='["id"]')
        self.assertEqual(data["matched_row_count"], 4)
        self.assertEqual(data["changed_cell_count"], 4)
        self.assertEqual(data["changes"][1]["changes"][0]["before"], "001")

    async def test_compare_row_and_column_order_reported_separately_from_equality(self):
        data = await self.result("compare_csv_tables", before="id,value\n1,A\n2,B\n",
                                 after="value,id\nB,2\nA,1\n", key_columns_json='["id"]')
        self.assertTrue(data["equal"])
        self.assertTrue(data["column_order_changed"])
        self.assertTrue(data["row_order_changed"])
        self.assertEqual(data["changed_cell_count"], 0)

    async def test_compare_duplicate_keys_are_ambiguous_even_on_one_side(self):
        one, two = "id,value\n1,A\n", "id,value\n1,A\n1,B\n"
        for before, after, counts in ((one, two, (1, 2)), (two, one, (2, 1)), (two, two, (2, 2))):
            data = await self.result("compare_csv_tables", before=before, after=after, key_columns_json='["id"]')
            self.assertIsNone(data["equal"])
            self.assertEqual(data["ambiguous_key_count"], 1)
            self.assertEqual(data["matched_row_count"], 0)
            self.assertEqual((data["ambiguous_keys"][0]["before_count"], data["ambiguous_keys"][0]["after_count"]), counts)
            self.assertEqual(data["added_row_count"], 0)
            self.assertEqual(data["removed_row_count"], 0)

    async def test_compare_blank_or_whitespace_key_components_unkeyed(self):
        content = table(["id", "part", "value"], [["", "x", "A"], ["1", " \t ", "B"], ["2", "x", "C"]])
        data = await self.result("compare_csv_tables", before=content, after=content, key_columns_json='["id","part"]')
        self.assertEqual(data["unkeyed_before_rows"], [1, 2])
        self.assertEqual(data["unkeyed_after_count"], 2)
        self.assertEqual(data["matched_row_count"], 1)
        self.assertIsNone(data["equal"])

    async def test_compare_known_changes_with_ambiguous_keys_are_false(self):
        data = await self.result("compare_csv_tables", before="id,value\n1,A\n2,B\n2,C\n", after="id,value\n1,D\n2,B\n2,C\n",
                                 key_columns_json='["id"]')
        self.assertFalse(data["equal"])
        self.assertEqual(data["ambiguous_key_count"], 1)
        self.assertEqual(data["changed_row_count"], 1)

    async def test_compare_added_removed_columns_and_missing_versus_empty_cells(self):
        data = await self.result("compare_csv_tables", before="id,old,kept\n1,,\n", after="id,new,kept\n1,,\n", key_columns_json='["id"]')
        self.assertEqual(data["added_columns"], ["new"])
        self.assertEqual(data["removed_columns"], ["old"])
        self.assertIsNone(data["column_order_changed"])
        changes = data["changes"][0]["changes"]
        self.assertEqual(changes[0]["before"], "")
        self.assertIsNone(changes[0]["after"])
        self.assertFalse(changes[0]["after_present"])
        self.assertEqual(changes[1]["after"], "")
        self.assertFalse(changes[1]["before_present"])

    async def test_compare_header_only_tables_still_compare_columns(self):
        data = await self.result("compare_csv_tables", before="id,old\n", after="id,new\n", key_columns_json='["id"]')
        self.assertFalse(data["equal"])
        self.assertEqual(data["matched_row_count"], 0)
        self.assertEqual(data["added_column_count"], 1)
        same = await self.result("compare_csv_tables", before="id,old\n", after="old,id\n", key_columns_json='["id"]')
        self.assertTrue(same["equal"])

    async def test_compare_record_ordinals_not_physical_lines(self):
        before = 'id,value\n\n1,"one\ntwo"\n\n2,A\n'
        after = before.replace("2,A", "2,B")
        data = await self.result("compare_csv_tables", before=before, after=after, key_columns_json='["id"]')
        self.assertEqual(data["changes"][0]["before_row"], 2)
        self.assertEqual(data["changes"][0]["after_row"], 2)

    async def test_compare_all_rows_cells_and_key_values_before_display_limits(self):
        headers = ["id"] + [f"c{index}" for index in range(10)]
        old = table(headers, [[str(index)] + ["old"] * 10 for index in range(60)])
        new = table(headers, [[str(index)] + ["new"] * 10 for index in range(60)])
        data = await self.result("compare_csv_tables", before=old, after=new, key_columns_json='["id"]', limit=1)
        self.assertEqual(data["changed_row_count"], 60)
        self.assertEqual(data["changed_cell_count"], 600)
        self.assertEqual(data["changes"][0]["change_count"], 10)
        self.assertEqual(len(data["changes"][0]["changes"]), 1)
        self.assertTrue(data["truncated"])
        prefix = "x" * 1000
        old, new = table(["id", "value"], [[prefix + "a", "old"]]), table(["id", "value"], [[prefix + "b", "new"]])
        data = await self.result("compare_csv_tables", before=old, after=new, key_columns_json='["id"]')
        self.assertEqual(data["matched_row_count"], 0)
        self.assertEqual(data["added_row_count"], 1)
        self.assertEqual(data["removed_row_count"], 1)
        self.assertEqual(data["added_rows"][0]["key"], data["removed_rows"][0]["key"])
        self.assertTrue(data["truncated"])

    async def test_compare_long_changed_values_not_equal_after_shortening(self):
        prefix = "x" * 1000
        data = await self.result("compare_csv_tables", before=table(["id", "value"], [["1", prefix + "old"]]),
                                 after=table(["id", "value"], [["1", prefix + "new"]]), key_columns_json='["id"]')
        self.assertFalse(data["equal"])
        self.assertEqual(data["changed_cell_count"], 1)
        self.assertEqual(data["changes"][0]["changes"][0]["before"], data["changes"][0]["changes"][0]["after"])
        self.assertTrue(data["truncated"])

    async def test_compare_counts_added_removed_and_ambiguous_beyond_limit(self):
        data = await self.result("compare_csv_tables", before="id\n" + ''.join(f"old{index}\n" for index in range(60)),
                                 after="id\n" + ''.join(f"new{index}\n" for index in range(60)), key_columns_json='["id"]', limit=1)
        self.assertEqual(data["added_row_count"], 60)
        self.assertEqual(data["removed_row_count"], 60)
        self.assertEqual(len(data["added_rows"]), 1)
        duplicates = "id\n" + ''.join(f"{index}\n{index}\n" for index in range(60))
        data = await self.result("compare_csv_tables", before=duplicates, after=duplicates, key_columns_json='["id"]', limit=1)
        self.assertEqual(data["ambiguous_key_count"], 60)
        self.assertTrue(data["truncated"])

    async def test_redact_exact_columns_and_counts_including_empty_cells(self):
        data = await self.result("redact_csv_columns", csv_text="id,email,token\n001,private-email,private-token\n002,,private-token2\n",
                                 columns_json='["email","token"]')
        self.assertEqual(parsed(data["csv"]), [["id", "email", "token"], ["001", "[REDACTED]", "[REDACTED]"], ["002", "[REDACTED]", "[REDACTED]"]])
        self.assertEqual(data["replacement_count"], 4)
        self.assertEqual(data["redacted_columns"], ["email", "token"])
        self.assertFalse(data["truncated"])
        self.assertNotIn("private-", json.dumps(data))

    async def test_redact_preserves_unselected_cr_lf_quotes_delimiters_and_formulas(self):
        retained = ['a\rb', 'a\nb', 'a\r\nb', 'a,"b"', '=HYPERLINK("https://example.com")', "001", ""]
        content = table(["keep", "token"], [[value, "private-token"] for value in retained])
        data = await self.result("redact_csv_columns", csv_text=content, columns_json='["token"]')
        rewritten = parsed(data["csv"])
        self.assertEqual([row[0] for row in rewritten[1:]], retained)
        self.assertEqual([row[1] for row in rewritten[1:]], ["[REDACTED]"] * len(retained))
        self.assertIn("\r\n", data["csv"])

    async def test_redact_tsv_empty_mask_and_quoted_multiline_mask(self):
        content = table(["id", "token"], [["001", "private"]], "\t")
        for mask in ("", 'a,\r\n"b"'):
            data = await self.result("redact_csv_columns", csv_text=content, columns_json='["token"]', delimiter="\t", mask=mask)
            self.assertEqual(parsed(data["csv"], "\t")[1], ["001", mask])

    async def test_redact_unknown_columns_and_duplicate_or_empty_selection_fail_closed(self):
        for selection in ('[]', '["missing"]', '["id","id"]', '["ID"]', '[1]', '{}'):
            text = await self.call("redact_csv_columns", csv_text="id\nprivate-value\n", columns_json=selection)
            self.assertTrue(text.startswith("Error:"))
            self.assertNotIn("private-value", text)

    async def test_redact_header_only_table_and_blank_records(self):
        data = await self.result("redact_csv_columns", csv_text="id,token\n\n", columns_json='["token"]')
        self.assertEqual(data["row_count"], 0)
        self.assertEqual(data["replacement_count"], 0)
        self.assertEqual(parsed(data["csv"]), [["id", "token"]])

    async def test_redact_case_sensitive_header_names_and_unselected_data_still_visible(self):
        data = await self.result("redact_csv_columns", csv_text="Token,token,secret\nupper-private,lower-private,unselected-private\n",
                                 columns_json='["token"]')
        self.assertNotIn("lower-private", json.dumps(data))
        self.assertIn("upper-private", data["csv"])
        self.assertIn("unselected-private", data["csv"])

    async def test_schema_real_worker_validates_patterns_required_and_min_length(self):
        schema = {"type": "object", "required": ["id", "code"], "additionalProperties": False,
                  "properties": {"id": {"type": "string", "pattern": "^[0-9]{3}$"}, "code": {"type": "string", "minLength": 1}}}
        data = await self.result("validate_csv_schema", csv_text="id,code\n001,ok\n1,\n", schema_json=json.dumps(schema),
                                 required_columns_json='["id","code"]')
        self.assertFalse(data["valid"])
        self.assertEqual(data["validated_row_count"], 2)
        self.assertEqual(data["valid_row_count"], 1)
        self.assertEqual(data["invalid_rows"], [2])
        self.assertEqual({row["keyword"] for row in data["errors"]}, {"pattern", "minLength"})
        self.assertEqual({row["path"] for row in data["errors"]}, {"/id", "/code"})

    async def test_schema_cells_remain_strings_numbers_booleans_and_empty_not_coerced(self):
        headers, rows = service._read("id,count,flag,empty\n001,12,true,\n", ",")
        schema = {"properties": {"id": {"const": "001"}, "count": {"type": "integer"}, "flag": {"type": "boolean"}, "empty": {"type": "null"}}}
        data = service._validate_rows(headers, rows, schema, [], 20)
        self.assertEqual(data["invalid_row_count"], 1)
        self.assertEqual({error["path"] for error in data["errors"]}, {"/count", "/flag", "/empty"})

    async def test_schema_explicit_required_headers_checked_on_zero_rows(self):
        data = await self.result("validate_csv_schema", csv_text="id\n", schema_json='{"required":["id","missing"]}',
                                 required_columns_json='["id","missing"]')
        self.assertFalse(data["valid"])
        self.assertEqual(data["header_check"]["missing_columns"], ["missing"])
        self.assertEqual(data["validated_row_count"], 0)
        self.assertEqual(data["invalid_row_count"], 0)
        vacuous = service._validate_rows(["id"], [], {"required": ["missing"]}, [], 20)
        self.assertTrue(vacuous["valid"])

    async def test_schema_local_refs_formats_and_unknown_formats(self):
        schema = {"$defs": {"email": {"type": "string", "format": "email"}},
                  "properties": {"email": {"$ref": "#/$defs/email"}, "other": {"format": "unknown-format"}}}
        data = await self.result("validate_csv_schema", csv_text="email,other\nnot-an-email,private-value\n", schema_json=json.dumps(schema))
        self.assertEqual(data["reported_error_count"], 1)
        self.assertEqual(data["errors"][0]["keyword"], "format")
        self.assertNotIn("not-an-email", json.dumps(data))
        self.assertNotIn("private-value", json.dumps(data))

    async def test_schema_known_drafts_and_boolean_schemas(self):
        headers, rows = service._read("id\n001\n", ",")
        for schema in (True, {"$schema": "http://json-schema.org/draft-07/schema#", "properties": {"id": {"type": "string"}}},
                       {"$schema": "https://json-schema.org/draft/2020-12/schema", "properties": {"id": {"const": "001"}}}):
            self.assertTrue(service._validate_rows(headers, rows, schema, [], 20)["valid"])
        data = service._validate_rows(headers, rows, False, [], 20)
        self.assertFalse(data["valid"])
        self.assertEqual(data["errors"][0]["keyword"], "false_schema")

    async def test_schema_required_empty_property_and_additional_properties(self):
        headers, rows = service._read("id,extra\n,private-extra\n", ",")
        schema = {"required": ["id", "absent"], "properties": {"id": {"minLength": 1}}, "additionalProperties": False}
        data = service._validate_rows(headers, rows, schema, [], 20)
        self.assertEqual({error["keyword"] for error in data["errors"]}, {"required", "minLength", "additionalProperties"})
        self.assertNotIn("private-extra", json.dumps(data))

    async def test_schema_pointer_escaping_and_no_literal_error_messages(self):
        headers, rows = service._read('"a/b~c"\nprivate-value\n', ",")
        data = service._validate_rows(headers, rows, {"properties": {"a/b~c": {"enum": ["private-allowed"]}}}, [], 20)
        self.assertEqual(data["errors"][0]["path"], "/a~1b~0c")
        self.assertEqual(data["errors"][0]["schema_path"], "/properties/a~1b~0c/enum")
        for value in ("private-value", "private-allowed"):
            self.assertNotIn(value, json.dumps(data))
        self.assertNotIn("message", data["errors"][0])

    async def test_schema_all_rows_classified_after_error_and_output_caps(self):
        headers = ["id", "value"]
        rows = [[str(index), "bad"] for index in range(1000)]
        rows[-1][1] = "good"
        data = service._validate_rows(headers, rows, {"properties": {"value": {"const": "good"}}}, [], 1)
        self.assertEqual(data["validated_row_count"], 1000)
        self.assertEqual(data["invalid_row_count"], 999)
        self.assertEqual(data["valid_row_count"], 1)
        self.assertEqual(data["reported_error_count"], 50)
        self.assertEqual(len(data["errors"]), 1)
        self.assertTrue(data["errors_capped"])
        self.assertTrue(data["truncated"])
        exactly = service._validate_rows(headers, rows[:50], {"properties": {"value": {"const": "good"}}}, [], 50)
        self.assertFalse(exactly["errors_capped"])

    async def test_schema_invalid_or_unsupported_schema_and_remote_references_sanitized(self):
        for schema in ('{"type":"private-unknown-type"}', '{"$schema":"https://private.example/schema"}',
                       '{"properties":{"id":{"pattern":"[private-pattern"}}}',
                       '{"$ref":"https://private.example/schema"}', '{"$ref":"file:///private-file"}',
                       '{"$ref":"#/private-missing"}'):
            text = await self.call("validate_csv_schema", csv_text="id\nprivate-cell\n", schema_json=schema)
            self.assertTrue(text.startswith("Error: CSV schema validation failed"), text)
            self.assertNotIn("private-", text)
            self.assertNotIn("private.example", text)

    async def test_schema_pathological_regex_real_worker_is_stopped(self):
        text = await self.call("validate_csv_schema", csv_text="id\n" + "a" * 80 + "!\n",
                               schema_json='{"properties":{"id":{"pattern":"^(a+)+$"}}}')
        self.assertTrue(text.startswith("Error:"))
        self.assertTrue("five-second" in text or "worker exited" in text, text)
        self.assertTrue(service._VALIDATION_SLOT.acquire(blocking=False))
        service._VALIDATION_SLOT.release()

    async def test_schema_worker_busy_and_context_failure_release_slot(self):
        service._VALIDATION_SLOT.acquire()
        try:
            with self.assertRaisesRegex(ValueError, "busy"):
                service.validate("id\n1\n", "{}", "[]", ",", 1)
        finally:
            service._VALIDATION_SLOT.release()
        with patch.object(service.multiprocessing, "get_context", side_effect=OSError("private-failure")):
            with self.assertRaisesRegex(ValueError, "could not start") as error:
                service.validate("id\n1\n", "{}", "[]", ",", 1)
        self.assertNotIn("private-failure", str(error.exception))
        self.assertTrue(service._VALIDATION_SLOT.acquire(blocking=False))
        service._VALIDATION_SLOT.release()

    async def test_schema_worker_timeout_terminates_kills_and_closes(self):
        receiver, sender, process, context = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        receiver.poll.return_value = False
        process.pid = 1
        process.is_alive.side_effect = [True, True]
        context.Pipe.return_value = receiver, sender
        context.Process.return_value = process
        with patch.object(service.multiprocessing, "get_context", return_value=context):
            with self.assertRaisesRegex(ValueError, "five-second"):
                service.validate("id\n1\n", "{}", "[]", ",", 1)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        receiver.close.assert_called_once()
        process.close.assert_called_once()
        self.assertTrue(service._VALIDATION_SLOT.acquire(blocking=False))
        service._VALIDATION_SLOT.release()

    async def test_schema_worker_start_and_eof_failures_are_sanitized(self):
        for phase in ("start", "recv"):
            receiver, sender, process, context = MagicMock(), MagicMock(), MagicMock(), MagicMock()
            context.Pipe.return_value = receiver, sender
            context.Process.return_value = process
            process.pid = None
            if phase == "start":
                process.start.side_effect = OSError("private-start")
            else:
                receiver.recv.side_effect = EOFError("private-eof")
            with patch.object(service.multiprocessing, "get_context", return_value=context):
                with self.assertRaisesRegex(ValueError, "worker exited") as error:
                    service.validate("id\n1\n", "{}", "[]", ",", 1)
            self.assertNotIn("private-", str(error.exception))
            process.close.assert_called_once()

    async def test_schema_worker_unexpected_errors_and_output_caps(self):
        sender = MagicMock()
        with patch.object(service, "_resource_limits"), patch.object(service, "_validate_rows", side_effect=ValueError("private-literal")):
            service._validation_worker(sender, ["id"], [["private-cell"]], {}, [], 1)
        self.assertNotIn("private-", json.dumps(sender.send.call_args.args[0]))
        sender.close.assert_called_once()
        sender = MagicMock()
        with patch.object(service, "_resource_limits"), patch.object(service, "_validate_rows", return_value={"large": "x" * 100001}):
            service._validation_worker(sender, ["id"], [], {}, [], 1)
        self.assertIn("100000", sender.send.call_args.args[0]["error"])

    async def test_all_tools_reject_ragged_duplicate_empty_or_malformed_headers(self):
        inputs = ("", "a,a\nx,y\n", "a,\nx,y\n", "a,b\nx\n", 'a,b\nx,"private-unfinished',
                  table(["x" * 201]), table(["a\nb"]), table(["a\0b"]), table([f"c{index}" for index in range(101)]))
        for content in inputs:
            for name, arguments in (("profile_csv", {"csv_text": content}),
                                    ("validate_csv_schema", {"csv_text": content, "schema_json": "{}"}),
                                    ("compare_csv_tables", {"before": content, "after": content, "key_columns_json": '["a"]'}),
                                    ("redact_csv_columns", {"csv_text": content, "columns_json": '["a"]'})):
                text = await self.call(name, **arguments)
                self.assertTrue(text.startswith("Error:"), (name, content[:30]))
                self.assertNotIn("private-unfinished", text)

    async def test_common_row_bounds_and_late_invalid_row_not_hidden_by_limit(self):
        content = "id\n" + "value\n" * 1000
        self.assertEqual(service.profile(content, ",", 1)["row_count"], 1000)
        for content in (content + "last\n", "id,value\n1,A\n2,private-bad,extra\n"):
            for function, arguments in ((service.profile, (content, ",", 1)),
                                        (service.compare, (content, content, '["id"]', ",", 1)),
                                        (service.redact, (content, '["id"]', ",", "mask")),
                                        (service.validate, (content, "{}", "[]", ",", 1))):
                with self.assertRaises(ValueError):
                    function(*arguments)

    async def test_input_delimiter_and_limit_types_and_sizes_before_worker(self):
        samples = ((service.profile, ("id\n1\n", ",", 1)),
                   (service.compare, ("id\n1\n", "id\n1\n", '["id"]', ",", 1)),
                   (service.redact, ("id\n1\n", '["id"]', ",", "mask")),
                   (service.validate, ("id\n1\n", "{}", "[]", ",", 1)))
        with patch.object(service, "_run_validation", side_effect=AssertionError("worker")):
            for function, arguments in samples:
                for value in (None, {}, "x" * 200001):
                    invalid = list(arguments)
                    invalid[0] = value
                    with self.assertRaises(ValueError):
                        function(*invalid)
                delimiter_position = 1 if function == service.profile else 2 if function == service.redact else 3
                for delimiter in (None, 1, "", "::", '"', "\r", "\n", "\0"):
                    invalid = list(arguments)
                    invalid[delimiter_position] = delimiter
                    with self.assertRaises(ValueError):
                        function(*invalid)
                if function != service.redact:
                    for limit in (True, 0, 51, 1.5, "1", None):
                        invalid = list(arguments)
                        invalid[-1] = limit
                        with self.assertRaises(ValueError):
                            function(*invalid)

    async def test_json_duplicate_nonfinite_depth_node_and_selection_bounds(self):
        invalid = ('{', '[NaN]', '[1e999]', '{"x":1,"x":2}', '[' * 52 + '0' + ']' * 52, '[' + ','.join('0' for _ in range(10001)) + ']')
        for value in invalid:
            with self.assertRaises(ValueError):
                service._json(value)
        for value in ('[]', '["id","id"]', '[1]', '[""]', '["a\\nb"]', '{}', json.dumps([f"c{index}" for index in range(101)]),
                      json.dumps(["x" * 201])):
            with self.assertRaises(ValueError):
                service._columns(value)

    async def test_schema_and_compare_second_input_checked_and_no_worker_for_bad_json(self):
        with patch.object(service, "_run_validation", side_effect=AssertionError("worker")):
            for value in (None, {}, "x" * 200001, "[]", '"private-value"', "NaN"):
                with self.assertRaises(ValueError):
                    service.validate("id\n1\n", value, "[]", ",", 1)
            for value in (None, {}, "x" * 200001):
                with self.assertRaises(ValueError):
                    service.compare("id\n1\n", value, '["id"]', ",", 1)
            for selection in ('["missing"]', '["ID"]'):
                with self.assertRaisesRegex(ValueError, "exist"):
                    service.compare("id\n1\n", "id\n1\n", selection, ",", 1)

    async def test_redact_mask_bounds_and_output_never_partial(self):
        for mask in (None, 1, "x" * 201, "bad\0mask"):
            with self.assertRaises(ValueError):
                service.redact("id\n1\n", '["id"]', ",", mask)
        text = await self.call("redact_csv_columns", csv_text="id\n" + "1\n" * 1000, columns_json='["id"]', mask="x" * 200)
        self.assertTrue(text.startswith("Error: Redacted CSV exceeds"))
        self.assertNotIn('"csv"', text)

    async def test_real_comparison_output_cap_and_smaller_limit_recovery(self):
        old = table(["id", "one", "two", "three"], [[str(index)] + ["a" * 600] * 3 for index in range(60)])
        new = table(["id", "one", "two", "three"], [[str(index)] + ["b" * 600] * 3 for index in range(60)])
        self.assertLess(len(old), 200000)
        text = await self.call("compare_csv_tables", before=old, after=new, key_columns_json='["id"]', limit=50)
        self.assertTrue(text.startswith("Error: CSV output exceeds 100000"))
        data = await self.result("compare_csv_tables", before=old, after=new, key_columns_json='["id"]', limit=1)
        self.assertEqual(data["changed_cell_count"], 180)
        self.assertTrue(data["truncated"])

    async def test_json_envelope_output_limit_and_redaction_cannot_truncate(self):
        for name, target, arguments in (("profile_csv", "profile", {"csv_text": "id\n1"}),
                                        ("validate_csv_schema", "validate", {"csv_text": "id\n1", "schema_json": "{}"}),
                                        ("redact_csv_columns", "redact", {"csv_text": "id\n1", "columns_json": '["id"]'})):
            with patch.object(service, target, return_value={"large": "x" * 100001}):
                self.assertTrue((await self.call(name, **arguments)).startswith("Error: CSV output exceeds"))
        content = table(["id", "token"], [["\"" * 500, "private"]] * 60)
        text = await self.call("redact_csv_columns", csv_text=content, columns_json='["token"]')
        self.assertTrue(text.startswith("Error: CSV output exceeds 100000"), text[:100])

    async def test_no_file_network_dns_commands_or_schema_resource_fetch(self):
        content = table(["id", "value"], [["1", "https://127.0.0.1/private"]])
        with patch("builtins.open", side_effect=AssertionError("file")), patch("socket.getaddrinfo", side_effect=AssertionError("DNS")), \
                patch("requests.get", side_effect=AssertionError("network")), patch("urllib.request.urlopen", side_effect=AssertionError("network")), \
                patch("subprocess.run", side_effect=AssertionError("command")), patch("os.system", side_effect=AssertionError("command")):
            self.assertEqual(service.profile(content, ",", 1)["row_count"], 1)
            self.assertTrue(service.compare(content, content, '["id"]', ",", 1)["equal"])
            self.assertEqual(service.redact(content, '["value"]', ",", "mask")["replacement_count"], 1)
            self.assertTrue(service._validate_rows(["id", "value"], [["1", "literal"]], {}, [], 1)["valid"])
            for schema in ({"$ref": "https://127.0.0.1/schema"}, {"$ref": "file:///private-file"}):
                with self.assertRaises(Exception) as error:
                    service._validate_rows(["id"], [["1"]], schema, [], 1)
                self.assertNotIsInstance(error.exception, AssertionError)

    async def test_extracted_csv_parser_preserves_existing_converter_behavior(self):
        legacy = FastMCP("legacy-csv-tests")
        csv_tools.register(legacy)
        content = '\ufeffid,note\r\n001,"one\r\ntwo"\r\n\r\n002,"comma,quote\"\""\r\n'
        headers, rows = csv_service.read_csv(content, ",")
        self.assertEqual(headers, ["id", "note"])
        self.assertEqual(rows, [["001", "one\r\ntwo"], ["002", 'comma,quote"']])
        result = await legacy.call_tool("csv_to_json", {"csv_text": content})
        blocks = result[0] if isinstance(result, tuple) else result
        output = '\n'.join(item.text for item in blocks if item.type == "text")
        self.assertEqual(json.loads(output), [dict(zip(headers, row)) for row in rows])
        legacy_header = table(["long" * 100], [["value"]])
        self.assertEqual(csv_service.read_csv(legacy_header, ",")[0], ["long" * 100])

    async def test_shared_json_schema_factory_keeps_existing_validation_semantics(self):
        validator = schemas._make_validator({"type": "object", "properties": {"count": {"type": "integer"}}})
        self.assertTrue(validator.is_valid({"count": 2}))
        self.assertFalse(validator.is_valid({"count": "2"}))
        self.assertTrue(schemas._make_validator(True).is_valid(None))
        self.assertFalse(schemas._make_validator(False).is_valid(None))


if __name__ == "__main__":
    unittest.main()
