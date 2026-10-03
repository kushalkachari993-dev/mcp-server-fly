from app.tools.report_utils.tool import _run

from . import service


def register(mcp):
    @mcp.tool()
    async def compare_sarif_reports(before: str, after: str, limit: int = 20) -> str:
        """Compare two supplied inline SARIF 2.1.0 reports by exact scanner,
        rule and bounded fingerprint identity. Report observed additions,
        removals and level/kind/suppression changes; missing or duplicate
        identities stay unresolved. No scanner execution or external properties.
        Each input: 200000 chars, 20000 JSON nodes, depth 50, 20 runs,
        2000 results; limit 1-50 per list, output 100000 chars. Offline only.
        """
        return await _run(service.compare_sarif, before, after, limit)

    @mcp.tool()
    async def compare_sboms(before: str, after: str, limit: int = 20) -> str:
        """Compare supplied CycloneDX JSON 1.5/1.6/1.7 component inventories.
        Match unique Package URLs without version, or weaker exact declared
        coordinates when no PURL exists; duplicates and invalid PURLs remain
        unresolved. Report version declarations and license changes, not upgrade
        direction, vulnerability status or dependency-edge changes. Each input:
        200000 chars, 10000 nodes, depth 50, 1000 components/dependency entries,
        5000 edges; limit 1-50 per list, output 100000 chars. Offline only.
        """
        return await _run(service.compare_sboms, before, after, limit)

    @mcp.tool()
    async def compare_prometheus_metrics(before: str, after: str, limit: int = 20) -> str:
        """Compare two supplied Prometheus text snapshots by metric family,
        sample name and exact labels. Report observed series/type changes,
        gauge snapshot deltas and raw counter differences with reset uncertainty.
        No scraping, rate/quantile inference or full format validation. Each
        input: 200000 chars, 5000 lines/samples, 500 family blocks, 20 labels
        per sample; limit 1-50 per list, output 100000 chars. Offline only.
        """
        return await _run(service.compare_metrics, before, after, limit)

    @mcp.tool()
    async def compare_access_logs(before: str, after: str, format: str = "combined", limit: int = 20) -> str:
        """Compare two supplied Apache common/combined log windows by status
        and exact method/query-free path. Report observed request/error counts
        and error fractions, not traffic-normalized rates or causal regressions.
        Invalid entries stay counted; IPs/users/agents are omitted. Each input:
        200000 chars, 5000 lines, 10000 chars per line; limit 1-50 per list,
        output 100000 chars. No file/network access or live monitoring.
        """
        return await _run(service.compare_access, before, after, format, limit)
