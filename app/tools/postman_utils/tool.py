from app.tools.report_utils.tool import _run

from . import service


def register(mcp):
    @mcp.tool()
    async def inspect_postman_collection(content: str, limit: int = 20) -> str:
        """Inspect supplied Postman Collection v2.1 JSON: folder/request names,
        method counts, sanitized HTTP targets and declared/inherited auth types.
        Partial selected-field inspection, not complete schema validation or proof
        of runtime auth. Variables/templates are not resolved; scripts/requests
        never executed. Auth values, headers, bodies, examples and scripts omitted;
        names/hosts/paths may remain sensitive. Input 200000 chars, 20000 JSON nodes,
        depth 50, 1000 total items, URL 10000 chars; limit 1-50/output 100000 chars.
        """
        return await _run(service.inspect_collection, content, limit)
