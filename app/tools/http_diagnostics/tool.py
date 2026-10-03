import json

import anyio
import urllib3

from . import service


def register(mcp):
    @mcp.tool()
    async def inspect_redirect_chain(url: str) -> str:
        """Trace a public URL through up to three redirects, showing each observed
        status, destination, HEAD/GET method, timing, loops, and HTTPS downgrades.
        HEAD uses GET fallback on 405/501. Private destinations are blocked at
        every hop; partial observations retain bounded network/redirect errors.
        No credentials/bodies. Total request budget 25 seconds (DNS can exceed it),
        1 MB per response, 4096 chars per URL, and 100000 output characters.
        """
        try:
            result = await anyio.to_thread.run_sync(service.trace_redirects, url)
            output = json.dumps(result, indent=2, allow_nan=False)
            if len(output) > 100000:
                raise ValueError("Redirect inspection output exceeds 100000 characters")
            return output
        except (ValueError, RecursionError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def inspect_http_cors(url: str, origin: str, requested_method: str = "GET",
                                requested_headers_json: str = "[]") -> str:
        """Inspect public CORS headers with OPTIONS and an independent anonymous
        GET. requested_method/header names are preflight metadata only; no POST,
        DELETE, credentials, bodies, or custom header values are sent. Origin may
        be an HTTP/HTTPS origin (any port) or null. Redirects are not followed.
        Reports separate anonymous/credential declarations, not actual browser
        access. Bounds: 20 requested names, 100 returned header tokens, 25-second
        total request budget (DNS can exceed it), 1 MB per download, 100000 output.
        """
        try:
            result = await anyio.to_thread.run_sync(service.inspect_cors, url, origin, requested_method, requested_headers_json)
            output = json.dumps(result, indent=2, allow_nan=False)
            if len(output) > 100000:
                raise ValueError("CORS output exceeds 100000 characters")
            return output
        except (ValueError, RecursionError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"
