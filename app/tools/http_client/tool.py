import ipaddress
import json
import socket
from urllib.parse import urlparse

import requests


_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_MAX_BODY_CHARS = 20000
_MAX_RESPONSE_CHARS = 8000


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


def _parse_json_object(value: str, field_name: str) -> dict:
    if not value or not value.strip():
        return {}

    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object")

    return parsed


def register(mcp):

    @mcp.tool()
    def http_request(
        url: str,
        method: str = "GET",
        headers_json: str = "",
        body: str = "",
        timeout_seconds: int = 10,
    ) -> str:
        """
        Make an HTTP request to a public HTTP/HTTPS URL.
        headers_json must be a JSON object string. Local/private hosts are blocked.
        """

        url = url.strip()
        method = method.strip().upper()
        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"}:
            return "Error: URL must start with http:// or https://"

        if not parsed.hostname:
            return "Error: URL must include a hostname"

        if method not in _ALLOWED_METHODS:
            return f"Error: Method must be one of {', '.join(sorted(_ALLOWED_METHODS))}"

        if len(body) > _MAX_BODY_CHARS:
            return f"Error: Body is too large. Maximum is {_MAX_BODY_CHARS} characters"

        if timeout_seconds < 1 or timeout_seconds > 30:
            return "Error: timeout_seconds must be between 1 and 30"

        try:
            if not _is_public_host(parsed.hostname):
                return "Error: Private, local, reserved, or link-local hosts are blocked"

            headers = _parse_json_object(headers_json, "headers_json")
            headers.setdefault("User-Agent", "MCPSever/0.1")

            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                data=body if body else None,
                timeout=timeout_seconds,
                allow_redirects=True,
            )

            response_text = response.text[:_MAX_RESPONSE_CHARS]
            truncated = len(response.text) > _MAX_RESPONSE_CHARS
            response_headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower()
                in {
                    "content-type",
                    "content-length",
                    "cache-control",
                    "server",
                    "location",
                }
            }

            return (
                f"Status: {response.status_code}\n"
                f"Final URL: {response.url}\n"
                f"Headers: {json.dumps(response_headers, indent=2)}\n"
                f"Truncated: {truncated}\n\n"
                f"{response_text}"
            )
        except json.JSONDecodeError as e:
            return f"Error: headers_json is invalid JSON - {e}"
        except requests.exceptions.Timeout:
            return "Error: Request timed out"
        except requests.exceptions.RequestException as e:
            return f"Error: Network issue - {e}"
        except Exception as e:
            return f"Error: {e}"
