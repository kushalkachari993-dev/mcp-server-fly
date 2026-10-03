import base64
import binascii
import json
import re
from urllib.parse import quote, urlencode

from app.tools.webpage.service import fetch_page


_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}\Z")
_REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
_JSON_TYPES = {"application/json", "application/vnd.github+json"}
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,199}\Z")


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


def list_directory(owner, repo, path, ref, limit):
    root = _repo_path(owner, repo)
    if (len(path) > 512 or "\\" in path or
            (path and any(part in {"", ".", ".."} for part in path.split("/")))):
        raise ValueError("Provide a repository-relative directory path of at most 512 characters")
    if len(ref) > 200:
        raise ValueError("ref must not exceed 200 characters")
    suffix = "/" + "/".join(quote(part, safe="") for part in path.split("/")) if path else ""
    rows = _request(f"{root}/contents{suffix}", {"ref": ref} if ref else None)
    if not isinstance(rows, list):
        raise ValueError("GitHub did not return a directory")
    entries = [{"name": _text(row.get("name"), 255),
                "path": _text(row.get("path"), 512),
                "type": _text(row.get("type"), 30),
                "size": row.get("size"),
                "sha": _text(row.get("sha"), 40),
                "url": _text(row.get("html_url"), 1000)}
               for row in rows[:limit] if isinstance(row, dict)]
    return {"owner": owner, "repo": repo, "path": path, "ref": ref or "default",
            "entries": entries, "truncated": len(rows) > limit}


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


def list_workflow_runs(owner, repo, branch, limit):
    root = _repo_path(owner, repo)
    if len(branch) > 200 or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in branch):
        raise ValueError("branch must be at most 200 characters without whitespace or control characters")
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    params = {"per_page": limit + 1}
    if branch:
        params["branch"] = branch
    data = _request(f"{root}/actions/runs", params)
    if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
        raise ValueError("GitHub did not return workflow runs")
    rows = data["workflow_runs"]
    total = data.get("total_count")
    if type(total) is not int or total < len(rows) or any(
        not isinstance(row, dict) or type(row.get("id")) is not int for row in rows
    ):
        raise ValueError("GitHub returned invalid workflow run metadata")
    truncated = total > limit or len(rows) > limit

    def text(value, maximum):
        nonlocal truncated
        if isinstance(value, str):
            truncated |= len(value) > maximum
        return _text(value, maximum)

    runs = [{"id": row["id"], "name": text(row.get("name"), 200),
             "title": text(row.get("display_title"), 500),
             "branch": text(row.get("head_branch"), 200), "sha": text(row.get("head_sha"), 64),
             "event": text(row.get("event"), 50), "status": text(row.get("status"), 50),
             "conclusion": text(row.get("conclusion"), 50) or None,
             "created_at": text(row.get("created_at"), 50),
             "updated_at": text(row.get("updated_at"), 50),
             "url": text(row.get("html_url"), 1000)} for row in rows[:limit]]
    return {"owner": owner, "repo": repo, "branch": branch,
            "total_count": total, "runs": runs, "truncated": truncated}


def list_workflow_jobs(owner, repo, run_id, limit, max_steps):
    root = _repo_path(owner, repo)
    if type(run_id) is not int or not 1 <= run_id <= 2**63 - 1:
        raise ValueError("run_id must be a positive 64-bit integer")
    if not 1 <= limit <= 20 or not 1 <= max_steps <= 50:
        raise ValueError("limit must be 1-20 and max_steps must be 1-50")
    data = _request(f"{root}/actions/runs/{run_id}/jobs", {"filter": "latest", "per_page": limit + 1})
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("GitHub did not return workflow jobs")
    rows, total = data["jobs"], data.get("total_count")
    if type(total) is not int or total < len(rows):
        raise ValueError("GitHub returned an invalid job count")
    truncated = total > limit or len(rows) > limit

    def text(value, maximum):
        nonlocal truncated
        if isinstance(value, str):
            truncated |= len(value) > maximum
        return _text(value, maximum)

    jobs = []
    for row in rows[:limit]:
        if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] < 1:
            raise ValueError("GitHub returned invalid job metadata")
        steps = row.get("steps", [])
        if not isinstance(steps, list) or any(
            not isinstance(step, dict) or type(step.get("number")) is not int or step["number"] < 0
            for step in steps
        ):
            raise ValueError("GitHub returned invalid step metadata")
        truncated |= len(steps) > max_steps
        jobs.append({
            "id": row["id"], "name": text(row.get("name"), 200),
            "status": text(row.get("status"), 50), "conclusion": text(row.get("conclusion"), 50) or None,
            "started_at": text(row.get("started_at"), 50) or None,
            "completed_at": text(row.get("completed_at"), 50) or None,
            "url": text(row.get("html_url"), 1000), "step_count": len(steps),
            "steps": [{"number": step["number"], "name": text(step.get("name"), 200),
                       "status": text(step.get("status"), 50),
                       "conclusion": text(step.get("conclusion"), 50) or None,
                       "started_at": text(step.get("started_at"), 50) or None,
                       "completed_at": text(step.get("completed_at"), 50) or None}
                      for step in steps[:max_steps]],
            "steps_truncated": len(steps) > max_steps,
        })
    return {"owner": owner, "repo": repo, "run_id": run_id, "filter": "latest",
            "total_count": total, "jobs": jobs, "truncated": truncated}


def compare_refs(owner, repo, base, head, max_commits, max_files):
    root = _repo_path(owner, repo)
    for ref in (base, head):
        if not _REF.fullmatch(ref) or ref.endswith("/") or ".." in ref or "//" in ref:
            raise ValueError("base and head must be valid branch, tag, or commit references")
    pair = f"{quote(base, safe='')}...{quote(head, safe='')}"
    data = _request(f"{root}/compare/{pair}", {"per_page": max_commits + 1})
    if not isinstance(data, dict) or not isinstance(data.get("commits"), list):
        raise ValueError("GitHub did not return a commit comparison")
    rows = data["commits"]
    files = data.get("files", [])
    if not isinstance(files, list):
        raise ValueError("GitHub did not return changed files")
    total_commits = data.get("total_commits", len(rows))
    if not isinstance(total_commits, int):
        total_commits = len(rows)
    return {
        "owner": owner, "repo": repo, "base": base, "head": head,
        "status": data.get("status", ""), "ahead_by": data.get("ahead_by", 0),
        "behind_by": data.get("behind_by", 0), "total_commits": total_commits,
        "url": data.get("html_url", ""),
        "commits": [{"sha": _text(row.get("sha"), 40),
                     "message": _text((row.get("commit") or {}).get("message"), 500),
                     "author": _text(((row.get("commit") or {}).get("author") or {}).get("name"), 100)}
                    for row in rows[:max_commits] if isinstance(row, dict)],
        "files": [{"path": _text(row.get("filename"), 500),
                   "status": _text(row.get("status"), 30),
                   "additions": row.get("additions", 0), "deletions": row.get("deletions", 0)}
                  for row in files[:max_files] if isinstance(row, dict)],
        "commits_truncated": total_commits > max_commits,
        "files_truncated": len(files) > max_files or len(files) >= 300,
    }


def read_commit(owner, repo, ref, max_files):
    if not _REF.fullmatch(ref) or ref.endswith("/") or ".." in ref or "//" in ref:
        raise ValueError("ref must be a valid branch, tag, or commit reference")
    data = _request(f"{_repo_path(owner, repo)}/commits/{quote(ref, safe='')}")
    if not isinstance(data, dict) or not isinstance(data.get("sha"), str) or not data["sha"]:
        raise ValueError("GitHub did not return a commit")
    commit = data.get("commit")
    if not isinstance(commit, dict):
        raise ValueError("GitHub returned invalid commit metadata")
    verification = commit.get("verification") or {}
    if not isinstance(verification, dict):
        raise ValueError("GitHub returned invalid verification metadata")
    files = data.get("files", [])
    if not isinstance(files, list):
        raise ValueError("GitHub returned invalid changed files")
    truncated = len(files) > max_files or len(files) >= 300
    rows = []
    for row in files[:max_files]:
        if not isinstance(row, dict) or not isinstance(row.get("filename"), str):
            raise ValueError("GitHub returned an invalid changed file")
        rows.append({"path": _text(row["filename"], 500), "status": _text(row.get("status"), 30),
                     "additions": row.get("additions", 0), "deletions": row.get("deletions", 0),
                     "changes": row.get("changes", 0)})
    author = commit.get("author") or {}
    committer = commit.get("committer") or {}
    stats = data.get("stats") or {}
    if not isinstance(author, dict) or not isinstance(committer, dict) or not isinstance(stats, dict):
        raise ValueError("GitHub returned invalid commit details")
    return {
        "owner": owner, "repo": repo, "ref": ref, "sha": data["sha"],
        "message": _text(commit.get("message"), 2000),
        "author": {"name": _text(author.get("name"), 200), "email": _text(author.get("email"), 300),
                   "date": _text(author.get("date"), 50)},
        "committer": {"name": _text(committer.get("name"), 200), "email": _text(committer.get("email"), 300),
                      "date": _text(committer.get("date"), 50)},
        "verification": {"verified": verification.get("verified", False),
                          "reason": _text(verification.get("reason"), 100)},
        "parents": [_text(parent.get("sha"), 64) for parent in data.get("parents", [])[:10]
                    if isinstance(parent, dict)],
        "stats": {"additions": stats.get("additions", 0), "deletions": stats.get("deletions", 0),
                  "total": stats.get("total", 0)},
        "url": _text(data.get("html_url"), 1000), "files": rows, "truncated": truncated,
    }
