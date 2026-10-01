from io import BytesIO
from urllib.parse import urlsplit
from xml.etree import ElementTree

from app.tools.webpage.service import fetch_page, request_public


_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_XML_TYPES = {"application/xml", "text/xml", "text/plain"}


def _robots_url(site_url):
    parts = urlsplit(site_url.strip())
    if (parts.scheme != "https" or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.port not in (None, 443)):
        raise ValueError("Provide a public HTTPS website URL on port 443")
    hostname = parts.hostname.encode("idna").decode("ascii").rstrip(".").lower()
    return f"https://{hostname}/robots.txt"


def _parse_robots(body, url, max_rules):
    text = body.decode("utf-8-sig", errors="replace")
    groups = []
    sitemaps = []
    current = None
    rule_count = 0
    truncated = False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            current = None
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        key, value = key.strip().lower(), value.strip()
        if key == "sitemap":
            if value and len(sitemaps) < 20:
                sitemaps.append(value[:1000])
                truncated |= len(value) > 1000
            elif value:
                truncated = True
        elif key == "user-agent" and value:
            if current is None or current["rules"]:
                if len(groups) >= 50:
                    truncated = True
                    current = None
                    continue
                current = {"user_agents": [], "rules": []}
                groups.append(current)
            if len(current["user_agents"]) < 20:
                current["user_agents"].append(value[:100])
                truncated |= len(value) > 100
            else:
                truncated = True
        elif key in {"allow", "disallow"} and current is not None:
            if rule_count >= max_rules:
                truncated = True
                continue
            current["rules"].append({"directive": key, "path": value[:300]})
            rule_count += 1
            truncated |= len(value) > 300
    return {"url": url, "found": True, "groups": groups, "sitemaps": sitemaps,
            "truncated": truncated, "note": "Rules are listed, not evaluated for a user agent or path"}


def inspect_robots(site_url, max_rules):
    url = _robots_url(site_url)
    status, headers, body, final_url = request_public(url, headers={"Accept": "text/plain"})
    if 400 <= status < 500:
        return {"url": final_url, "found": False, "http_status": status,
                "groups": [], "sitemaps": [], "truncated": False}
    if not 200 <= status < 300:
        raise ValueError(f"robots.txt returned HTTP {status}")
    content_type = next((value.lower().split(";", 1)[0].strip()
                         for key, value in headers.items() if key.lower() == "content-type"), "")
    if content_type != "text/plain":
        raise ValueError("robots.txt must have text/plain content type")
    return _parse_robots(body, final_url, max_rules)


def _valid_location(value):
    if not value or len(value) > 4096:
        return False
    try:
        parts = urlsplit(value)
        port = parts.port
        return (parts.scheme in {"http", "https"} and bool(parts.hostname)
                and parts.username is None and parts.password is None
                and (port is None or port > 0))
    except ValueError:
        return False


def _parse_sitemap(body, url, limit):
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("Sitemaps with DTDs or entity declarations are not supported")
    try:
        body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Sitemap must be UTF-8 XML") from error
    kind = None
    namespace = None
    depth = 0
    nodes = 0
    entries = []
    entry_chars = 0
    invalid_entries = 0
    truncated = False
    try:
        for event, element in ElementTree.iterparse(BytesIO(body), events=("start", "end")):
            if event == "start":
                depth += 1
                nodes += 1
                if nodes > 10000 or depth > 30:
                    raise ValueError("Sitemap exceeds XML node or nesting limits")
                if kind is None:
                    if element.tag.startswith("{"):
                        namespace, _, local = element.tag[1:].partition("}")
                        if namespace != _SITEMAP_NS:
                            raise ValueError("Unsupported sitemap XML namespace")
                        namespace = "{" + namespace + "}"
                    else:
                        namespace, local = "", element.tag
                    if local not in {"urlset", "sitemapindex"}:
                        raise ValueError("Expected a sitemap urlset or sitemapindex")
                    kind = local
            else:
                entry_tag = namespace + ("url" if kind == "urlset" else "sitemap")
                if depth == 2 and element.tag == entry_tag:
                    location = (element.findtext(namespace + "loc") or "").strip()
                    if _valid_location(location):
                        lastmod = (element.findtext(namespace + "lastmod") or "").strip()
                        cost = len(location) + min(len(lastmod), 100) + 100
                        if len(entries) < limit and entry_chars + cost <= 100000:
                            entries.append({"url": location, "lastmod": lastmod[:100]})
                            entry_chars += cost
                            truncated |= len(lastmod) > 100
                        else:
                            truncated = True
                    else:
                        invalid_entries += 1
                    element.clear()
                elif depth == 2:
                    element.clear()
                depth -= 1
    except ElementTree.ParseError as error:
        raise ValueError("Invalid sitemap XML") from error
    return {"url": url, "kind": kind, "entries": entries,
            "invalid_entries": invalid_entries, "truncated": truncated}


def read_sitemap(url, limit):
    body, _, final_url = fetch_page(url, media_types=_XML_TYPES)
    return _parse_sitemap(body, final_url, limit)
