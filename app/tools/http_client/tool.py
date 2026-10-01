import json

import urllib3

from app.tools.webpage.service import request_public


_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_MAX_BODY_CHARS = 20000
_MAX_RESPONSE_CHARS = 8000


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
        if method not in _ALLOWED_METHODS:
            return f"Error: Method must be one of {', '.join(sorted(_ALLOWED_METHODS))}"

        if len(body) > _MAX_BODY_CHARS:
            return f"Error: Body is too large. Maximum is {_MAX_BODY_CHARS} characters"

        if len(headers_json) > 8000:
            return "Error: headers_json must not exceed 8000 characters"

        if timeout_seconds < 1 or timeout_seconds > 30:
            return "Error: timeout_seconds must be between 1 and 30"

        try:
            headers = _parse_json_object(headers_json, "headers_json")
            if len(headers) > 30:
                raise ValueError("headers_json must contain at most 30 headers")
            if any(not isinstance(key, str) or not isinstance(value, str) for key, value in headers.items()):
                raise ValueError("headers_json keys and values must be strings")
            if any(not key or len(key) > 100 or len(value) > 1000 or
                   "\r" in key or "\n" in key or "\r" in value or "\n" in value
                   for key, value in headers.items()):
                raise ValueError("headers_json contains an invalid or oversized header")
            if any(key.lower() in {"host", "content-length", "transfer-encoding"} for key in headers):
                raise ValueError("Host, Content-Length, and Transfer-Encoding headers are managed by the server")
            headers.setdefault("User-Agent", "MCPSever/0.1")
            status, response_headers, response_body, final_url = request_public(
                url, method=method, headers=headers, body=body.encode("utf-8") if body else None,
                timeout_seconds=timeout_seconds,
            )
            decoded = response_body.decode("utf-8", errors="replace")
            response_text = decoded[:_MAX_RESPONSE_CHARS]
            truncated = len(decoded) > _MAX_RESPONSE_CHARS
            selected_headers = {
                key: value
                for key, value in response_headers.items()
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
                f"Status: {status}\n"
                f"Final URL: {final_url}\n"
                f"Headers: {json.dumps(selected_headers, indent=2)}\n"
                f"Truncated: {truncated}\n\n"
                f"{response_text}"
            )
        except json.JSONDecodeError as e:
            return f"Error: headers_json is invalid JSON - {e}"
        except urllib3.exceptions.TimeoutError:
            return "Error: Request timed out"
        except urllib3.exceptions.HTTPError as e:
            return f"Error: Network issue - {e}"
        except Exception as e:
            return f"Error: {e}"
