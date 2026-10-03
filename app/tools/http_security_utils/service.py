from urllib.parse import urlsplit

from app.tools.webpage.service import request_public


_SECURITY_HEADERS = {
    "content-security-policy": "Controls permitted content sources and browser execution.",
    "strict-transport-security": "Requests HTTPS for future visits.",
    "referrer-policy": "Controls referrer information sent with requests.",
    "permissions-policy": "Controls access to browser capabilities.",
    "x-content-type-options": "Prevents MIME-type sniffing when set to nosniff.",
    "x-frame-options": "Controls legacy framing protection.",
    "cross-origin-opener-policy": "Controls cross-origin browsing context isolation.",
    "cross-origin-resource-policy": "Controls cross-origin resource loading.",
    "cross-origin-embedder-policy": "Controls cross-origin resource embedding.",
}


def inspect_headers(url):
    status, headers, _, final_url = request_public(
        url, method="HEAD", headers={"Accept": "*/*", "User-Agent": "MCPSever/0.1"}
    )
    if status in {405, 501}:
        status, headers, _, final_url = request_public(
            url, method="GET", headers={"Accept": "*/*", "User-Agent": "MCPSever/0.1"}
        )
    normalized = {key.lower(): value for key, value in headers.items()}
    present = {name: normalized[name][:2000] for name in _SECURITY_HEADERS if name in normalized}
    missing = [name for name in _SECURITY_HEADERS if name not in normalized]
    final_parts = urlsplit(final_url)
    notes = ["This is a header-presence summary, not a security score or proof of safety."]
    if final_parts.scheme != "https":
        notes.append("The final URL is not HTTPS; sensitive data should not be sent over it.")
    elif "strict-transport-security" not in normalized:
        notes.append("Strict-Transport-Security is absent from the final response.")
    if "content-security-policy" not in normalized:
        notes.append("Content-Security-Policy is absent from the final response.")
    return {
        "url": url,
        "final_url": final_url,
        "http_status": status,
        "https": final_parts.scheme == "https",
        "present": present,
        "missing": missing,
        "notes": notes,
    }
