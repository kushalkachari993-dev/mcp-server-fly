import json

import anyio
import urllib3

from . import service


def register(mcp):

    @mcp.tool()
    async def inspect_robots_txt(site_url: str, max_rules: int = 100) -> str:
        """Summarize user-agent groups, allow/disallow rules, and Sitemap lines
        from a public HTTPS site's root robots.txt. A 4xx response is reported
        as missing; 5xx is an error. Rules are not evaluated. Up to 200 rules.
        """
        try:
            if not 1 <= max_rules <= 200:
                raise ValueError("max_rules must be between 1 and 200")
            result = await anyio.to_thread.run_sync(service.inspect_robots, site_url, max_rules)
            return json.dumps(result, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def read_sitemap(url: str, limit: int = 100) -> str:
        """Read up to 500 URLs and last-modified values from a public XML sitemap
        or sitemap index. Child sitemaps are listed, not fetched. Downloads are
        limited to 1 MB; DTDs, custom entity declarations, and excessive XML
        nesting are rejected.
        Gzipped and plain-text sitemap formats are not supported.
        """
        try:
            if not 1 <= limit <= 500:
                raise ValueError("limit must be between 1 and 500")
            result = await anyio.to_thread.run_sync(service.read_sitemap, url, limit)
            return json.dumps(result, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"
