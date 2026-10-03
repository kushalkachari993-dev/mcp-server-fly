from app.tools.report_utils.tool import _run

from . import service


def register(mcp):
    @mcp.tool()
    async def compare_coverage_reports(before: str, after: str, format: str = "lcov", limit: int = 20) -> str:
        """Compare two supplied reports in the same LCOV or Cobertura format.
        Reports observed coverage deltas, added/removed identities and line-number
        hit transitions. Exact paths are not resolved or remapped across revisions;
        repeated identities remain ambiguous. No execution/file/network access.
        Existing inspector format/record bounds apply to each input (200000 chars);
        limit 1-50 per returned list, output 100000 chars. Names may be sensitive.
        """
        return await _run(service.compare_coverage, before, after, format, limit)

    @mcp.tool()
    async def compare_junit_reports(before: str, after: str, limit: int = 20) -> str:
        """Compare common JUnit XML test outcomes and reported durations by
        exact suite ancestry, classname and name. Duplicate/missing identities and
        mixed outcome markers remain ambiguous, not guessed matches. No flaky-test
        or runtime regression inference, test execution, file/network access.
        Each input: 200000 chars, 10000 XML nodes, depth 50, 1000 suites, 2000 cases;
        DTDs/entities forbidden. Limit 1-50 per list; output 100000 chars.
        """
        return await _run(service.compare_junit, before, after, limit)

    @mcp.tool()
    async def compare_har_reports(before: str, after: str, limit: int = 20) -> str:
        """Compare supplied HAR 1.2 observations grouped by exact method and
        sanitized HTTP scheme/host/effective port/path. Queries intentionally merge;
        repeated requests are aggregates, not paired guesses. Credentials, headers,
        cookies/bodies omitted; hosts/paths may still be sensitive. No live requests
        or causal/statistical regression inference. Each input: 200000 chars,
        20000 JSON nodes, depth 50, 1000 entries; limit 1-50, output 100000 chars.
        """
        return await _run(service.compare_har, before, after, limit)

    @mcp.tool()
    async def compare_k6_summaries(before: str, after: str, limit: int = 20) -> str:
        """Compare supported flat legacy or machine-v1 k6 summary metrics and
        explicit threshold results. Numeric deltas require the same summary format,
        metric source/name/type and known contains dimension. No unit conversion,
        threshold evaluation, load execution or proof of comparable workloads.
        Each input: 200000 chars, 20000 JSON nodes, depth 50, 500 metrics/collection,
        1000 thresholds; limit 1-50 per list, output 100000 chars. No file/network.
        """
        return await _run(service.compare_k6, before, after, limit)
