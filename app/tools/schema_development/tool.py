import anyio
from . import service


async def _run(name, *args):
    try:
        return await anyio.to_thread.run_sync(service.run, name, *args)
    except ValueError as error:
        return f"Error: {error}"


def register(mcp):
    @mcp.tool()
    async def inspect_json_schema(schema: str, limit: int = 100) -> str:
        """Inspect supplied JSON Schema declarations, types, required fields, constraints
        and local reference status offline. Supports canonical draft-07, 2019-09,
        2020-12 $schema URIs (default 2020-12); no $id, remote, dynamic or recursive
        refs or nested dialect changes. Does not expand refs. Annotations are not
        schema nodes. Input/output <=200000 chars, <=10000 nodes, depth <=50;
        3-second worker timeout. limit 1..1000 bounds node and reference listings.
        """
        return await _run("inspect_json_schema", schema, limit)

    @mcp.tool()
    async def compare_json_schemas(before: str, after: str, limit: int = 100) -> str:
        """Compare supplied JSON Schema declarations offline, returning changed paths
        without values or a compatibility verdict. Arrays compare as whole values;
        includes annotations and order changes. Same dialect/reference restrictions
        as inspect_json_schema. Input/output <=200000 chars, <=10000 nodes, depth
        <=50; 3-second worker timeout; limit 1..1000 bounds change listings.
        """
        return await _run("compare_json_schemas", before, after, limit)

    @mcp.tool()
    async def infer_json_schema(examples: str) -> str:
        """Infer a draft 2020-12 schema from a nonempty JSON array of sample documents
        offline. Infer observed types, object properties, required fields common to
        samples of each object shape, and combined array item types. Return schema
        with explicit uncertainty; no enums, formats, ranges, tuple constraints or
        additional-property prohibition. Input/output <=200000 chars, <=10000 nodes,
        depth <=50; 3-second worker timeout. Never infer from external data.
        """
        return await _run("infer_json_schema", examples)

    @mcp.tool()
    async def validate_jsonl_schema(content: str, schema: str, limit: int = 100) -> str:
        """Validate every valid LF-delimited JSONL record against supplied JSON Schema
        offline; ignore blank lines, report malformed line numbers separately. Report
        one value-free diagnostic per failing record, identified by one-based line.
        limit 1..1000 caps listings, not evaluated records. Formats are annotations.
        Same dialect/reference restrictions as inspect_json_schema; input/output
        <=200000 chars, <=10000 aggregate nodes, depth <=50; 3-second worker timeout.
        """
        return await _run("validate_jsonl_schema", content, schema, limit)

    @mcp.tool()
    async def validate_json_schema_batch(value: str, schema: str, limit: int = 100) -> str:
        """Validate each item in a supplied JSON array against supplied JSON Schema
        offline. Return counts and one value-free diagnostic per failing item using
        zero-based indices. limit 1..1000 caps diagnostics, not evaluated items.
        Formats are annotations. Same dialect/reference restrictions as inspection;
        input/output <=200000 chars, <=10000 nodes, depth <=50; 3-second timeout.
        """
        return await _run("validate_json_schema_batch", value, schema, limit)

    @mcp.tool()
    async def resolve_json_schema_pointer(schema: str, pointer: str) -> str:
        """Extract a schema node by escaped JSON Pointer from supplied JSON Schema
        offline; empty pointer selects root. Reject keyword/annotation values; return
        complete selected object or boolean without expanding references. Same dialect
        and reference restrictions as inspection. Input/output <=200000 chars,
        <=10000 nodes, nesting/pointer depth <=50; 3-second worker timeout.
        """
        return await _run("resolve_json_schema_pointer", schema, pointer)
