import json

import anyio

from . import service


async def _run(function, *arguments):
    try:
        result = await anyio.to_thread.run_sync(function, *arguments)
        output = json.dumps(result, indent=2, allow_nan=False)
        if len(output) > 100000:
            raise ValueError("Report summary exceeds 100000 characters; reduce input/limit")
        return output
    except (ValueError, RecursionError) as error:
        return f"Error: {error}"


def register(mcp):
    @mcp.tool()
    async def inspect_junit_report(content: str, limit: int = 20) -> str:
        """Inspect supplied common JUnit XML suites/testcases, failed/skipped
        tests and slowest reported durations. Counts observed cases once; suite
        aggregate declarations stay separate. No test execution or full schema
        validation. DTDs/entities forbidden; no file/network access. Failure bodies,
        stdout/stderr and properties omitted. Bounds: 200000 chars, 10000 XML
        elements, depth 50, 1000 suites, 2000 cases, limit 1-50; output 100000 chars.
        """
        return await _run(service.inspect_junit, content, limit)

    @mcp.tool()
    async def inspect_sarif_report(content: str, limit: int = 20) -> str:
        """Summarize supplied inline SARIF 2.1.0 scanner results, rule IDs,
        explicit levels, locations and suppression requests. Does not validate
        findings or resolve rule defaults, URI bases, extensions or external
        properties. No execution/file/network access. Bounds: 200000 chars,
        20000 JSON nodes, depth 50, 20 runs, 2000 results; limit 1-50; output 100000.
        """
        return await _run(service.inspect_sarif, content, limit)

    @mcp.tool()
    async def inspect_prometheus_metrics(content: str, limit: int = 20) -> str:
        """Inspect one supplied Prometheus text snapshot: family types, labels
        and sample values. Uses the official permissive parser, not full format
        validation. No scraping/rates/trends or quantile inference. Counter names
        may be normalized; NaN/Inf are JSON strings. Bounds: 200000 chars, 5000
        lines/samples, 10000 chars per line, 500 family blocks, 20 labels/sample,
        limit 1-50 families and samples per family; output 100000 chars.
        """
        return await _run(service.inspect_metrics, content, limit)

    @mcp.tool()
    async def analyze_access_logs(content: str, format: str = "combined", limit: int = 20) -> str:
        """Summarize supplied Apache common/combined logs: status counts,
        client/server errors, query-free paths and reported bytes. IPs/users,
        referrers and user agents omitted. No custom formats, live monitoring,
        latency inference or file/network access. Bounds: 200000 chars, 5000
        lines, 10000 chars/line, limit 1-50 path/method/error rows, output 100000.
        """
        return await _run(service.analyze_access, content, format, limit)
