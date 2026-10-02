import json

import anyio

from . import service


def register(mcp):

    @mcp.tool()
    async def inspect_dependency_manifest(content: str, format: str, limit: int = 100) -> str:
        """Inspect supplied package.json or pyproject.toml text offline.
        Lists declared requirements by section, preserving Python extras/markers/URLs.
        Python dependency-group includes are listed, not expanded; tool-specific
        declarations are not read. Does not resolve versions, access files/URLs,
        evaluate markers, or install packages. Input: 200000 characters; 1-200
        returned requirements; output: 100000 characters. Not a full manifest validator.
        """
        try:
            result = await anyio.to_thread.run_sync(service.inspect_manifest, content, format, limit)
            output = json.dumps(result, indent=2, allow_nan=False)
            if len(output) > 100000:
                raise ValueError("Manifest output exceeds 100000 characters; reduce limit")
            return output
        except (ValueError, RecursionError) as error:
            return f"Error: {error}"
