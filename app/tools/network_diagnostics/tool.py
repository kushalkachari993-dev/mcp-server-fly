import json
import ssl

import anyio
import urllib3

from . import service


def register(mcp):

    @mcp.tool()
    async def inspect_tls_certificate(domain: str) -> str:
        """Inspect a public domain's HTTPS certificate on port 443. Verifies the
        certificate and hostname, then reports issuer, validity dates, days
        until expiry, and up to 20 DNS names. Invalid certificates return an error.
        """
        try:
            result = await anyio.to_thread.run_sync(service.inspect_certificate, domain)
            return json.dumps(result, indent=2)
        except (ValueError, OSError, ssl.SSLError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def lookup_dns_records(domain: str, record_type: str = "A", limit: int = 20) -> str:
        """Query public DNS A, AAAA, MX, or TXT records through Cloudflare DNS
        over HTTPS. Returns up to 50 records, DNS status, TTL, and truncation.
        The domain is sent to Cloudflare; local/private DNS is not queried.
        """
        try:
            if not 1 <= limit <= 50:
                raise ValueError("limit must be between 1 and 50")
            result = await anyio.to_thread.run_sync(service.lookup_records, domain, record_type, limit)
            return json.dumps(result, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"
