import json

import anyio

from . import service


def register(mcp):
    @mcp.tool()
    async def inspect_sbom(content: str, limit: int = 50) -> str:
        """Inspect supplied CycloneDX JSON 1.5/1.6/1.7: metadata and nested
        components, versions, package URLs, declared licenses and dependsOn edges.
        No vulnerability/license-compliance conclusion or completeness inference.
        SPDX/XML and service inventory are not supported. No file/network access
        or execution. Bounds: 200000 chars, 10000 nodes, 50 nesting levels, 1000
        components/dependency entries, 5000 edges; limit 1-200; output 100000 chars.
        """
        try:
            result = await anyio.to_thread.run_sync(service.inspect_sbom, content, limit)
            output = json.dumps(result, indent=2, allow_nan=False)
            if len(output) > 100000:
                raise ValueError("SBOM summary exceeds 100000 characters; reduce input/limit")
            return output
        except (ValueError, RecursionError) as error:
            return f"Error: {error}"
