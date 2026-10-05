import json
import re
from collections import Counter
from urllib.parse import quote, urlencode

from app.tools.github_utils.service import _repo_path, _REF
from app.tools.public_inspection.service import _header
from app.tools.webpage.service import request_public


_SHA = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")


class _Text:
    def __init__(self):
        self.truncated = False

    def get(self, value, maximum=200):
        if not isinstance(value, str):
            return None
        self.truncated |= len(value) > maximum
        return value[:maximum]


def _request(root, suffix="", params=None, *, allow_empty_list=False):
    url = "https://api.github.com/" + root + suffix
    if params:
        url += "?" + urlencode(params)
    status, headers, body, _ = request_public(
        url, allowed_host="api.github.com", follow_redirects=False, timeout_seconds=25,
        headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"})
    if status == 204 and allow_empty_list:
        return [], headers
    if status != 200:
        raise ValueError(f"GitHub returned HTTP {status}; check the public repository, ref/number or rate limits")
    if _header(headers, "content-type").split(";", 1)[0].strip().lower() not in {
        "application/json", "application/vnd.github+json", "application/vnd.github.v3+json"
    }:
        raise ValueError("GitHub returned an unsupported content type")
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise ValueError("GitHub returned invalid JSON") from None
    return data, headers


def _number(value):
    if type(value) is not int or value < 1 or value > 2147483647:
        raise ValueError("number must be 1-2147483647")


def _integer(value):
    return value if type(value) is int and value >= 0 else None


def _boolean(value):
    return value if type(value) is bool else None


def _repository(data):
    if (not isinstance(data, dict) or type(data.get("id")) is not int or data["id"] < 1
            or data.get("private") is not False or not isinstance(data.get("full_name"), str)
            or not isinstance(data.get("default_branch"), str)):
        raise ValueError("GitHub did not return public repository metadata")
    text = _Text()
    license = data.get("license")
    topics = data.get("topics")
    if topics is None:
        topics = []
    if not isinstance(topics, list) or any(not isinstance(topic, str) for topic in topics):
        raise ValueError("GitHub returned invalid repository topics")
    result = {"id": data["id"], "full_name": text.get(data["full_name"]),
              "url": text.get(data.get("html_url"), 2000),
              "description": text.get(data.get("description"), 2000),
              "default_branch": text.get(data["default_branch"]),
              "visibility": "public", "archived": _boolean(data.get("archived")),
              "disabled": _boolean(data.get("disabled")), "fork": _boolean(data.get("fork")),
              "language": text.get(data.get("language"), 100),
              "stars": _integer(data.get("stargazers_count")), "forks": _integer(data.get("forks_count")),
              "subscribers": _integer(data.get("subscribers_count")),
              "open_issues_and_prs": _integer(data.get("open_issues_count")),
              "reported_size_kb": _integer(data.get("size")),
              "created_at": text.get(data.get("created_at"), 50),
              "updated_at": text.get(data.get("updated_at"), 50),
              "pushed_at": text.get(data.get("pushed_at"), 50),
              "topics": [text.get(topic, 100) for topic in topics[:50]],
              "license": {"key": text.get(license.get("key"), 100),
                          "spdx_id": text.get(license.get("spdx_id"), 100),
                          "name": text.get(license.get("name"), 200)} if isinstance(license, dict) else None}
    result["truncated"] = text.truncated or len(topics) > 50
    return result


def get_github_repository(owner, repo):
    data, _ = _request(_repo_path(owner, repo))
    return _repository(data)


def list_github_repository_tree(owner, repo, ref="", recursive=True, limit=200):
    root = _repo_path(owner, repo)
    if not 1 <= limit <= 500:
        raise ValueError("limit must be 1-500")
    if ref and not _REF.fullmatch(ref):
        raise ValueError("ref must be an ASCII branch, tag or SHA of at most 200 characters")
    if not ref:
        metadata, _ = _request(root)
        _repository(metadata)
        ref = metadata["default_branch"]
        if not ref or len(ref) > 200:
            raise ValueError("Repository has no supported default branch; supply an explicit ref")
    # Even recursive=false enables recursion in GitHub's API; omit it entirely.
    data, _ = _request(root, "/git/trees/" + quote(ref, safe=""), {"recursive": "1"} if recursive else None)
    if (not isinstance(data, dict) or not isinstance(data.get("tree"), list)
            or type(data.get("truncated")) is not bool
            or not isinstance(data.get("sha"), str) or not _SHA.fullmatch(data["sha"])):
        raise ValueError("GitHub returned invalid tree metadata")
    entries, text = [], _Text()
    for row in data["tree"]:
        if (not isinstance(row, dict) or not isinstance(row.get("path"), str)
                or not isinstance(row.get("sha"), str) or not _SHA.fullmatch(row["sha"])
                or not isinstance(row.get("type"), str) or row["type"] not in {"blob", "tree", "commit"}
                or not isinstance(row.get("mode"), str) or row["mode"] not in {"100644", "100755", "040000", "160000", "120000"}
                or (row["type"], row["mode"]) not in {("blob", "100644"), ("blob", "100755"),
                                                       ("blob", "120000"), ("tree", "040000"), ("commit", "160000")}
                or ("size" in row and _integer(row["size"]) is None)):
            raise ValueError("GitHub returned invalid tree entries")
        if len(entries) < limit:
            path = text.get(row["path"], 2000)
            entries.append({"path": path, "path_truncated": len(row["path"]) > 2000,
                            "type": row["type"], "mode": row["mode"], "sha": row["sha"],
                            "size_bytes": row.get("size"), "symlink": row["mode"] == "120000",
                            "submodule": row["type"] == "commit"})
    provider_truncated = data["truncated"]
    listing_truncated = len(data["tree"]) > limit
    return {"owner": owner, "repo": repo, "ref": ref, "tree_sha": data["sha"], "recursive": recursive,
            "provider_entry_count": len(data["tree"]), "entries": entries,
            "provider_truncated": provider_truncated, "listing_truncated": listing_truncated,
            "text_truncated": text.truncated,
            "truncated": provider_truncated or listing_truncated or text.truncated,
            "note": "Entries describe the returned tree, not file contents. Provider truncation means the inventory is incomplete. For large trees use recursive=false and fetch subtree SHAs separately."}


def _page(owner, repo, number, suffix, limit, page, max_body_chars):
    root = _repo_path(owner, repo)
    _number(number)
    if not 1 <= limit <= 50 or not 1 <= page <= 1000:
        raise ValueError("limit must be 1-50 and page 1-1000")
    if not 100 <= max_body_chars <= 10000:
        raise ValueError("max_body_chars must be 100-10000")
    rows, headers = _request(root, f"/pulls/{number}/{suffix}", {"per_page": limit, "page": page})
    if (not isinstance(rows, list) or len(rows) > limit or any(
        not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] < 1 for row in rows
    )):
        raise ValueError("GitHub returned invalid review metadata")
    has_more = bool(re.search(r';\s*rel="next"', _header(headers, "link")))
    result = {"owner": owner, "repo": repo, "number": number, "page": page,
              "has_more": has_more, "next_page": page + 1 if has_more and page < 1000 else None,
              "pagination_limit_reached": has_more and page == 1000}
    return rows, result


def _common(row, text, max_body_chars):
    user = row.get("user")
    return {"id": row["id"], "author": text.get(user.get("login"), 100) if isinstance(user, dict) else None,
            "author_association": text.get(row.get("author_association"), 50),
            "url": text.get(row.get("html_url"), 2000), "body": text.get(row.get("body"), max_body_chars),
            "body_truncated": isinstance(row.get("body"), str) and len(row["body"]) > max_body_chars,
            "commit_id": text.get(row.get("commit_id"), 64)}


def get_github_pr_reviews(owner, repo, number, limit=20, page=1, max_body_chars=2000):
    rows, result = _page(owner, repo, number, "reviews", limit, page, max_body_chars)
    reviews, states, text = [], Counter(), _Text()
    for row in rows:
        if not isinstance(row.get("state"), str) or not 1 <= len(row["state"]) <= 50:
            raise ValueError("GitHub returned invalid review state metadata")
        review = _common(row, text, max_body_chars)
        review["state"] = row["state"]
        review["submitted_at"] = text.get(row.get("submitted_at"), 50)
        reviews.append(review)
        states[row["state"]] += 1
    result.update({"reviews": reviews, "returned_reviews": len(reviews),
                   "page_state_counts": dict(states), "truncated": text.truncated,
                   "note": "Chronological review records on this page only; no effective approval, required-review or mergeability verdict. Reviewed commits may differ from the current PR head."})
    return result


def get_github_pr_review_comments(owner, repo, number, limit=20, page=1, max_body_chars=2000):
    rows, result = _page(owner, repo, number, "comments", limit, page, max_body_chars)
    comments, text = [], _Text()
    for row in rows:
        if not isinstance(row.get("path"), str):
            raise ValueError("GitHub returned invalid review comment path")
        comment = _common(row, text, max_body_chars)
        comment.update({"path": text.get(row["path"], 2000),
                        "path_truncated": len(row["path"]) > 2000,
                        "original_commit_id": text.get(row.get("original_commit_id"), 64),
                        "created_at": text.get(row.get("created_at"), 50),
                        "updated_at": text.get(row.get("updated_at"), 50),
                        "subject_type": text.get(row.get("subject_type"), 30),
                        "side": text.get(row.get("side"), 10), "start_side": text.get(row.get("start_side"), 10)})
        for key in ("pull_request_review_id", "in_reply_to_id", "line", "original_line", "start_line",
                    "original_start_line", "position", "original_position"):
            if row.get(key) is not None and _integer(row[key]) is None:
                raise ValueError("GitHub returned invalid review comment location or identity")
            comment[key] = row.get(key)
        comments.append(comment)
    result.update({"comments": comments, "returned_comments": len(comments), "truncated": text.truncated,
                   "note": "PR review comments only; conversation comments use get_github_issue_comments. Null/current/original locations are preserved without inferring outdated or resolved threads. Diff hunks are omitted."})
    return result
