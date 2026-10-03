import json
import time
from urllib.parse import urlsplit

import anyio
import urllib3

from app.tools.webpage.service import request_public


def _read_endpoints(endpoints_json):
    if len(endpoints_json) > 25000:
        raise ValueError("endpoints_json must not exceed 25000 characters")
    try:
        endpoints = json.loads(endpoints_json)
    except (ValueError, RecursionError) as error:
        raise ValueError("endpoints_json must be a JSON array") from error
    if not isinstance(endpoints, list) or not 1 <= len(endpoints) <= 5:
        raise ValueError("Provide between one and five endpoint objects")
    result = []
    for entry in endpoints:
        if not isinstance(entry, dict) or set(entry) - {"name", "url", "expected_status"}:
            raise ValueError("Endpoint objects accept only name, url, and expected_status")
        url, name, expected = entry.get("url"), entry.get("name", ""), entry.get("expected_status", 200)
        if not isinstance(name, str) or len(name) > 100:
            raise ValueError("Endpoint names must be strings of at most 100 characters")
        if not isinstance(url, str) or not url.strip() or len(url) > 4096:
            raise ValueError("Endpoint URLs must be strings of at most 4096 characters")
        url = url.strip()
        if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url):
            raise ValueError("Endpoint URLs cannot contain whitespace or control characters")
        parts = urlsplit(url)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username is not None or parts.password is not None or parts.port not in {None, 80, 443}):
            raise ValueError("Use HTTP/HTTPS URLs on ports 80/443 without credentials")
        if type(expected) is not int or not 100 <= expected <= 599:
            raise ValueError("expected_status must be an integer between 100 and 599")
        result.append({"name": name, "url": url, "expected_status": expected})
    return result


def _check(endpoint):
    started = time.monotonic()
    result = {**endpoint, "http_status": None, "final_url": None, "matched": False, "error": None}
    try:
        status, _, _, final_url = request_public(endpoint["url"], timeout_seconds=10)
        result.update(http_status=status, final_url=final_url, matched=status == endpoint["expected_status"])
    except (ValueError, urllib3.exceptions.HTTPError, OSError) as error:
        result["error"] = f"{type(error).__name__}: {error}"[:500]
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
    return result


async def check_endpoints(endpoints_json):
    endpoints = _read_endpoints(endpoints_json)
    results = [None] * len(endpoints)
    semaphore = anyio.Semaphore(2)

    async def check_one(index, endpoint):
        async with semaphore:
            results[index] = await anyio.to_thread.run_sync(_check, endpoint)

    async with anyio.create_task_group() as group:
        for index, endpoint in enumerate(endpoints):
            group.start_soon(check_one, index, endpoint)
    passed = sum(result["matched"] for result in results)
    return {"count": len(results), "passed": passed, "failed": len(results) - passed,
            "all_matched": passed == len(results), "endpoints": results}
