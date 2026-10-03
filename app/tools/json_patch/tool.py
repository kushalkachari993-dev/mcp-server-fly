import anyio

from . import service


def register(mcp):

    @mcp.tool()
    async def apply_json_patch(value: str, patch: str) -> str:
        """Apply RFC 6902 JSON Patch operations to supplied JSON and return the result.
        Supports add/remove/replace/move/copy/test, escaped JSON Pointers, array
        appends, and root replacement. Root removal is unsupported. Errors return
        no partial document. No files or APIs are modified. Each input/output is
        capped at 200000 characters; 50 operations, 10000 nodes, 50 nested levels.
        Limits are checked after every operation, including copies.
        """
        try:
            return await anyio.to_thread.run_sync(service.apply, value, patch)
        except (ValueError, RecursionError) as error:
            return f"Error: {error}"
