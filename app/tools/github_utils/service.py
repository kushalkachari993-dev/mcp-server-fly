import base64
import binascii
import json
import re
from urllib.parse import quote, urlencode

from app.tools.webpage.service import fetch_page


_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}\Z")
_REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
_JSON_TYPES = {"application/json", "application/vnd.github+json"}


def _repo_path(owner, repo):
    if not _OWNER.fullmatch(owner) or not _REPO.fullmatch(repo) or repo in {".", ".."}:
        raise ValueError("A valid GitHub owner and repository are required")
    return f"repos/{owner}/{repo}"


def _request(path, params=None):
    url = f"https://api.github.com/{path}"
    if params:
        url += "?" + urlencode(params)
    body, _, _ = fetch_page(url, media_types=_JSON_TYPES, allowed_host="api.github.com")
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("GitHub returned invalid JSON") from error


def _text(value, maximum):
    return value[:maximum] if isinstance(value, str) else ""


def read_file(owner, repo, path, ref, max_chars):
    root = _repo_path(owner, repo)
    if (not path or len(path) > 512 or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))):
        raise ValueError("Provide a repository-relative file path of at most 512 characters")
    if len(ref) > 200:
        raise ValueError("ref must not exceed 200 characters")
    suffix = "/".join(quote(part, safe="") for part in path.split("/"))
    data = _request(f"{root}/contents/{suffix}", {"ref": ref} if ref else None)
    if not isinstance(data, dict) or data.get("type") != "file" or data.get("encoding") != "base64":
        raise ValueError("GitHub did not return a regular file with inline content")
    if not isinstance(data.get("size"), int) or data["size"] > 1000000:
        raise ValueError("File exceeds the 1 MB limit")
    try:
        raw = base64.b64decode(data["content"], validate=False)
        if len(raw) > 1000000:
            raise ValueError("File exceeds the 1 MB limit")
        content = raw.decode("utf-8")
    except (KeyError, TypeError, binascii.Error, UnicodeDecodeError) as error:
        raise ValueError("GitHub file is not UTF-8 text") from error
    return {"owner": owner, "repo": repo, "path": path, "ref": ref or "default",
            "sha": data.get("sha", ""), "content": content[:max_chars],
            "truncated": len(content) > max_chars}


def read_issue(owner, repo, number):
    data = _request(f"{_repo_path(owner, repo)}/issues/{number}")
    if not isinstance(data, dict) or "number" not in data:
        raise ValueError("GitHub did not return an issue")
    if "pull_request" in data:
        raise ValueError("This number is a pull request; use get_github_pull_request")
    return {"number": data["number"], "title": _text(data.get("title"), 1000),
            "state": data.get("state", ""), "url": data.get("html_url", ""),
            "author": (data.get("user") or {}).get("login", ""),
            "labels": [_text(item.get("name"), 100) for item in data.get("labels", [])[:20]],
            "created_at": data.get("created_at"), "updated_at": data.get("updated_at"),
            "body": _text(data.get("body"), 12000),
            "truncated": len(data.get("body") or "") > 12000}


def read_pull_request(owner, repo, number, max_files):
    root = _repo_path(owner, repo)
    data = _request(f"{root}/pulls/{number}")
    if not isinstance(data, dict) or "number" not in data:
        raise ValueError("GitHub did not return a pull request")
    changed_files = data.get("changed_files", 0)
    files = []
    if changed_files:
        rows = _request(f"{root}/pulls/{number}/files", {"per_page": max_files})
        if not isinstance(rows, list):
            raise ValueError("GitHub did not return pull request files")
        files = [{"path": _text(row.get("filename"), 500), "status": row.get("status", ""),
                  "additions": row.get("additions", 0), "deletions": row.get("deletions", 0)}
                 for row in rows[:max_files]]
    return {"number": data["number"], "title": _text(data.get("title"), 1000),
            "state": data.get("state", ""), "draft": data.get("draft", False),
            "merged": data.get("merged", False), "url": data.get("html_url", ""),
            "author": (data.get("user") or {}).get("login", ""),
            "base": (data.get("base") or {}).get("ref", ""),
            "head": (data.get("head") or {}).get("ref", ""),
            "body": _text(data.get("body"), 12000),
            "changed_files": changed_files, "files": files,
            "truncated": changed_files > len(files) or len(data.get("body") or "") > 12000}


def list_releases(owner, repo, limit):
    rows = _request(f"{_repo_path(owner, repo)}/releases", {"per_page": limit + 1})
    if not isinstance(rows, list):
        raise ValueError("GitHub did not return releases")
    return {"owner": owner, "repo": repo,
            "releases": [{"tag": _text(row.get("tag_name"), 200),
                          "name": _text(row.get("name"), 500),
                          "url": row.get("html_url", ""),
                          "published_at": row.get("published_at"),
                          "prerelease": row.get("prerelease", False),
                          "body": _text(row.get("body"), 4000)} for row in rows[:limit]],
            "truncated": len(rows) > limit}
