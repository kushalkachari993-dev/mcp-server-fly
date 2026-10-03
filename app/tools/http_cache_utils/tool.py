import json

import anyio
import urllib3

from . import service


def register(mcp):
    @mcp.tool()
    async def inspect_http_cache(url: str) -> str:
        """Inspect public response cache headers using HEAD, falling back to GET on
        405/501. Separates browser/shared storage and declared freshness directives;
        reports duplicates, invalid values, validators, and field-qualified rules.
        Does not calculate remaining TTL or guarantee actual caching behavior.
        Shared public transport blocks private destinations/redirects and caps
        downloads at 1 MB. Up to 100 directives/16000 header characters are parsed.
        """
        try:
            result = await anyio.to_thread.run_sync(service.inspect_cache, url)
            output = json.dumps(result, indent=2, allow_nan=False)
            if len(output) > 100000:
                raise ValueError("Cache inspection output exceeds 100000 characters")
            return output
        except (ValueError, RecursionError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"
