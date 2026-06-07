import ipaddress
import socket
from urllib.parse import urlparse

import requests


_MAX_CHARS = 6000


def _is_public_host(hostname: str) -> bool:
    try:
        addresses = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ValueError("Could not resolve hostname")

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False

    return True


def register(mcp):

    @mcp.tool()
    def fetch_url(url: str) -> str:
        """
        Fetch a public HTTP/HTTPS URL and return status, content type, and text.
        Blocks localhost, private, reserved, and link-local network addresses.
        """

        url = url.strip()
        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"}:
            return "Error: URL must start with http:// or https://"

        if not parsed.hostname:
            return "Error: URL must include a hostname"

        try:
            if not _is_public_host(parsed.hostname):
                return "Error: Private, local, reserved, or link-local hosts are blocked"

            response = requests.get(
                url,
                timeout=10,
                headers={"User-Agent": "MCPSever/0.1"},
            )

            content_type = response.headers.get("content-type", "unknown")
            text = response.text[:_MAX_CHARS]
            truncated = len(response.text) > _MAX_CHARS

            return (
                f"Status: {response.status_code}\n"
                f"Content-Type: {content_type}\n"
                f"Final URL: {response.url}\n"
                f"Truncated: {truncated}\n\n"
                f"{text}"
            )
        except requests.exceptions.Timeout:
            return "Error: Request timed out"
        except requests.exceptions.RequestException as e:
            return f"Error: Network issue - {e}"
        except Exception as e:
            return f"Error: {e}"
