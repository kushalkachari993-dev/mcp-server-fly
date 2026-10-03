import re
from urllib.request import parse_http_list

from app.tools.webpage.service import request_public


_TOKEN = r"[!#$%&'*+.^_`|~0-9A-Za-z-]+"
_VALUE = rf'(?:{_TOKEN}|"(?:[^"\\\r\n]|\\[^\r\n])*")'
_DIRECTIVE = rf"{_TOKEN}(?:\s*=\s*{_VALUE})?"
_LIST = re.compile(rf"\s*{_DIRECTIVE}\s*(?:,\s*{_DIRECTIVE}\s*)*\Z")
_NUMERIC = {"max-age", "s-maxage", "stale-while-revalidate", "stale-if-error"}
_HEADERS = ("cache-control", "age", "date", "expires", "etag", "last-modified", "vary")


def _parse_cache_control(value):
    if len(value) > 16000:
        raise ValueError("Cache-Control header exceeds 16000 characters")
    directives, issues, grouped = [], [], {}
    syntax_valid = not value.strip() or _LIST.fullmatch(value) is not None
    if not syntax_valid:
        issues.append("Malformed Cache-Control syntax; policy interpretation is unknown.")
    parts = parse_http_list(value) if value.strip() else []
    if len(parts) > 100:
        raise ValueError("Cache-Control header exceeds 100 directives")
    for part in parts:
        name, separator, argument = part.partition("=")
        name, argument = name.strip().lower(), argument.strip()
        if not re.fullmatch(_TOKEN, name):
            continue
        if argument.startswith('"') and argument.endswith('"'):
            argument = argument[1:-1]
        argument = argument if separator else None
        directives.append({"name": name, "value": argument})
        grouped.setdefault(name, []).append(argument)
    for name, values in grouped.items():
        if len(values) > 1:
            issues.append(f"Repeated {name} directive; do not assume a single effective value.")
    seconds = {}
    for name in _NUMERIC:
        if name not in grouped:
            continue
        values = grouped[name]
        value = values[0]
        if (not syntax_valid or len(values) != 1 or value is None
                or not re.fullmatch(r"[0-9]{1,19}", value) or int(value) > 2**63 - 1):
            seconds[name] = None
            issues.append(f"Invalid or ambiguous {name}; no lifetime is inferred from it.")
        else:
            seconds[name] = int(value)
    for name in ("no-store", "public", "must-revalidate", "proxy-revalidate", "immutable", "no-transform", "must-understand"):
        if name in grouped and grouped[name] != [None]:
            issues.append(f"{name} must occur once without an argument.")
            syntax_valid = False
    if "public" in grouped and "private" in grouped:
        issues.append("public and private conflict; private restrictions are reported conservatively.")
    return directives, grouped, seconds, issues, syntax_valid


def inspect_cache(url):
    method = "HEAD"
    status, headers, _, final_url = request_public(url, method=method, headers={"Accept": "*/*"})
    if status in {405, 501}:
        method = "GET"
        status, headers, _, final_url = request_public(url, method=method, headers={"Accept": "*/*"})
    headers = {name.lower(): value for name, value in headers.items()}
    directives, grouped, seconds, issues, syntax_valid = _parse_cache_control(headers.get("cache-control", ""))

    def field_names(name):
        if name not in grouped or grouped[name] == [None]:
            return []
        value = grouped[name][0]
        if len(grouped[name]) != 1 or value is None:
            issues.append(f"Ambiguous {name} field list.")
            return None
        fields = [part.strip().lower() for part in value.split(",")]
        if not fields or any(not re.fullmatch(_TOKEN, part) for part in fields):
            issues.append(f"Invalid {name} field list.")
            return None
        return fields

    private_fields, no_cache_fields = field_names("private"), field_names("no-cache")
    scopes = {}
    for scope in ("browser", "shared"):
        storage = "not_prohibited" if syntax_valid else "unknown"
        if syntax_valid and "no-store" in grouped:
            storage = "conditional_must_understand" if "must-understand" in grouped else "prohibited"
        if syntax_valid and scope == "shared" and "private" in grouped and storage != "prohibited":
            storage = "conditional_field_exclusion" if private_fields else "prohibited"
            if private_fields is None:
                storage = "unknown"
        source = "s-maxage" if scope == "shared" and "s-maxage" in grouped else "max-age"
        if source in grouped:
            lifetime = seconds[source] if syntax_valid else None
        else:
            source = "expires" if headers.get("expires") else "unspecified"
            lifetime = None
        revalidation = "not_requested" if syntax_valid else "unknown"
        if syntax_valid and "no-cache" in grouped:
            revalidation = "listed_fields" if no_cache_fields else "required"
            if no_cache_fields is None:
                revalidation = "unknown"
        scopes[scope] = {
            "storage": storage, "freshness_source": source, "freshness_lifetime_seconds": lifetime,
            "revalidate_before_reuse": revalidation,
            "revalidate_when_stale": syntax_valid and ("must-revalidate" in grouped or
                (scope == "shared" and ("proxy-revalidate" in grouped or "s-maxage" in grouped))),
        }
    notes = ["Header-only interpretation, not a guarantee of cacheability or actual browser/CDN behavior.",
             "Lifetimes are declared values, not remaining TTL; Age, Date, request timing, and Expires are not evaluated.",
             "HEAD headers may differ from GET; GET is used only when HEAD returns 405 or 501."]
    if "must-understand" in grouped:
        notes.append("must-understand conditions storage on status-code support and can override no-store in supporting caches.")
    elif "no-store" in grouped:
        notes.append("no-store prohibits storage even if freshness or public directives are also present.")
    if "no-cache" in grouped:
        notes.append("no-cache requires validation before reuse (or for listed fields); it does not prohibit storage.")
    if headers.get("vary", "").strip() == "*":
        notes.append("Vary: * prevents reuse for subsequent requests.")
    if "immutable" in grouped:
        notes.append("immutable applies while fresh; it does not override no-store or no-cache.")
    return {
        "url": url, "final_url": final_url, "http_status": status, "method": method,
        "headers": {name: headers[name][:2000] for name in _HEADERS if name in headers},
        "directives": directives, "seconds": seconds,
        "private_fields": private_fields, "no_cache_fields": no_cache_fields,
        "scopes": scopes, "issues": issues, "valid_cache_control": syntax_valid and not issues,
        "notes": notes, "truncated": any(len(headers.get(name, "")) > 2000 for name in _HEADERS),
    }
