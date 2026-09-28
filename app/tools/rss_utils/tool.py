import json
from functools import partial
from urllib.parse import urljoin, urlsplit

import anyio
import feedparser
import urllib3
from bs4 import BeautifulSoup

from app.tools.webpage.service import fetch_page


_FEED_TYPES = {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml", "text/plain"}


def _web_link(value, base_url):
    try:
        link = urljoin(base_url, value)
        parts = urlsplit(link)
        if (parts.scheme in {"http", "https"} and parts.hostname
                and parts.username is None and parts.password is None and len(link) <= 4096):
            return link
    except ValueError:
        pass
    return ""


def _parse_feed(body, content_type, url, limit):
    # Parse bytes only: feedparser must never download a URL or open a local file.
    parsed = feedparser.parse(body, response_headers={"content-type": content_type, "content-location": url})
    if not parsed.version:
        raise ValueError("Response is not a recognized RSS or Atom feed")
    entries = []
    for entry in parsed.entries[:limit]:
        summary = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ", strip=True)
        published = entry["published"] if "published" in entry else entry.get("updated", "")
        entries.append({"title": entry.get("title", "")[:1000],
                        "url": _web_link(entry.get("link", ""), url),
                        "published": published[:200],
                        "summary": summary[:2000]})
    return {"url": url, "title": parsed.feed.get("title", "")[:1000],
            "feed_type": parsed.version, "entries": entries,
            "truncated": len(parsed.entries) > limit,
            "parse_warning": bool(parsed.get("bozo"))}


def register(mcp):

    @mcp.tool()
    async def read_rss_feed(url: str, limit: int = 10) -> str:
        """Read up to 50 RSS/Atom entries from a public URL, in feed order.
        Returns title, URL, publication string, and plain-text summary per entry.
        Uses the shared public-only fetcher with a 1 MB download cap. A parse_warning
        marks recoverable malformed feeds. Fetches on demand; does not monitor feeds.
        """
        try:
            if not 1 <= limit <= 50:
                raise ValueError("limit must be between 1 and 50")
            body, content_type, final_url = await anyio.to_thread.run_sync(partial(fetch_page, url, media_types=_FEED_TYPES))
            result = await anyio.to_thread.run_sync(_parse_feed, body, content_type, final_url, limit)
            return json.dumps(result, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError, LookupError) as error:
            return f"Error: {error}"
