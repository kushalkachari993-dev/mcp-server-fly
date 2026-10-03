from app.tools.report_utils.tool import _run

from . import service


def register(mcp):
    @mcp.tool()
    async def inspect_lcov_report(content: str, limit: int = 20) -> str:
        """Inspect supplied LCOV text: observed/declared line, function and
        branch coverage, uncovered lines, grouped aliases and mismatches. Sections
        stay separate; repeated files are not merged. Not test execution/full
        validation; no file/network access. Bounds: 200000 chars, 5000 lines,
        10000 chars/line, 200 sections; limit 1-50 rows per list, output 100000.
        """
        return await _run(service.inspect_lcov, content, limit)

    @mcp.tool()
    async def inspect_cobertura_report(content: str, limit: int = 20) -> str:
        """Inspect supplied Cobertura XML: declared rates/counts, observed
        class lines/branches, uncovered lines and least-covered classes. Method
        line copies are not counted twice; repeated filenames are not merged.
        No execution/file/network access; entities forbidden, DTDs not loaded.
        Bounds: 200000 chars, 10000 XML elements, depth 50, 200 packages, 1000
        classes, 5000 class lines; limit 1-50 rows per list, output 100000.
        """
        return await _run(service.inspect_cobertura, content, limit)
