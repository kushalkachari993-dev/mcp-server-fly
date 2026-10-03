import json

from . import service


def register(mcp):
    @mcp.tool()
    async def check_http_endpoints(endpoints_json: str) -> str:
        """Check 1-5 public HTTP endpoints using GET, with at most two concurrent requests.
        Supply a JSON array of {url, expected_status: 200, name: "optional"} objects.
        Returns final status/URL, status match, elapsed milliseconds, and individual
        errors in input order. No credentials, headers, or bodies are accepted.
        Private destinations/redirects are blocked; request budget is 10 seconds
        (blocking DNS can exceed it), with three redirects and a 1 MB download cap.
        """
        try:
            result = await service.check_endpoints(endpoints_json)
            output = json.dumps(result, indent=2, allow_nan=False)
            if len(output) > 100000:
                raise ValueError("Endpoint output exceeds 100000 characters")
            return output
        except (ValueError, RecursionError) as error:
            return f"Error: {error}"
