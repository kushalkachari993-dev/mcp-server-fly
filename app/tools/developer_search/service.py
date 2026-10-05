import codecs
import json
import os
import re
from urllib.parse import urlencode

from app.tools.github_utils.service import _request, _text
from app.tools.webpage.service import request_public


def _query(query, limit, page):
    if not query.strip() or len(query) > 500 or any(ord(c) < 32 for c in query):
        raise ValueError("query must be 1-500 characters without control characters")
    if not 1 <= limit <= 50 or not 1 <= page <= 20 or page * limit > 1000:
        raise ValueError("limit must be 1-50 and page 1-20 (at most 1000 results)")
    return {"q": query, "per_page": limit, "page": page}


def _response(data):
    if (not isinstance(data, dict) or not isinstance(data.get("items"), list)
            or type(data.get("total_count")) is not int or data["total_count"] < 0
            or type(data.get("incomplete_results")) is not bool
            or any(not isinstance(row, dict) for row in data["items"])):
        raise ValueError("GitHub returned invalid search metadata")
    return data["items"]


def search_github_issues(query, limit=10, page=1):
    params = _query(query, limit, page)
    # Anonymous requests cannot return private repositories. Exclude PRs explicitly.
    if re.search(r"\bOR\b|\bis\s*:\s*pr\b", query, re.I):
        raise ValueError("Issue search does not support OR or pull-request qualifiers")
    params["q"] = query + " is:issue"
    data = _request("search/issues", params)
    rows = _response(data)
    results = []
    for row in rows[:limit]:
        if "pull_request" in row:
            raise ValueError("GitHub returned pull requests for an issue-only search")
        results.append({"number": row.get("number"), "title": _text(row.get("title"), 1000),
                        "state": _text(row.get("state"), 30), "url": _text(row.get("html_url"), 2000),
                        "repository_url": _text(row.get("repository_url"), 2000),
                        "body": _text(row.get("body"), 2000),
                        "body_truncated": isinstance(row.get("body"), str) and len(row["body"]) > 2000,
                        "updated_at": _text(row.get("updated_at"), 50)})
    return {"total_count": data["total_count"], "incomplete_results": data["incomplete_results"],
            "page": page, "results": results,
            "has_more": page * limit < min(data["total_count"], 1000)}


def search_github_code(query, limit=10, page=1):
    params = _query(query, limit, page)
    # Keep token-backed searches public and avoid OR escaping the added qualifier.
    if re.search(r"\bOR\b|\bis\s*:\s*private\b", query, re.I):
        raise ValueError("Code search does not support OR or private visibility qualifiers")
    params["q"] = query + " is:public"
    token = os.environ.get("GITHUB_SEARCH_TOKEN", "")
    if not token:
        raise ValueError("Configure GITHUB_SEARCH_TOKEN on the server to enable code search")
    if len(token) > 1000 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError("GITHUB_SEARCH_TOKEN has an invalid format")
    url = "https://api.github.com/search/code?" + urlencode(params)
    try:
        status, headers, body, _ = request_public(
            url, headers={"Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
                          "X-GitHub-Api-Version": "2026-03-10"},
            allowed_host="api.github.com", follow_redirects=False, timeout_seconds=15)
    except Exception:
        raise ValueError("GitHub code search request failed") from None
    if status != 200:
        raise ValueError(f"GitHub code search returned HTTP {status}; check authentication, query or rate limits")
    content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
    if content_type.split(";", 1)[0].lower() not in {"application/json", "application/vnd.github+json"}:
        raise ValueError("GitHub returned an unsupported content type")
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("GitHub returned invalid JSON") from None
    rows = _response(data)
    results, excluded = [], 0
    for row in rows[:limit]:
        repo = row.get("repository")
        if not isinstance(repo, dict) or repo.get("private") is not False:
            excluded += 1
            continue
        results.append({"name": _text(row.get("name"), 255), "path": _text(row.get("path"), 2000),
                        "sha": _text(row.get("sha"), 64), "url": _text(row.get("html_url"), 2000),
                        "repository": _text(repo.get("full_name"), 200)})
    return {"total_count": data["total_count"], "incomplete_results": data["incomplete_results"],
            "page": page, "results": results, "excluded_nonpublic_or_unknown": excluded,
            "has_more": page * limit < min(data["total_count"], 1000), "content_included": False}


_HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)\Z")


def _path(text, prefix=False):
    if text.startswith('"'):
        if not text.endswith('"'):
            raise ValueError("Malformed quoted Git path")
        try:
            # Git C-quotes non-ASCII UTF-8 bytes using octal escapes.
            text = codecs.escape_decode(text[1:-1].encode("utf-8"))[0].decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Unsupported Git path encoding") from None
    if prefix and text.startswith(("a/", "b/")):
        text = text[2:]
    return None if text == "/dev/null" else text


def _header_paths(line):
    rest = line[len("diff --git "):]
    if rest.startswith('"'):
        match = re.fullmatch(r'("(?:[^"\\]|\\.)*") ("(?:[^"\\]|\\.)*"|b/.*)', rest)
        if not match:
            raise ValueError("Malformed Git diff header")
        return _path(match[1], True), _path(match[2], True)
    if ' "b/' in rest:
        a, b = rest.split(' "b/', 1)
        return _path(a, True), _path('"b/' + b, True)
    if " b/" not in rest or not rest.startswith("a/"):
        raise ValueError("Git diff must use standard a/ and b/ prefixes")
    a, b = rest.split(" b/", 1)
    return _path(a, True), _path("b/" + b, True)


def inspect_git_diff(content, limit=100):
    if len(content) > 200000:
        raise ValueError("Input must not exceed 200000 characters")
    if not 1 <= limit <= 500:
        raise ValueError("limit must be 1-500")
    files, current, remaining, binary_payload = [], None, None, False
    for line in content.split("\n"):
        if remaining is not None and (remaining[0] or remaining[1]):
            if line.startswith("\\ No newline at end of file"):
                continue
            marker = line[:1]
            if marker not in {" ", "+", "-"}:
                raise ValueError("Malformed or incomplete diff hunk")
            old, new = marker != "+", marker != "-"
            remaining[0] -= old
            remaining[1] -= new
            if min(remaining) < 0:
                raise ValueError("Diff hunk counts do not match its content")
            current["additions"] += marker == "+"
            current["deletions"] += marker == "-"
            continue
        if line.startswith(("diff --cc ", "diff --combined ", "@@@")):
            raise ValueError("Combined merge diffs are unsupported")
        if line.startswith("diff --git "):
            a, b = _header_paths(line)
            current = {"before_path": a, "after_path": b, "status": "modified", "additions": 0,
                       "deletions": 0, "hunks": 0, "hunk_contexts": [], "binary": False}
            files.append(current)
            if len(files) > 500:
                raise ValueError("Diff exceeds 500 files")
            remaining, binary_payload = None, False
        elif current is None:
            if line.startswith(("--- ", "+++ ", "@@")):
                raise ValueError("A Git diff --git header is required")
            # Ignore mail-format preamble and commit metadata.
            continue
        elif binary_payload:
            continue
        elif line.startswith("@@"):
            match = _HUNK.fullmatch(line)
            if not match:
                raise ValueError("Malformed unified hunk header")
            remaining = [int(match[2]) if match[2] is not None else 1,
                         int(match[4]) if match[4] is not None else 1]
            current["hunks"] += 1
            if match[5].strip() and len(current["hunk_contexts"]) < 20:
                current["hunk_contexts"].append(match[5].strip()[:200])
        elif line.startswith("--- "):
            current["before_path"] = _path(line[4:], True)
        elif line.startswith("+++ "):
            current["after_path"] = _path(line[4:], True)
        elif line.startswith("new file mode "):
            current["status"] = "added"
        elif line.startswith("deleted file mode "):
            current["status"] = "deleted"
        elif line.startswith("rename from "):
            current["before_path"] = _path(line[12:])
            current["status"] = "renamed"
        elif line.startswith("rename to "):
            current["after_path"] = _path(line[10:])
        elif line.startswith("copy from "):
            current["before_path"] = _path(line[10:])
            current["status"] = "copied"
        elif line.startswith("copy to "):
            current["after_path"] = _path(line[8:])
        elif line.startswith("old mode "):
            current["old_mode"] = line[9:]
        elif line.startswith("new mode "):
            current["new_mode"] = line[9:]
        elif line.startswith("Binary files ") or line == "GIT binary patch":
            current["binary"] = True
            binary_payload = line == "GIT binary patch"
        elif line.startswith(("+", "-", " ")) and line != "-- ":
            raise ValueError("Unexpected content outside a diff hunk")
    if remaining is not None and any(remaining):
        raise ValueError("Incomplete diff hunk")
    if content.strip() and not files:
        raise ValueError("No Git diff file sections found")
    for file in files:
        if file["before_path"] is None:
            file["status"] = "added"
        elif file["after_path"] is None:
            file["status"] = "deleted"
    return {"file_count": len(files), "additions": sum(f["additions"] for f in files),
            "deletions": sum(f["deletions"] for f in files), "files": files[:limit],
            "truncated": len(files) > limit, "symbols_inferred": False,
            "note": "Hunk contexts are supplied labels, not verified changed symbols. Binary line counts are unavailable."}
