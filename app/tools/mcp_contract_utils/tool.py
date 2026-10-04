from app.tools.report_utils.tool import _run

from . import catalogs, runtime, service


def register(mcp):
    @mcp.tool()
    async def inspect_mcp_tool_manifest(manifest: str, protocol_version: str = "2025-11-25", limit: int = 20) -> str:
        """Inspect a supplied tools/list JSON response or result, including
        names, argument counts, schema presence and untrusted annotation hints.
        A nextCursor marks a partial page. No live connection, schema validation
        or value echo. Input at most 200000 chars, 20000 nodes, 500 tools;
        limit 1-50. Supports 2025-11-25 and 2026-07-28.
        """
        return await _run(service.inspect_mcp_tool_manifest, manifest, protocol_version, limit)

    @mcp.tool()
    async def compare_mcp_tool_manifests(before: str, after: str,
                                         protocol_version: str = "2025-11-25", limit: int = 20) -> str:
        """Compare complete supplied tools/list snapshots by exact tool name.
        Flag tool, schema and selected metadata changes, with shallow property
        and required-argument details. No compatibility verdict or server calls.
        Paginated partial lists are rejected. Each input at most 200000 chars;
        limit 1-50. Supports 2025-11-25 and 2026-07-28.
        """
        return await _run(service.compare_mcp_tool_manifests, before, after, protocol_version, limit)

    @mcp.tool()
    async def validate_mcp_tool_arguments(manifest: str, tool_name: str, arguments: str,
                                          protocol_version: str = "2025-11-25", limit: int = 20) -> str:
        """Validate supplied JSON arguments against one tool inputSchema,
        without invoking it. JSON Schema 2020-12/default or Draft 7 with local
        refs only; errors omit values. Offline three-second worker. Each JSON
        input at most 200000 chars and 20000 nodes; limit 1-50.
        """
        return await _run(service.validate_mcp_tool_arguments, manifest, tool_name, arguments, protocol_version, limit)

    @mcp.tool()
    async def validate_mcp_tool_result(manifest: str, tool_name: str, result: str,
                                       protocol_version: str = "2025-11-25", limit: int = 20) -> str:
        """Validate supplied structuredContent against one tool outputSchema.
        Error/input-required results and absent outputSchema are reported as
        unchecked; no full envelope validation. 2025-11-25 requires an object,
        2026-07-28 permits any JSON value. Offline three-second worker; inputs
        at most 200000 chars; errors omit values; limit 1-50.
        """
        return await _run(service.validate_mcp_tool_result, manifest, tool_name, result, protocol_version, limit)

    @mcp.tool()
    async def inspect_mcp_resource_manifest(resources: str, templates: str = "",
                                            protocol_version: str = "2025-11-25", limit: int = 20) -> str:
        """Inspect supplied resources/list and optional resources/templates/list
        JSON responses. Summarize names, query-free URIs, MIME types and sizes;
        mark nextCursor as partial. No resource reads or network access. Each
        input at most 200000 chars, 20000 nodes, 500 entries; limit 1-50.
        Supports 2025-11-25 and 2026-07-28.
        """
        return await _run(catalogs.inspect_mcp_resource_manifest, resources, templates, protocol_version, limit)

    @mcp.tool()
    async def compare_mcp_resource_manifests(before_resources: str, after_resources: str,
                                             before_templates: str = "", after_templates: str = "",
                                             protocol_version: str = "2025-11-25", limit: int = 20) -> str:
        """Compare complete supplied MCP resource and optional template lists
        by full URI identity. Flag presence, MIME, size and selected metadata
        changes without reading content or claiming compatibility. Supply both
        template lists or neither; nextCursor pages are rejected. Each input at
        most 200000 chars; limit 1-50. Supports 2025-11-25 and 2026-07-28.
        """
        return await _run(catalogs.compare_mcp_resource_manifests, before_resources, after_resources,
                          before_templates, after_templates, protocol_version, limit)

    @mcp.tool()
    async def inspect_mcp_prompt_manifest(manifest: str, protocol_version: str = "2025-11-25",
                                          limit: int = 20) -> str:
        """Inspect supplied prompts/list JSON names and required argument
        declarations. Descriptions and prompt message content are omitted.
        A nextCursor marks a partial page. No prompt fetch or server access.
        Input at most 200000 chars, 20000 nodes, 500 prompts/arguments;
        limit 1-50. Supports 2025-11-25 and 2026-07-28.
        """
        return await _run(catalogs.inspect_mcp_prompt_manifest, manifest, protocol_version, limit)

    @mcp.tool()
    async def compare_mcp_prompt_manifests(before: str, after: str,
                                           protocol_version: str = "2025-11-25", limit: int = 20) -> str:
        """Compare complete supplied prompts/list snapshots by exact prompt
        and argument names. Flag presence, required-flag and selected metadata
        changes without returning descriptions or prompt content. Partial
        nextCursor pages are rejected. Each input at most 200000 chars;
        limit 1-50. Supports 2025-11-25 and 2026-07-28.
        """
        return await _run(catalogs.compare_mcp_prompt_manifests, before, after, protocol_version, limit)

    @mcp.tool()
    async def inspect_mcp_server_capabilities(response: str, protocol_version: str = "2025-11-25",
                                              limit: int = 20) -> str:
        """Inspect a supplied 2025 initialize or 2026 server/discover result.
        Summarize known server capabilities and version declarations; omit
        instructions and extension settings. No connection or trust verdict.
        Input at most 200000 chars and 20000 nodes; limit 1-50.
        """
        return await _run(runtime.inspect_mcp_server_capabilities, response, protocol_version, limit)

    @mcp.tool()
    async def compare_mcp_server_capabilities(before: str, after: str,
                                              protocol_version: str = "2025-11-25", limit: int = 20) -> str:
        """Compare selected declarations in two supplied initialize or
        server/discover results of the same protocol era. Omit instructions,
        extension settings and identity values. No compatibility verdict.
        Each input at most 200000 chars; limit 1-50.
        """
        return await _run(runtime.compare_mcp_server_capabilities, before, after, protocol_version, limit)

    @mcp.tool()
    async def validate_mcp_prompt_arguments(manifest: str, prompt_name: str, arguments: str,
                                            protocol_version: str = "2025-11-25", limit: int = 20) -> str:
        """Check supplied prompts/get string arguments against one prompt's
        required declarations in a supplied prompts/list page. Undeclared
        names are reported, not rejected. No prompt fetch or value echo.
        Each JSON input at most 200000 chars; limit 1-50.
        """
        return await _run(runtime.validate_mcp_prompt_arguments, manifest, prompt_name,
                          arguments, protocol_version, limit)

    @mcp.tool()
    async def validate_mcp_resource_read_result(response: str, protocol_version: str = "2025-11-25",
                                                limit: int = 20) -> str:
        """Check selected resources/read result structure, content kinds,
        base64 syntax and 2026 cache hints without exposing resource contents
        or URIs. Input-required results remain unchecked. No dereference.
        Input at most 200000 chars, 500 entries; limit 1-50.
        """
        return await _run(runtime.validate_mcp_resource_read_result, response, protocol_version, limit)

    @mcp.tool()
    async def validate_mcp_prompt_get_result(response: str, protocol_version: str = "2025-11-25",
                                             limit: int = 20) -> str:
        """Check selected prompts/get message roles and content-block shapes
        without returning text, media data or embedded resource contents.
        Input-required results remain unchecked. No prompt rendering.
        Input at most 200000 chars, 500 messages; limit 1-50.
        """
        return await _run(runtime.validate_mcp_prompt_get_result, response, protocol_version, limit)
