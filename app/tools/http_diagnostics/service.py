import json
import re
import time
from urllib.parse import urljoin, urlsplit

import urllib3

from app.tools.webpage.service import request_public


_REDIRECTS = {301, 302, 303, 307, 308}
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_CORS_HEADERS = ("access-control-allow-origin", "access-control-allow-credentials",
                 "access-control-allow-methods", "access-control-allow-headers",
                 "access-control-expose-headers", "access-control-max-age", "vary")


def _url(url):
    if not isinstance(url, str) or not url.strip() or len(url) > 4096:
        raise ValueError("Use a public URL of at most 4096 characters")
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url):
        raise ValueError("URLs must not contain whitespace or control characters")
    parts = urlsplit(url)
    if (parts.scheme not in {"http", "https"} or not parts.hostname
            or parts.username is not None or parts.password is not None or parts.port not in {None, 80, 443}):
        raise ValueError("Use HTTP/HTTPS on ports 80/443 without URL credentials")
    return url


def _url_key(url):
    parts = urlsplit(url)
    return (parts.scheme, parts.hostname.lower().rstrip("."), parts.port or (443 if parts.scheme == "https" else 80),
            parts.path or "/", parts.query)


def trace_redirects(url):
    url = _url(url)
    current, seen, hops = url, set(), []
    deadline = time.monotonic() + 25
    result = {"url": url, "final_url": url, "http_status": None, "completed": False,
              "hops": hops, "loop_detected": False, "https_downgrade_observed": False,
              "redirect_limit_reached": False, "error": None, "truncated": False}
    for index in range(4):
        seen.add(_url_key(current))
        started = time.monotonic()
        try:
            def request(method):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("Redirect inspection exceeded its 25-second request budget")
                return request_public(current, method=method, follow_redirects=False, timeout_seconds=remaining)

            method = "HEAD"
            status, headers, _, final_url = request(method)
            if status in {405, 501}:
                method = "GET"
                status, headers, _, final_url = request(method)
            normalized = {name.lower(): value for name, value in headers.items()}
            location = normalized.get("location") if status in _REDIRECTS else None
            hops.append({"url": final_url, "http_status": status, "method": method,
                         "location": location[:4096] if location else None,
                         "elapsed_ms": round((time.monotonic() - started) * 1000, 2)})
            result.update(final_url=final_url, http_status=status)
            if status not in _REDIRECTS:
                result["completed"] = True
                break
            if not location:
                raise ValueError("Redirect response did not include a destination")
            if len(location) > 4096:
                result["truncated"] = True
                raise ValueError("Redirect destination exceeds 4096 characters")
            next_url = _url(urljoin(current, location))
            result["https_downgrade_observed"] |= urlsplit(current).scheme == "https" and urlsplit(next_url).scheme == "http"
            if _url_key(next_url) in seen:
                result["loop_detected"] = True
                raise ValueError("Redirect loop detected")
            if index == 3:
                result["redirect_limit_reached"] = True
                raise ValueError("Redirect inspection stopped after three redirects")
            current = next_url
        except (ValueError, urllib3.exceptions.HTTPError, OSError) as error:
            result["error"] = f"{type(error).__name__}: {error}"[:500]
            break
    result["redirect_responses"] = sum(hop["http_status"] in _REDIRECTS for hop in hops)
    result["followed_redirects"] = max(0, len(hops) - 1)
    result["notes"] = ["Observed HEAD responses, with GET fallback on 405/501; browser navigation may behave differently.",
                       "Each requested hop is revalidated as public and IP-pinned. No credentials or bodies are sent.",
                       "Budget is 25 seconds across at most four URLs; blocking DNS can exceed it. Each download is capped at 1 MB.",
                       "final_url is the last successfully observed response, not an unrequested redirect destination."]
    return result


def _origin(origin):
    if origin == "null":
        return origin
    if not origin or len(origin) > 2000 or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in origin):
        raise ValueError("origin must be null or a valid HTTP/HTTPS origin without controls")
    parts = urlsplit(origin)
    if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.path not in {"", "/"} or parts.query or parts.fragment):
        raise ValueError("origin must contain only HTTP/HTTPS scheme, hostname, and optional port")
    port = parts.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Origin port must be between 1 and 65535")
    host = parts.hostname.encode("idna").decode("ascii").lower()
    host = f"[{host}]" if ":" in host else host
    suffix = f":{port}" if port is not None and port != (443 if parts.scheme == "https" else 80) else ""
    return f"{parts.scheme}://{host}{suffix}"


def _requested_headers(value):
    if len(value) > 4000:
        raise ValueError("requested_headers_json must not exceed 4000 characters")
    try:
        headers = json.loads(value)
    except (ValueError, RecursionError) as error:
        raise ValueError("requested_headers_json must be a JSON array of header names") from error
    if not isinstance(headers, list) or len(headers) > 20 or any(
        not isinstance(header, str) or len(header) > 100 or not _TOKEN.fullmatch(header) or header == "*" for header in headers
    ):
        raise ValueError("Provide at most 20 valid header names of up to 100 characters")
    return sorted({header.lower() for header in headers})


def _cors_response(status, headers, final_url, origin):
    headers = {name.lower(): value for name, value in headers.items()}
    if any(len(headers.get(name, "")) > 16000 for name in _CORS_HEADERS):
        raise ValueError("CORS headers must not exceed 16000 characters each")
    issues = []

    def tokens(name, lower=False):
        raw = headers.get(name, "")
        values = [value.strip() for value in raw.split(",")] if raw.strip() else []
        if len(values) > 100 or any(not _TOKEN.fullmatch(value) for value in values):
            issues.append(f"Malformed or oversized {name} token list")
            return None
        return [value.lower() for value in values] if lower else values

    allowed_origin = headers["access-control-allow-origin"].strip() if "access-control-allow-origin" in headers else None
    credentials = headers["access-control-allow-credentials"].strip() if "access-control-allow-credentials" in headers else None
    if allowed_origin is not None and allowed_origin not in {origin, "*"}:
        issues.append("Access-Control-Allow-Origin does not exactly match the supplied origin or wildcard")
    if credentials is not None and credentials != "true":
        issues.append("Access-Control-Allow-Credentials must be exactly true when present")
    if allowed_origin == "*" and credentials == "true":
        issues.append("Wildcard origin cannot authorize credentialed access")
    methods = tokens("access-control-allow-methods")
    allowed_headers = tokens("access-control-allow-headers", lower=True)
    exposed = tokens("access-control-expose-headers", lower=True)
    return {
        "http_status": status, "url": final_url,
        "headers": {name: headers[name][:2000] for name in _CORS_HEADERS if name in headers},
        "allowed_methods": methods, "allowed_headers": allowed_headers, "exposed_headers": exposed,
        "origin_allows_anonymous": allowed_origin in {origin, "*"},
        "origin_allows_credentials": allowed_origin == origin and credentials == "true",
        "issues": issues, "truncated": any(len(headers.get(name, "")) > 2000 for name in _CORS_HEADERS),
    }


def inspect_cors(url, origin, requested_method, requested_headers_json):
    url, origin, requested_headers = _url(url), _origin(origin), _requested_headers(requested_headers_json)
    if requested_method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
        raise ValueError("requested_method must be an uppercase GET, HEAD, POST, PUT, PATCH, DELETE, or OPTIONS")
    deadline = time.monotonic() + 25

    def request(method, headers):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("CORS inspection exceeded its 25-second request budget")
        status, response_headers, _, final_url = request_public(
            url, method=method, headers=headers, follow_redirects=False, timeout_seconds=remaining
        )
        return _cors_response(status, response_headers, final_url, origin)

    headers = {"Origin": origin, "Access-Control-Request-Method": requested_method}
    if requested_headers:
        headers["Access-Control-Request-Headers"] = ", ".join(requested_headers)
    preflight = request("OPTIONS", headers)
    methods, allowed_headers = preflight["allowed_methods"], preflight["allowed_headers"]
    safelisted_method = requested_method in {"GET", "HEAD", "POST"}
    method_anonymous = methods is not None and (safelisted_method or requested_method in methods or "*" in methods)
    method_credentials = methods is not None and (safelisted_method or requested_method in methods)
    header_anonymous = allowed_headers is not None and all(
        header in allowed_headers or (header != "authorization" and "*" in allowed_headers) for header in requested_headers
    )
    header_credentials = allowed_headers is not None and all(header in allowed_headers for header in requested_headers)
    preflight.update(
        requested_method_allowed_anonymous=method_anonymous, requested_headers_allowed_anonymous=header_anonymous,
        cors_allows_anonymous=200 <= preflight["http_status"] < 300 and preflight["origin_allows_anonymous"] and method_anonymous and header_anonymous,
        cors_allows_credentials=200 <= preflight["http_status"] < 300 and preflight["origin_allows_credentials"] and method_credentials and header_credentials,
    )
    get_response = request("GET", {"Origin": origin, "Accept": "*/*"})
    return {"url": url, "origin": origin, "requested_method": requested_method,
            "requested_headers": requested_headers, "preflight": preflight, "get": get_response,
            "truncated": preflight["truncated"] or get_response["truncated"],
            "notes": ["Header observations only, not a browser test, authorization check, or proof of safety.",
                      "Only OPTIONS and an anonymous GET are sent. Requested methods and header names are preflight metadata, never executed/sent as actual values.",
                      "GET is an independent sample and does not verify the actual response for another requested method or headers.",
                      "Redirects are not followed; no cookies, tokens, or request bodies are sent. Browser safelisted header values are not modeled.",
                      "Budget is 25 seconds across two requests; blocking DNS can exceed it. Each download is capped at 1 MB."]}
