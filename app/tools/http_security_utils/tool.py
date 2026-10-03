import json

import anyio
import urllib3

from . import service


def register(mcp):

    @mcp.tool()
    async def inspect_http_security_headers(url: str) -> str:
        """Inspect common security-related response headers on a public URL.
        Uses HEAD and falls back to GET when unsupported. Returns bounded header
        values and missing-header notes, not a security score or guarantee.
        Local/private hosts and unsafe redirects are blocked by the shared client.
        """
        try:
            result = await anyio.to_thread.run_sync(service.inspect_headers, url)
            return json.dumps(result, indent=2)
        except (ValueError, RecursionError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"
