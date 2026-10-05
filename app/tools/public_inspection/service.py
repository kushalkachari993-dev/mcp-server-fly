import json
import re
import stat
import zipfile
from collections import Counter
from io import BytesIO
from urllib.parse import urljoin, urlsplit, urlunsplit

from app.tools.github_utils.service import _repo_path
from app.tools.webpage.service import fetch_page, request_public
from app.tools.webpage.tool import _html_soup


def _header(headers, name):
    return next((value for key, value in headers.items() if key.lower() == name.lower()), "")


def _github(owner, repo, number, suffix, accept):
    root = _repo_path(owner, repo)
    if number < 1 or number > 2147483647:
        raise ValueError("number must be 1-2147483647")
    url = f"https://api.github.com/{root}/{suffix.format(number=number)}"
    status, headers, body, _ = request_public(
        url, allowed_host="api.github.com", follow_redirects=False,
        headers={"Accept": accept, "X-GitHub-Api-Version": "2026-03-10"})
    if status != 200:
        raise ValueError(f"GitHub returned HTTP {status}; check the public repository, number or rate limits")
    return headers, body


def get_github_issue_comments(owner, repo, number, limit=20, page=1, max_body_chars=2000):
    if not 1 <= limit <= 50 or not 1 <= page <= 1000:
        raise ValueError("limit must be 1-50 and page 1-1000")
    if not 100 <= max_body_chars <= 10000:
        raise ValueError("max_body_chars must be 100-10000")
    headers, body = _github(owner, repo, number,
                            f"issues/{{number}}/comments?per_page={limit}&page={page}",
                            "application/vnd.github+json")
    if _header(headers, "content-type").split(";", 1)[0].strip().lower() not in {
        "application/json", "application/vnd.github+json", "application/vnd.github.v3+json"
    }:
        raise ValueError("GitHub returned an unsupported content type")
    try:
        rows = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("GitHub returned invalid JSON") from None
    if (not isinstance(rows, list) or len(rows) > limit
            or any(not isinstance(row, dict) or type(row.get("id")) is not int for row in rows)):
        raise ValueError("GitHub returned invalid issue comment metadata")
    comments, truncated = [], False
    def text(value, size):
        nonlocal truncated
        if not isinstance(value, str):
            return ""
        truncated |= len(value) > size
        return value[:size]
    for row in rows:
        user = row.get("user")
        comments.append({"id": row["id"], "url": text(row.get("html_url"), 2000),
                         "author": text(user.get("login"), 100) if isinstance(user, dict) else None,
                         "author_association": text(row.get("author_association"), 50),
                         "created_at": text(row.get("created_at"), 50),
                         "updated_at": text(row.get("updated_at"), 50),
                         "body": text(row.get("body"), max_body_chars),
                         "body_truncated": isinstance(row.get("body"), str) and len(row["body"]) > max_body_chars})
    has_more = bool(re.search(r';\s*rel="next"', _header(headers, "link")))
    return {"owner": owner, "repo": repo, "number": number, "page": page,
            "comments": comments, "returned_comments": len(comments), "has_more": has_more,
            "next_page": page + 1 if has_more and page < 1000 else None,
            "pagination_limit_reached": has_more and page == 1000, "truncated": truncated,
            "comment_kind": "issue and PR conversation comments; excludes inline review comments"}


def get_github_pr_diff(owner, repo, number, max_chars=50000):
    if not 100 <= max_chars <= 150000:
        raise ValueError("max_chars must be 100-150000")
    headers, body = _github(owner, repo, number, "pulls/{number}", "application/vnd.github.diff")
    media_type = _header(headers, "content-type").split(";", 1)[0].strip().lower()
    if media_type not in {"text/plain", "text/x-diff", "application/vnd.github.diff", "application/vnd.github.v3.diff"}:
        raise ValueError("GitHub did not return a diff media type")
    try:
        diff = body.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("GitHub diff is not UTF-8 text") from None
    if diff and not diff.startswith("diff --git "):
        raise ValueError("GitHub did not return a standard Git diff")
    return {"owner": owner, "repo": repo, "number": number,
            "url": f"https://github.com/{owner}/{repo}/pull/{number}", "diff": diff[:max_chars],
            "downloaded_chars": len(diff), "returned_chars": min(len(diff), max_chars),
            "truncated": len(diff) > max_chars,
            "note": "Live provider diff; no commit snapshot or completeness guarantee beyond the downloaded response. Truncated text may end inside a hunk."}


def _archive_manifest(body, limit):
    if len(body) > 1000000:
        raise ValueError("Archive exceeds the 1 MB download limit")
    try:
        with zipfile.ZipFile(BytesIO(body)) as archive:
            entries = archive.infolist()
            if len(entries) > 5000:
                raise ValueError("Archive exceeds the 5000-entry limit")
            counts = Counter(info.orig_filename for info in entries)
            files, suspicious = [], 0
            for info in entries:
                path = info.orig_filename
                normalized = path.replace("\\", "/")
                path_warning = (normalized.startswith("/") or bool(re.match(r"^[A-Za-z]:", normalized))
                                or ".." in normalized.split("/") or "\x00" in path)
                suspicious += path_warning
                if len(files) < limit:
                    files.append({"path": path[:2000], "path_truncated": len(path) > 2000,
                                  "directory": info.is_dir(), "compressed_bytes": info.compress_size,
                                  "uncompressed_bytes": info.file_size, "compression_method": info.compress_type,
                                  "encrypted": bool(info.flag_bits & 1),
                                  "symlink": info.create_system == 3 and stat.S_ISLNK(info.external_attr >> 16),
                                  "duplicate_name": counts[path] > 1, "path_warning": bool(path_warning)})
            return {"entry_count": len(entries), "files": files,
                    "declared_compressed_bytes": sum(info.compress_size for info in entries),
                    "declared_uncompressed_bytes": sum(info.file_size for info in entries),
                    "duplicate_name_count": sum(count > 1 for count in counts.values()),
                    "path_warning_count": suspicious,
                    "truncated": len(entries) > limit or any(f["path_truncated"] for f in files),
                    "contents_verified": False,
                    "note": "Central-directory declarations only; no member decompression, CRC verification or extraction."}
    except (zipfile.BadZipFile, NotImplementedError, UnicodeDecodeError, OSError):
        raise ValueError("Response is not a supported ZIP archive") from None


def extract_archive_manifest(url, limit=100):
    if not 1 <= limit <= 500:
        raise ValueError("limit must be 1-500")
    body, _, final_url = fetch_page(url, media_types={
        "application/zip", "application/x-zip-compressed", "application/octet-stream"})
    result = _archive_manifest(body, limit)
    result["url"] = final_url
    result["downloaded_bytes"] = len(body)
    return result


def _action(value, base_url, document_url):
    try:
        destination = urljoin(base_url, value.strip()) if value.strip() else document_url
        parts = urlsplit(destination)
        if parts.scheme not in {"http", "https"} or not parts.hostname or len(destination) > 4096:
            return {"url": None, "supported": False, "query_omitted": bool(parts.query)}
        if parts.username is not None or parts.password is not None:
            return {"url": None, "supported": False, "query_omitted": bool(parts.query)}
        return {"url": urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
                "supported": True, "query_omitted": bool(parts.query)}
    except ValueError:
        return {"url": None, "supported": False, "query_omitted": False}


def _disabled(control):
    if control.has_attr("disabled"):
        return True
    for parent in control.parents:
        if parent.name == "fieldset" and parent.has_attr("disabled"):
            first_legend = parent.find("legend", recursive=False)
            if first_legend is None or not any(ancestor is first_legend for ancestor in control.parents):
                return True
    return False


def _label_text(label):
    chunks = []
    for node in label.find_all(string=True):
        # Wrapped textarea/select contents are values, not label text.
        if not any(parent.name in {"input", "select", "textarea", "button"} for parent in node.parents):
            chunks.append(str(node))
    return " ".join(" ".join(chunks).split())


def _forms(body, content_type, document_url, limit, max_fields):
    soup = _html_soup(body, content_type)
    stack, node_count = [(soup, 0)], 0
    while stack:
        node, depth = stack.pop()
        node_count += 1
        if node_count > 20000 or depth > 100:
            raise ValueError("HTML exceeds its 20000-node or 100-level nesting limit")
        if hasattr(node, "contents"):
            stack.extend((child, depth + 1) for child in node.contents)
    for element in soup.find_all(["script", "style", "template", "noscript"]):
        element.decompose()
    forms = soup.find_all("form")
    if len(forms) > 1000:
        raise ValueError("Page exceeds the 1000-form limit")
    ids = {}
    for element in soup.find_all(id=True):
        ids.setdefault(element["id"], []).append(element)
    base = soup.find("base", href=True)
    base_url = urljoin(document_url, base["href"]) if base else document_url
    owners = {id(form): [] for form in forms}
    unassociated = 0
    controls = soup.find_all(["input", "select", "textarea", "button"])
    if len(controls) > 10000:
        raise ValueError("Page exceeds the 10000-control limit")
    for control in controls:
        if control.has_attr("form"):
            matches = ids.get(control["form"], [])
            owner = matches[0] if matches and matches[0].name == "form" else None
        else:
            owner = control.find_parent("form")
        if owner is None or id(owner) not in owners:
            unassociated += 1
        else:
            owners[id(owner)].append(control)
    labels = {}
    for label in soup.find_all("label", attrs={"for": True}):
        labels.setdefault(label["for"], []).append(_label_text(label))
    result, shortened = [], False
    def text(value, size=200):
        nonlocal shortened
        value = value if isinstance(value, str) else ""
        shortened |= len(value) > size
        return value[:size]
    for index, form in enumerate(forms[:limit]):
        fields = []
        for control in owners[id(form)][:max_fields]:
            kind = control.get("type", "text" if control.name == "input" else "submit").lower()
            control_id = control.get("id", "")
            explicit = labels.get(control_id, []) if ids.get(control_id, [None])[0] is control else []
            wrapping = control.find_parent("label")
            label = " ".join(explicit) or (_label_text(wrapping) if wrapping else "") or control.get("aria-label", "")
            field = {"tag": control.name, "type": kind if control.name in {"input", "button"} else control.name,
                     "id": text(control_id), "name": text(control.get("name")), "label": text(label, 500),
                     "required_declared": control.has_attr("required"), "disabled": _disabled(control),
                     "readonly_declared": control.has_attr("readonly"), "multiple": control.has_attr("multiple")}
            if control.name == "select":
                field["option_count"] = len(control.find_all("option"))
            if kind in {"submit", "image"} and control.name in {"input", "button"}:
                if control.has_attr("formaction"):
                    field["action_override"] = _action(control["formaction"], base_url, document_url)
                if control.has_attr("formmethod"):
                    field["method_override"] = text(control["formmethod"].lower())
            fields.append(field)
        method = form.get("method", "get").lower()
        result.append({"index": index, "id": text(form.get("id")), "name": text(form.get("name")),
                       "method": method if method in {"get", "post", "dialog"} else "get",
                       "action": _action(form.get("action", ""), base_url, document_url),
                       "enctype": text(form.get("enctype", "application/x-www-form-urlencoded")),
                       "novalidate": form.has_attr("novalidate"), "field_count": len(owners[id(form)]),
                       "fields": fields, "fields_truncated": len(owners[id(form)]) > max_fields})
    return {"url": document_url, "form_count": len(forms), "forms": result,
            "unassociated_controls": unassociated, "values_included": False,
            "truncated": len(forms) > limit or shortened or any(f["fields_truncated"] for f in result),
            "note": "Static HTML declarations only; no JavaScript, submission or browser validity checks. Field values and action query strings are omitted; action destinations are not fetched or verified."}


def extract_html_forms(url, limit=20, max_fields=100):
    if not 1 <= limit <= 50 or not 1 <= max_fields <= 500:
        raise ValueError("limit must be 1-50 and max_fields 1-500")
    body, content_type, final_url = fetch_page(url, media_types={"text/html", "application/xhtml+xml"})
    return _forms(body, content_type, final_url, limit, max_fields)
