import json
import re
from urllib.parse import quote

from app.tools.webpage.service import fetch_page


_PROJECT = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,198}[A-Za-z0-9])?\Z")


def _text(value, maximum):
    return value[:maximum] if isinstance(value, str) else ""


def get_package(name):
    if not _PROJECT.fullmatch(name):
        raise ValueError("Provide a valid PyPI project name")
    url = f"https://pypi.org/pypi/{quote(name, safe='')}/json"
    body, _, _ = fetch_page(url, media_types={"application/json"}, allowed_host="pypi.org")
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("PyPI returned invalid JSON") from error
    info = data.get("info") if isinstance(data, dict) else None
    if not isinstance(info, dict) or not isinstance(info.get("version"), str):
        raise ValueError("PyPI did not return project metadata")
    dependencies = info.get("requires_dist") or []
    project_urls = info.get("project_urls") or {}
    if (not isinstance(dependencies, list) or not isinstance(project_urls, dict)
            or any(not isinstance(item, str) for item in dependencies)):
        raise ValueError("PyPI returned invalid dependency or project URL metadata")
    links = {str(key)[:100]: _text(value, 1000)
             for key, value in list(project_urls.items())[:10]}
    return {"name": _text(info.get("name"), 200),
            "version": _text(info["version"], 100),
            "summary": _text(info.get("summary"), 1000),
            "requires_python": _text(info.get("requires_python"), 200),
            "dependencies": [_text(item, 500) for item in dependencies[:30]],
            "project_urls": links,
            "license": _text(info.get("license_expression") or info.get("license"), 300),
            "url": _text(info.get("package_url") or url, 1000),
            "truncated": len(dependencies) > 30 or len(project_urls) > 10}
