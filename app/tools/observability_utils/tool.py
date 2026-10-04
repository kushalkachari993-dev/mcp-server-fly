from app.tools.report_utils.tool import _run

from . import logs, rules, traces


def register(mcp):
    @mcp.tool()
    async def inspect_otlp_traces(content: str, limit: int = 20) -> str:
        """Inspect a supplied OTLP/JSON ExportTraceServiceRequest offline. Summarize
        service/span operations, observed durations/statuses and parent links;
        omit IDs, attributes, events and messages. Not full OTLP validation.
        Bounds: 200000 chars, 20000 JSON nodes, depth 50, 100 resourceSpans,
        500 scopeSpans, 2000 spans, limit 1-50 rows, output 100000 chars.
        """
        return await _run(traces.inspect_otlp_traces, content, limit)

    @mcp.tool()
    async def compare_otlp_traces(before: str, after: str, limit: int = 20) -> str:
        """Compare two supplied OTLP/JSON trace batches by exact service
        namespace/name, span name and kind. Compare grouped counts, explicit
        status fractions and fully measured duration samples, never trace IDs.
        No traffic normalization or causal regression verdict. Each input:
        200000 chars, 20000 JSON nodes, depth 50, 2000 spans; limit 1-50
        rows per list, output 100000 chars. Offline only.
        """
        return await _run(traces.compare_otlp_traces, before, after, limit)

    @mcp.tool()
    async def compare_jsonl_logs(before: str, after: str, level_field: str = "level",
                                 event_field: str = "event", timestamp_field: str = "timestamp",
                                 limit: int = 20) -> str:
        """Compare supplied JSON-object log windows by level and exact top-level
        event/error-code identifiers. Unselected message text and other fields are omitted;
        missing/free-text events remain unmatchable. No rate or causal inference.
        Each input: 200000 chars, 5000 lines, 1000 JSON nodes/line, depth 20;
        limit 1-50 rows per list, output 100000 chars. Offline only.
        """
        return await _run(logs.compare_jsonl_logs, before, after, level_field,
                          event_field, timestamp_field, limit)

    @mcp.tool()
    async def compare_prometheus_rule_files(before: str, after: str, limit: int = 20) -> str:
        """Compare selected declarations in two supplied Prometheus alerting/
        recording rule YAML files by group and rule identity. Report expression,
        timing, label, annotation and order changes without returning their
        values or evaluating PromQL. Not promtool validation. Each input:
        200000 chars, 10000 YAML nodes, depth 50, 100 groups, 1000 rules;
        limit 1-50 rows per list, output 100000 chars. Offline only.
        """
        return await _run(rules.compare_prometheus_rule_files, before, after, limit)
