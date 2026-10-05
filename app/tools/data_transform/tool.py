import anyio

from . import service


async def _run(function, *args):
    try:
        return await anyio.to_thread.run_sync(function, *args)
    except (ValueError, RecursionError) as error:
        # Parser diagnostics can contain supplied values; keep errors content-free.
        if isinstance(error, ValueError) and type(error) is not ValueError:
            return "Error: Invalid JSON input"
        return f"Error: {error}"


def register(mcp):
    @mcp.tool()
    async def inspect_jsonl(content: str, limit: int = 100) -> str:
        """Inspect supplied JSON Lines offline: record types, top-level fields/types,
        missing fields among object records, blank lines and malformed line numbers.
        Values are omitted. Blank lines are ignored; limit 1..1000 bounds field and
        error listings. Each input/output <=200000 chars, <=10000 nodes, depth <=50.
        Duplicate keys and non-finite numbers are invalid. Lines split on LF.
        """
        return await _run(service.inspect_jsonl, content, limit)

    @mcp.tool()
    async def jsonl_to_json(content: str) -> str:
        """Convert supplied JSON Lines to a complete JSON array offline. Ignore blank
        lines; reject any malformed record without partial output. Any JSON record
        type is supported. Duplicate keys/non-finite numbers rejected. Input/output
        <=200000 chars, aggregate <=10000 nodes, nesting <=50; LF-delimited lines.
        """
        return await _run(service.jsonl_to_json, content)

    @mcp.tool()
    async def json_to_jsonl(value: str) -> str:
        """Convert a supplied JSON array to LF-separated compact JSON records offline,
        without a trailing newline. Empty arrays return empty text. No partial output.
        Duplicate keys/non-finite numbers rejected. Input/output <=200000 chars,
        <=10000 nodes, nesting <=50.
        """
        return await _run(service.json_to_jsonl, value)

    @mcp.tool()
    async def flatten_json(value: str) -> str:
        """Flatten nested objects to a JSON Pointer/value map offline. Escape ~ and /;
        empty pointer denotes root. Preserve arrays intact, including nested objects
        inside arrays; preserve empty objects and scalar roots. Duplicate keys and
        non-finite numbers rejected. Input/output <=200000 chars, <=10000 nodes,
        nesting <=50. Output is reversible with unflatten_json.
        """
        return await _run(service.flatten_json, value)

    @mcp.tool()
    async def unflatten_json(value: str) -> str:
        """Reconstruct JSON from a supplied JSON Pointer/value map offline. Intermediate
        containers are objects; numeric tokens are object keys. Arrays remain intact
        as leaf values. Reject invalid escapes, duplicate keys and conflicting
        ancestor/descendant paths. Empty map yields {}. Input/output <=200000 chars,
        <=10000 nodes, nesting/pointer depth <=50; no partial output.
        """
        return await _run(service.unflatten_json, value)

    @mcp.tool()
    async def redact_json_fields(value: str, pointers_json: str, mask: str = "[REDACTED]") -> str:
        """Replace explicitly selected existing JSON Pointer values with a string mask
        and return the complete JSON document offline. Supports object keys, canonical
        array indices and root. Reject missing, duplicate or overlapping pointers;
        no partial output. Unselected values remain in output. At most 100 pointers;
        input/output <=200000 chars, <=10000 nodes, nesting/pointer depth <=50.
        """
        return await _run(service.redact_json_fields, value, pointers_json, mask)
