from app.tools.report_utils.tool import _run

from . import service


def register(mcp):
    @mcp.tool()
    async def inspect_graphql_schema(schema_sdl: str, limit: int = 20) -> str:
        """Inspect supplied valid GraphQL SDL: operation roots, types, fields,
        arguments, interfaces/unions, enums, directives and deprecation flags.
        GraphQL-core 3.2 rules; no introspection request/resolvers or source-file
        access. Descriptions/default values/deprecation reasons omitted. Each
        input <=200000 chars, 8000 tokens, depth 50, 10000 AST nodes; names <=1000.
        Five-second worker, one concurrent GraphQL worker; limit 1-50 per list,
        output 100000 chars. Names may still contain caller-sensitive data.
        """
        return await _run(service.inspect_schema, schema_sdl, limit)

    @mcp.tool()
    async def validate_graphql_operation(schema_sdl: str, document: str, limit: int = 20) -> str:
        """Statically validate an entire supplied operation/fragment document
        against valid SDL with GraphQL-core's specified rules. No query/mutation/
        subscription execution, variable-value coercion, auth/cost/runtime checks
        or custom scalar implementation. Diagnostics return rule IDs and locations,
        not literal values. Each input <=200000 chars; schema 8000/document 4000
        tokens, depth 50, 10000 AST nodes, 200 definitions. Five-second bounded
        worker; at most 50 validation errors plus abort marker, limit 1-50/output
        100000 chars. No network/source-file access or import resolution.
        """
        return await _run(service.validate_operation, schema_sdl, document, limit)

    @mcp.tool()
    async def compare_graphql_schemas(before_sdl: str, after_sdl: str, limit: int = 20) -> str:
        """Compare valid supplied SDL with GraphQL-core 3.2 breaking/dangerous
        change utilities, plus explicit operation-root changes. Not exhaustive
        behavioral/custom directive/scalar/auth or resolver compatibility analysis.
        Default-change values/descriptions omitted. Each input <=200000 chars,
        8000 tokens, depth 50, 10000 AST nodes; five-second/single worker limit.
        Limit 1-50 per list; output 100000 chars. No execution/file/network access.
        """
        return await _run(service.compare_schemas, before_sdl, after_sdl, limit)
