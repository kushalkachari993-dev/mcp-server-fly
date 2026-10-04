from app.tools.report_utils.tool import _run

from . import service


def register(mcp):
    @mcp.tool()
    async def inspect_openapi_document(content: str, limit: int = 20) -> str:
        """Inspect supplied OpenAPI 3.0/3.1 JSON or YAML offline. List selected
        operations, parameters, request/response media and statuses, security
        declarations and local/external reference counts. This is not full
        OpenAPI validation. No remote refs, requests or files are accessed.
        Input at most 200000 chars, 500 operations; limit 1-50.
        """
        return await _run(service.inspect_openapi_document, content, limit)

    @mcp.tool()
    async def compare_openapi_contracts(before: str, after: str, limit: int = 20) -> str:
        """Compare selected declarations in two supplied OpenAPI 3.0/3.1
        documents offline: endpoints, parameters, request/response media and
        statuses, shallow schema shapes and security. Unresolved references
        and unselected constraints prevent a complete compatibility verdict.
        Each input at most 200000 chars, 500 operations; limit 1-50.
        """
        return await _run(service.compare_openapi_contracts, before, after, limit)

    @mcp.tool()
    async def compare_postman_collections(before: str, after: str, limit: int = 20) -> str:
        """Compare selected Postman Collection v2.1 declarations offline by
        exact folder ancestry and item name: methods, sanitized HTTP targets,
        and declared/effective auth types. Duplicate/missing identities are
        not guessed. Credentials, query, bodies, scripts and variables omitted.
        Each input at most 200000 chars, 1000 items; limit 1-50.
        """
        return await _run(service.compare_postman_collections, before, after, limit)

    @mcp.tool()
    async def validate_openapi_json_body(spec: str, path: str, method: str,
                                         direction: str, body: str, status: str = "200",
                                         media_type: str = "application/json", limit: int = 20) -> str:
        """Validate a supplied JSON request/response body against one exact
        OpenAPI 3.1 operation and JSON media type using JSON Schema 2020-12.
        Supports only local component-schema refs; rejects custom dialects,
        dynamic refs and readOnly/writeOnly semantics. Error values are omitted.
        Offline, three-second validation worker. Inputs at most 200000 chars;
        limit 1-50. status selects a response (default 200).
        """
        return await _run(service.validate_openapi_json_body, spec, path, method,
                          direction, body, status, media_type, limit)
