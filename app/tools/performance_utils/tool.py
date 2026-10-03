from app.tools.report_utils.tool import _run

from . import service


def register(mcp):
    @mcp.tool()
    async def inspect_har(content: str, limit: int = 20) -> str:
        """Inspect supplied HAR 1.2 JSON: status errors, slow requests,
        HTTP/HTTPS hosts/query-free paths, timing stages and known response sizes.
        Credentials, headers, cookies, bodies, server-IP fields and comments omitted; other
        schemes have no target text. No file/network access. Bounds: 200000 chars,
        20000 JSON nodes, depth 50, 1000 entries, 200 pages; limit 1-50 rows per
        list, output 100000. Not live monitoring or full HAR validation.
        """
        return await _run(service.inspect_har, content, limit)

    @mcp.tool()
    async def inspect_k6_summary(content: str, limit: int = 20) -> str:
        """Inspect supplied flat legacy handleSummary or version 1.0.0
        machine-readable k6 JSON: metric values/percentiles/rates, explicit
        metric threshold statuses and individual check counts. No execution,
        threshold evaluation, group/scenario aggregation or file/network access.
        Setup data/options/script paths omitted. Bounds: 200000 chars, 20000
        JSON nodes, depth 50, 500 metrics/collection, 50 values/thresholds per
        metric, 1000 thresholds/checks, 200 legacy groups; limit 1-50 rows per
        list, output 100000. Grouped summaries/raw JSONL are unsupported.
        """
        return await _run(service.inspect_k6, content, limit)
