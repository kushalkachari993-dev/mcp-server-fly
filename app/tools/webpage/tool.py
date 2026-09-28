import json
import re
from urllib.parse import urldefrag, urljoin, urlsplit

import anyio
import urllib3
from bs4 import BeautifulSoup

from .service import fetch_page


def _encoding(content_type):
    charset = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", content_type)
    return charset.group(1) if charset else "utf-8"


def _html_soup(body, content_type):
    if content_type.split(";", 1)[0].strip() not in {"text/html", "application/xhtml+xml"}:
        raise ValueError("An HTML webpage is required")
    return BeautifulSoup(body, "html.parser", from_encoding=_encoding(content_type))


def _extract_text(body: bytes, content_type: str):
    encoding = _encoding(content_type)
    if content_type.startswith("text/plain"):
        return "", body.decode(encoding, errors="replace").strip()
    soup = BeautifulSoup(body, "html.parser", from_encoding=encoding)
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for element in soup.select(
        'script,style,noscript,template,nav,header,footer,aside,[hidden],[aria-hidden="true"]'
    ):
        element.decompose()
    content = soup.find("article") or soup.find("main") or soup.body or soup
    lines = (re.sub(r"\s+", " ", line).strip() for line in content.get_text("\n", strip=True).splitlines())
    return title, "\n".join(line for line in lines if line)


def _extract_links(body, content_type, url, same_domain_only, limit):
    soup = _html_soup(body, content_type)
    base = soup.find("base", href=True)
    base_url = urljoin(url, base["href"]) if base else url
    domain = urlsplit(url).hostname.lower().rstrip(".")
    seen = set()
    links = []
    truncated = False
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith("#"):
            continue
        try:
            destination = urldefrag(urljoin(base_url, href))[0]
            parts = urlsplit(destination)
            if (parts.scheme not in {"http", "https"} or not parts.hostname
                    or parts.username is not None or parts.password is not None
                    or len(destination) > 4096):
                continue
            if same_domain_only and parts.hostname.lower().rstrip(".") != domain:
                continue
        except ValueError:
            continue
        if destination in seen:
            continue
        if len(links) == limit:
            truncated = True
            break
        seen.add(destination)
        label = anchor.get_text(" ", strip=True) or anchor.get("aria-label", "")
        if not label:
            image = anchor.find("img", alt=True)
            label = image["alt"] if image else ""
        links.append({"url": destination, "text": label[:1000]})
    return {"url": url, "links": links, "truncated": truncated}


def _span(cell, name, maximum):
    raw = str(cell.get(name, "1"))
    if len(raw) > 4 or not raw.isdigit() or not 1 <= int(raw) <= maximum:
        raise ValueError(f"Table {name} must be between 1 and {maximum}")
    return int(raw)


def _extract_tables(body, content_type, url, max_tables, max_rows):
    soup = _html_soup(body, content_type)
    # Nested layout tables are not treated as additional data tables.
    for nested in reversed(soup.select("table table")):
        nested.decompose()
    tables = []
    output_size = 0
    all_tables = soup.find_all("table")
    for table in all_tables[:max_tables]:
        grid = []
        pending = {}
        has_headers = False
        truncated = False
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            if not cells and not pending:
                continue
            if not grid:
                has_headers = bool(cells) and all(cell.name == "th" for cell in cells)
            if len(grid) >= max_rows + int(has_headers):
                truncated = True
                break
            values = {column: text for column, (text, remaining) in pending.items()}
            next_pending = {column: (text, remaining - 1) for column, (text, remaining) in pending.items() if remaining > 1}
            column = 0
            for cell in cells:
                while column in values:
                    column += 1
                colspan = _span(cell, "colspan", 50)
                rowspan = _span(cell, "rowspan", 1000)
                if column + colspan > 50:
                    raise ValueError("Tables must not exceed 50 columns")
                text = cell.get_text(" ", strip=True)
                if len(text) > 2000:
                    truncated = True
                for index in range(column, column + colspan):
                    if index in values:
                        raise ValueError("Overlapping table spans are not supported")
                    values[index] = text[:2000]
                    if rowspan > 1:
                        next_pending[index] = (text[:2000], rowspan - 1)
                column += colspan
            pending = next_pending
            width = max(values, default=-1) + 1
            expanded_row = [values.get(index, "") for index in range(width)]
            output_size += len(json.dumps(expanded_row))
            if output_size > 200000:
                raise ValueError("Extracted tables exceed the 200000-character output limit; reduce max_rows or max_tables")
            grid.append(expanded_row)
        width = max((len(row) for row in grid), default=0)
        grid = [row + [""] * (width - len(row)) for row in grid]
        headers = grid.pop(0) if has_headers else [f"column_{index + 1}" for index in range(width)]
        caption = table.find("caption", recursive=False)
        tables.append({"caption": caption.get_text(" ", strip=True)[:1000] if caption else "",
                       "headers": headers, "rows": grid, "truncated": truncated})
    result = {"url": url, "tables": tables,
              "truncated": len(all_tables) > max_tables or any(table["truncated"] for table in tables)}
    if len(json.dumps(result, indent=2)) > 200000:
        raise ValueError("Extracted tables exceed the 200000-character output limit; reduce max_rows or max_tables")
    return result


def register(mcp):

    @mcp.tool()
    async def get_webpage_text(url: str, max_chars: int = 12000) -> str:
        """Extract readable text from a public HTML or plain-text webpage.
        Returns JSON containing url, title, text, and truncated. Removes common
        navigation and scripts, and favors article/main content. JavaScript is not
        executed. Downloads at most 1 MB; max_chars must be between 100 and 50000.
        """
        if not 100 <= max_chars <= 50000:
            return "Error: max_chars must be between 100 and 50000"
        try:
            body, content_type, final_url = await anyio.to_thread.run_sync(fetch_page, url)
            title, text = await anyio.to_thread.run_sync(_extract_text, body, content_type)
            return json.dumps({
                "url": final_url, "title": title[:1000],
                "text": text[:max_chars], "truncated": len(text) > max_chars,
            }, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError, LookupError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def extract_webpage_links(url: str, same_domain_only: bool = False, limit: int = 100) -> str:
        """Extract up to 500 unique HTTP/HTTPS links with labels from public HTML.
        Resolves relative URLs and HTML base tags, removes fragments, and optionally
        keeps only the final page's exact hostname. Does not visit extracted links.
        Returns JSON with url, links, and truncated. JavaScript is not executed.
        """
        try:
            if not 1 <= limit <= 500:
                raise ValueError("limit must be between 1 and 500")
            body, content_type, final_url = await anyio.to_thread.run_sync(fetch_page, url)
            result = await anyio.to_thread.run_sync(_extract_links, body, content_type, final_url, same_domain_only, limit)
            return json.dumps(result, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError, LookupError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def extract_html_tables(url: str, max_tables: int = 5, max_rows: int = 100) -> str:
        """Extract public HTML tables as JSON headers and arrays of string cells.
        Supports positive rowspan/colspan; repeats spanned text and pads missing
        cells. An all-th first row becomes headers; later header rows remain data.
        Ignores nested tables. Limits: 20 tables, 1000 data rows/table, 50 columns,
        2000 characters/cell, 200000 output characters. Does not execute JavaScript.
        """
        try:
            if not 1 <= max_tables <= 20 or not 1 <= max_rows <= 1000:
                raise ValueError("max_tables must be 1-20 and max_rows must be 1-1000")
            body, content_type, final_url = await anyio.to_thread.run_sync(fetch_page, url)
            result = await anyio.to_thread.run_sync(_extract_tables, body, content_type, final_url, max_tables, max_rows)
            return json.dumps(result, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError, LookupError) as error:
            return f"Error: {error}"
