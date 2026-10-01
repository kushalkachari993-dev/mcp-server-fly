import ipaddress
import socket
import time
from urllib.parse import quote, urljoin, urlsplit

import urllib3


_MAX_BYTES = 1000000
_MAX_REDIRECTS = 3
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_PAGE_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}


def _public_destination(url: str):
    if len(url) > 4096:
        raise ValueError("URL must not exceed 4096 characters")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("A public HTTP or HTTPS URL is required")
    if parts.username is not None or parts.password is not None:
        raise ValueError("URLs containing credentials are not supported")
    hostname = parts.hostname.encode("idna").decode("ascii").rstrip(".")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in {80, 443}:
        raise ValueError("Only ports 80 and 443 are supported")
    try:
        resolved = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise ValueError("Could not resolve hostname") from error
    addresses = {ipaddress.ip_address(item[4][0]) for item in resolved}
    if not addresses or any(not address.is_global or address.is_multicast for address in addresses):
        raise ValueError("Private, local, and other non-public addresses are blocked")
    address = min(addresses, key=lambda item: (item.version, int(item)))
    return parts, hostname, port, str(address)


def request_public(url: str, *, method="GET", headers=None, body=None, timeout_seconds=25,
                   allowed_host=None):
    deadline = time.monotonic() + timeout_seconds
    url = url.strip()
    headers = dict(headers or {})
    for redirect_number in range(_MAX_REDIRECTS + 1):
        parts, hostname, port, address = _public_destination(url)
        if allowed_host is not None and (hostname != allowed_host or parts.scheme != "https"):
            raise ValueError("Destination host is not allowed")
        authority = f"[{hostname}]" if ":" in hostname else hostname
        if parts.port is not None:
            authority += f":{port}"
        target = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
        if parts.query:
            target += "?" + quote(parts.query, safe="=&?/%:@!$'()*+,;:-._~")

        # Connect to the validated IP while retaining the original TLS name and Host.
        if parts.scheme == "https":
            pool = urllib3.HTTPSConnectionPool(
                address, port=port, assert_hostname=hostname, server_hostname=hostname
            )
        else:
            pool = urllib3.HTTPConnectionPool(address, port=port)
        response = None
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("Webpage request timed out")
            response = pool.urlopen(
                method, target,
                body=body,
                headers={**headers,
                    "Host": authority,
                    "User-Agent": headers.get("User-Agent", "MCPSever/0.1"),
                    "Accept-Encoding": "gzip, deflate",
                },
                redirect=False,
                retries=False,
                preload_content=False,
                timeout=urllib3.Timeout(connect=min(5, remaining), read=min(5, remaining)),
            )
            if response.status in _REDIRECT_CODES:
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("Redirect response did not include a destination")
                if redirect_number == _MAX_REDIRECTS:
                    raise ValueError("Too many redirects")
                next_url = urljoin(url, location)
                next_parts = urlsplit(next_url)
                if next_parts.hostname != parts.hostname or next_parts.scheme != parts.scheme:
                    if body is not None:
                        raise ValueError("Cross-origin redirects with a request body are blocked")
                    headers = {key: value for key, value in headers.items()
                               if key.lower() not in {"authorization", "cookie", "proxy-authorization"}}
                if response.status == 303 or (response.status in {301, 302} and method == "POST"):
                    method, body = "GET", None
                    headers = {key: value for key, value in headers.items()
                               if key.lower() not in {"content-type", "content-length"}}
                url = next_url
                continue
            body = bytearray()
            while True:
                if time.monotonic() > deadline:
                    raise ValueError("Webpage request timed out")
                chunk = response.read(min(65536, _MAX_BYTES - len(body) + 1), decode_content=True)
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > _MAX_BYTES:
                    raise ValueError("Webpage exceeds the 1 MB download limit")
            return response.status, dict(response.headers), bytes(body), url
        finally:
            if response is not None:
                response.close()
            pool.close()
    raise ValueError("Too many redirects")


def fetch_page(url: str, *, media_types=None, allowed_host=None):
    allowed_types = _PAGE_TYPES if media_types is None else media_types
    status, headers, body, final_url = request_public(
        url, headers={"Accept": ",".join(sorted(allowed_types))}, allowed_host=allowed_host
    )
    if not 200 <= status < 300:
        raise ValueError(f"Webpage returned HTTP {status}")
    content_type = next((value.lower() for key, value in headers.items()
                         if key.lower() == "content-type"), "")
    media_type = content_type.split(";", 1)[0].strip()
    if media_type not in allowed_types:
        if media_types is None:
            raise ValueError("Only HTML and plain-text webpages are supported")
        raise ValueError("Response has an unsupported content type")
    return body, content_type, final_url
