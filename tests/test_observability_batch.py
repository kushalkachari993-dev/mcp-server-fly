import json
import unittest
from unittest.mock import patch

import yaml
from mcp.server.fastmcp import FastMCP

from app.tools.observability_utils import logs, rules, tool, traces


def span(name="GET /health", span_number=1, trace_number=1, parent=None, kind=2,
         status=1, start="1000000000", end="1010000000", **fields):
    value = {"traceId": f"{trace_number:032x}", "spanId": f"{span_number:016x}",
             "name": name, "kind": kind, "startTimeUnixNano": start,
             "endTimeUnixNano": end, "status": {"code": status}, **fields}
    if parent is not None:
        value["parentSpanId"] = f"{parent:016x}"
    return value


def batch(spans, service="api", namespace="prod", **fields):
    attributes = []
    if service is not None:
        attributes.append({"key": "service.name", "value": {"stringValue": service}})
    if namespace is not None:
        attributes.append({"key": "service.namespace", "value": {"stringValue": namespace}})
    attributes.append({"key": "private", "value": {"stringValue": "ATTRIBUTE_SECRET"}})
    return json.dumps({"resourceSpans": [{"resource": {"attributes": attributes},
                                          "scopeSpans": [{"spans": spans}]}], **fields})


def line(event="auth_failed", level="error", **fields):
    return json.dumps({"event": event, "level": level, "message": "MESSAGE_SECRET",
                       "timestamp": "2026-01-01T00:00:00Z", **fields}) + "\n"


def rule_file(groups):
    return yaml.safe_dump({"groups": groups}, sort_keys=False)


def group(name="api", rules=None, **fields):
    return {"name": name, "rules": [{"alert": "HighLatency", "expr": "rate(errors_total[5m]) > 0.1"}]
            if rules is None else rules, **fields}


class ObservabilityBatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("observability-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def parsed(self, name, **arguments):
        return json.loads(await self.call(name, **arguments))

    async def test_registers_exactly_four_tools(self):
        self.assertEqual({item.name for item in await self.mcp.list_tools()}, {
            "inspect_otlp_traces", "compare_otlp_traces", "compare_jsonl_logs", "compare_prometheus_rule_files"})

    async def test_inspect_otlp_operations_statuses_parents_and_privacy(self):
        data = batch([span(events=[{"name": "EVENT_SECRET"}],
                           links=[{"traceId": "f" * 32, "spanId": "f" * 16}],
                           attributes=[{"key": "password", "value": {"stringValue": "SPAN_SECRET"}}]),
                      span("db.query", 2, parent=1, kind=3, status=2, end="1005000000",
                           statusMessage="STATUS_SECRET"),
                      span("GET /health", 3, parent=9, status=0, end=None)])
        output = await self.call("inspect_otlp_traces", content=data)
        result = json.loads(output)
        self.assertEqual(result["span_count"], 3)
        self.assertEqual(result["trace_count"], 1)
        self.assertEqual(result["operation_count"], 2)
        self.assertEqual(result["status_counts"], {"unset": 1, "ok": 1, "error": 1})
        self.assertEqual(result["root_span_count"], 1)
        self.assertEqual(result["linked_parent_count"], 1)
        self.assertEqual(result["missing_parent_count"], 1)
        self.assertEqual(result["missing_duration_count"], 1)
        self.assertEqual(result["event_count"], 1)
        self.assertEqual(result["link_count"], 1)
        operation = next(row for row in result["operations"] if row["identity"]["span_name"] == "GET /health")
        self.assertEqual(operation["span_count"], 2)
        self.assertEqual(operation["duration_ms"]["mean"], 10)
        self.assertEqual(operation["missing_duration_count"], 1)
        for secret in ("ATTRIBUTE_SECRET", "SPAN_SECRET", "EVENT_SECRET", "STATUS_SECRET", f"{1:032x}", f"{1:016x}"):
            self.assertNotIn(secret, output)

    async def test_inspect_otlp_duplicate_ids_and_missing_service_are_uncertain(self):
        content = batch([span(span_number=1), span(span_number=1), span(span_number=2, parent=1)], service=None)
        result = await self.parsed("inspect_otlp_traces", content=content)
        self.assertEqual(result["duplicate_span_identity_count"], 1)
        self.assertEqual(result["ambiguous_parent_count"], 1)
        self.assertEqual(result["unmatchable_service_span_count"], 3)
        self.assertEqual(result["operation_count"], 0)
        result = await self.parsed("compare_otlp_traces", before=content, after=content)
        self.assertEqual(result["matching"]["matched_count"], 0)
        self.assertEqual(result["before"]["unmatchable_service_span_count"], 3)

    async def test_otlp_self_parent_is_not_a_link(self):
        result = await self.parsed("inspect_otlp_traces", content=batch([span(parent=1)]))
        self.assertEqual(result["self_parent_count"], 1)
        self.assertEqual(result["linked_parent_count"], 0)

    async def test_otlp_comparison_groups_operations_not_trace_ids(self):
        before = batch([span(status=1, end="1010000000")])
        after = batch([span(status=2, end="1020000000", trace_number=2, span_number=7)])
        result = await self.parsed("compare_otlp_traces", before=before, after=after)
        self.assertEqual(result["matching"]["matched_count"], 1)
        self.assertEqual(result["changed_operation_count"], 1)
        self.assertEqual(result["observed_mean_duration_increase_count"], 1)
        row = result["changes"][0]
        self.assertEqual(row["duration_ms"]["mean"]["delta"], 10)
        self.assertEqual(row["error_fraction_of_explicit_statuses"]["delta"], 1)
        self.assertEqual(row["error_count"]["delta"], 1)

    async def test_otlp_missing_measurements_and_statuses_do_not_get_deltas(self):
        before = batch([span(status=0, end=None)])
        after = batch([span(status=2, end="1020000000")])
        result = await self.parsed("compare_otlp_traces", before=before, after=after)
        row = result["changes"][0]
        self.assertIsNone(row["duration_ms"]["mean"]["delta"])
        self.assertIsNone(row["error_fraction_of_explicit_statuses"]["delta"])
        self.assertEqual(result["observed_mean_duration_increase_count"], 0)

    async def test_otlp_counts_all_spans_before_display_limit(self):
        content = batch([span(f"op-{index}", index + 1) for index in range(70)])
        result = await self.parsed("inspect_otlp_traces", content=content, limit=1)
        self.assertEqual(result["span_count"], 70)
        self.assertEqual(result["operation_count"], 70)
        self.assertEqual(len(result["operations"]), 1)
        self.assertTrue(result["truncated"])
        compared = await self.parsed("compare_otlp_traces", before=content, after=content, limit=1)
        self.assertEqual(compared["matching"]["matched_count"], 70)
        self.assertEqual(compared["changed_operation_count"], 0)

    async def test_otlp_rejects_malformed_ids_enums_times_and_large_inputs(self):
        invalid_spans = (span(traceId="x" * 32), span(kind="SPAN_KIND_SERVER"), span(status="ERROR"),
                         span(start="10", end="9"), span(start="-1"), span(spanId="0" * 16))
        for item in invalid_spans:
            with self.subTest(item=item):
                self.assertTrue((await self.call("inspect_otlp_traces", content=batch([item]))).startswith("Error:"))
        for content in ('{"resourceSpans":"SOURCE_SECRET', "x" * 200001, "{}"):
            output = await self.call("inspect_otlp_traces", content=content)
            self.assertTrue(output.startswith("Error:"))
            self.assertNotIn("SOURCE_SECRET", output)
        self.assertTrue((await self.call("inspect_otlp_traces", content=batch([]), limit=0)).startswith("Error:"))

    async def test_jsonl_compares_levels_events_and_omits_messages(self):
        before = line("auth_failed", "warn") + line("db_timeout", "error") + "{SOURCE_SECRET\n"
        after = line("auth_failed", "critical") + line("db_timeout", "error") * 2
        output = await self.call("compare_jsonl_logs", before=before, after=after)
        result = json.loads(output)
        self.assertEqual(result["before"]["invalid_entries"], 1)
        self.assertEqual(result["before"]["level_counts"]["warning"], 1)
        self.assertEqual(result["matching"]["matched_count"], 2)
        self.assertEqual(result["changed_event_count"], 2)
        self.assertEqual(result["event_error_count_increase_count"], 2)
        self.assertEqual(result["error_count"]["delta"], 2)
        for secret in ("MESSAGE_SECRET", "SOURCE_SECRET"):
            self.assertNotIn(secret, output)

    async def test_jsonl_supports_explicit_numeric_codes_and_unmatchable_free_text(self):
        before = line(event=None, error_code=5001) + line(event="free text with PRIVATE_SECRET") + line(event=None)
        result = await self.parsed("compare_jsonl_logs", before=before, after=before, event_field="error_code")
        self.assertEqual(result["matching"]["matched_count"], 1)
        self.assertEqual(result["before"]["unmatchable_event_entry_count"], 2)
        self.assertEqual(result["matching"]["added_count"], 0)
        result = await self.parsed("compare_jsonl_logs", before=line(event="free text with PRIVATE_SECRET"),
                                   after=line(event="free text with PRIVATE_SECRET"))
        self.assertEqual(result["matching"]["matched_count"], 0)
        self.assertEqual(result["before"]["unmatchable_event_entry_count"], 1)

    async def test_jsonl_counts_all_events_before_display_limit(self):
        before = "".join(line(f"event_{index}", "info") for index in range(70))
        after = "".join(line(f"event_{index}", "error") for index in range(70))
        result = await self.parsed("compare_jsonl_logs", before=before, after=after, limit=1)
        self.assertEqual(result["matching"]["matched_count"], 70)
        self.assertEqual(result["changed_event_count"], 70)
        self.assertEqual(len(result["changes"]), 1)
        self.assertTrue(result["truncated"])

    async def test_jsonl_bad_field_and_input_limits(self):
        value = line()
        for options in ({"event_field": ""}, {"event_field": "x" * 101}, {"level_field": "\n"}, {"limit": 0}):
            self.assertTrue((await self.call("compare_jsonl_logs", before=value, after=value, **options)).startswith("Error:"))
        self.assertTrue((await self.call("compare_jsonl_logs", before="x" * 200001, after=value)).startswith("Error:"))

    async def test_rule_file_changes_selected_fields_without_values(self):
        old = group(interval="30s", limit=10, query_offset="1m", labels={"team": "old-team"},
                    rules=[{"alert": "HighLatency", "expr": "SECRET_EXPR_OLD", "for": "5m",
                            "labels": {"severity": "PRIVATE_OLD"},
                            "annotations": {"summary": "SECRET_ANNOTATION_OLD"}}])
        new = group(interval="1m", limit=20, query_offset="2m", labels={"team": "new-team"},
                    rules=[{"alert": "HighLatency", "expr": "SECRET_EXPR_NEW", "for": "10m",
                            "labels": {"severity": "PRIVATE_NEW"},
                            "annotations": {"summary": "SECRET_ANNOTATION_NEW"}}])
        output = await self.call("compare_prometheus_rule_files", before=rule_file([old]), after=rule_file([new]))
        result = json.loads(output)
        self.assertFalse(result["selected_fields_equal"])
        self.assertEqual(result["group_matching"]["matched_count"], 1)
        self.assertEqual(result["rule_matching"]["matched_count"], 1)
        self.assertEqual(result["changed_group_count"], 1)
        self.assertEqual(result["changed_rule_count"], 1)
        self.assertEqual(result["group_changes"][0]["changed_label_keys"], ["team"])
        self.assertEqual(result["rule_changes"][0]["changed_annotation_keys"], ["summary"])
        self.assertEqual(set(result["rule_changes"][0]["changed_fields"]), {"expr", "for", "labels", "annotations"})
        for secret in ("SECRET_EXPR_OLD", "SECRET_EXPR_NEW", "PRIVATE_OLD", "PRIVATE_NEW",
                       "SECRET_ANNOTATION_OLD", "SECRET_ANNOTATION_NEW", "old-team", "new-team"):
            self.assertNotIn(secret, output)

    async def test_rules_recording_rule_order_and_added_removed(self):
        old = group(rules=[{"record": "request:rate", "expr": "sum(rate(requests_total[5m]))"},
                           {"alert": "Down", "expr": "up == 0"}])
        new = group(rules=[{"alert": "Down", "expr": "up == 0"},
                           {"record": "request:rate", "expr": "sum(rate(requests_total[5m]))"}])
        result = await self.parsed("compare_prometheus_rule_files", before=rule_file([old]), after=rule_file([new]))
        self.assertEqual(result["before"]["recording_rule_count"], 1)
        self.assertEqual(result["changed_rule_count"], 2)
        self.assertEqual(result["rule_changes"][0]["changed_fields"], ["position"])
        added = await self.parsed("compare_prometheus_rule_files", before=rule_file([old]),
                                  after=rule_file([group("other", rules=new["rules"]) ]))
        self.assertEqual(added["rule_matching"]["matched_count"], 0)
        self.assertEqual(added["rule_matching"]["added_count"], 2)
        self.assertEqual(added["rule_matching"]["removed_count"], 2)

    async def test_rules_duplicate_identities_are_ambiguous_and_unknown_fields_counted(self):
        duplicate = rule_file([group(), group()])
        result = await self.parsed("compare_prometheus_rule_files", before=duplicate, after=duplicate)
        self.assertIsNone(result["selected_fields_equal"])
        self.assertEqual(result["group_matching"]["ambiguous_count"], 1)
        self.assertEqual(result["rule_matching"]["ambiguous_count"], 1)
        old = rule_file([group(custom="one")])
        new = rule_file([group(custom="two")])
        result = await self.parsed("compare_prometheus_rule_files", before=old, after=new)
        self.assertTrue(result["selected_fields_equal"])
        self.assertEqual(result["before"]["ignored_group_field_count"], 1)

    async def test_rules_counts_all_rules_before_display_limit(self):
        old = rule_file([group(rules=[{"alert": f"Alert{index}", "expr": "up == 0"} for index in range(70)])])
        new = rule_file([group(rules=[{"alert": f"Alert{index}", "expr": "up == 1"} for index in range(70)])])
        result = await self.parsed("compare_prometheus_rule_files", before=old, after=new, limit=1)
        self.assertEqual(result["rule_matching"]["matched_count"], 70)
        self.assertEqual(result["changed_rule_count"], 70)
        self.assertEqual(len(result["rule_changes"]), 1)
        self.assertTrue(result["truncated"])

    async def test_rules_reject_invalid_yaml_shapes_and_bounds_without_source(self):
        cases = ('groups: [\nSECRET_SOURCE',
                 'groups:\n- name: a\n  name: SECRET_SOURCE\n  rules: []\n',
                 rule_file([group(rules=[{"alert": "A"}])]),
                 rule_file([group(rules=[{"alert": "A", "record": "B", "expr": "up"}])]),
                 rule_file([group(labels={"secret": None})]),
                 rule_file([group(str(index)) for index in range(101)]))
        for content in cases:
            with self.subTest(content=content[:60]):
                output = await self.call("compare_prometheus_rule_files", before=content, after=content)
                self.assertTrue(output.startswith("Error:"))
                self.assertNotIn("SECRET_SOURCE", output)
        good = rule_file([group()])
        self.assertTrue((await self.call("compare_prometheus_rule_files", before=good, after=good, limit=0)).startswith("Error:"))

    async def test_offline_services_do_not_open_files_or_use_network_or_commands(self):
        content = batch([span()])
        rules_yaml = rule_file([group()])
        with patch("builtins.open", side_effect=AssertionError("Unexpected file access")), \
                patch("socket.create_connection", side_effect=AssertionError("Unexpected network access")), \
                patch("subprocess.run", side_effect=AssertionError("Unexpected execution")):
            self.assertEqual(traces.inspect_otlp_traces(content, 20)["span_count"], 1)
            self.assertEqual(traces.compare_otlp_traces(content, content, 20)["matching"]["matched_count"], 1)
            self.assertEqual(logs.compare_jsonl_logs(line(), line(), "level", "event", "timestamp", 20)["matching"]["matched_count"], 1)
            self.assertTrue(rules.compare_prometheus_rule_files(rules_yaml, rules_yaml, 20)["selected_fields_equal"])


if __name__ == "__main__":
    unittest.main()
