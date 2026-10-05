import base64
import binascii
import re
from urllib.parse import quote

from app.tools.github_utils.service import _repo_path, _REF
from app.tools.github_navigation.service import _request, _Text, _integer, _boolean, _SHA
from app.tools.public_inspection.service import _header


def _choice(value, choices, name):
    if value not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(choices))}")


def _ref(value, name="ref"):
    if value and (not _REF.fullmatch(value) or value.endswith("/") or ".." in value or "//" in value):
        raise ValueError(f"{name} must be an ASCII Git reference of at most 200 characters")


def _id(value, name="id"):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError(f"{name} must be a positive 64-bit integer")


def _object(data, identity="id"):
    if not isinstance(data, dict):
        raise ValueError("GitHub returned invalid object metadata")
    if identity == "sha":
        if not isinstance(data.get("sha"), str) or not _SHA.fullmatch(data["sha"]):
            raise ValueError("GitHub returned invalid commit SHA metadata")
    elif type(data.get(identity)) is not int or data[identity] < 1:
        raise ValueError("GitHub returned invalid object identity")
    return data


def _map(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("GitHub returned invalid nested metadata")
    return value


def _strings(value, text, maximum=20):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("GitHub returned invalid string-list metadata")
    text.truncated |= len(value) > maximum
    return [text.get(item, 200) for item in value[:maximum]]


def _person(value, text):
    user = _map(value)
    return {"login": text.get(user.get("login"), 100), "url": text.get(user.get("html_url"), 2000)}


def _page(owner, repo, suffix, limit, page, params=None, envelope=None, allow_empty=False):
    root = _repo_path(owner, repo)
    if not 1 <= limit <= 50 or not 1 <= page <= 1000:
        raise ValueError("limit must be 1-50 and page 1-1000")
    query = {**(params or {}), "per_page": limit, "page": page}
    data, headers = _request(root, suffix, query, allow_empty_list=allow_empty)
    total = None
    if envelope:
        if not isinstance(data, dict) or _integer(data.get("total_count")) is None:
            raise ValueError("GitHub returned invalid paginated metadata")
        total = data["total_count"]
        rows = data.get(envelope)
    else:
        rows = data
    if (not isinstance(rows, list) or len(rows) > limit or any(not isinstance(row, dict) for row in rows)
            or (total is not None and total < len(rows))):
        raise ValueError("GitHub returned invalid page rows")
    has_more = bool(re.search(r';\s*rel="next"', _header(headers, "link")))
    result = {"owner": owner, "repo": repo, "page": page, "scanned_items": len(rows),
              "has_more": has_more, "next_page": page + 1 if has_more and page < 1000 else None,
              "pagination_limit_reached": has_more and page == 1000}
    if total is not None:
        result["total_count"] = total
    return rows, result


def _finish(result, text, key, rows):
    result[key] = rows
    result["returned_items"] = len(rows)
    result["truncated"] = text.truncated
    return result


def list_github_issues(owner, repo, state="open", labels="", limit=20, page=1, max_body_chars=1000):
    _choice(state, {"open", "closed", "all"}, "state")
    if len(labels) > 500 or any(ord(c) < 32 for c in labels):
        raise ValueError("labels must be at most 500 characters without controls")
    if not 100 <= max_body_chars <= 10000:
        raise ValueError("max_body_chars must be 100-10000")
    params = {"state": state, "sort": "updated", "direction": "desc"}
    if labels:
        params["labels"] = labels
    rows, result = _page(owner, repo, "/issues", limit, page, params)
    issues, text, excluded = [], _Text(), 0
    for row in rows:
        _object(row)
        if "pull_request" in row:
            excluded += 1
            continue
        if type(row.get("number")) is not int or row["number"] < 1:
            raise ValueError("GitHub returned invalid issue number")
        label_rows = row.get("labels", [])
        if not isinstance(label_rows, list) or any(not isinstance(label, dict) for label in label_rows):
            raise ValueError("GitHub returned invalid issue labels")
        text.truncated |= len(label_rows) > 20
        issues.append({"id": row["id"], "number": row["number"], "title": text.get(row.get("title"), 1000),
                       "state": text.get(row.get("state"), 50), "url": text.get(row.get("html_url"), 2000),
                       "author": _person(row.get("user"), text), "comments": _integer(row.get("comments")),
                       "labels": [text.get(label.get("name"), 100) for label in label_rows[:20]],
                       "created_at": text.get(row.get("created_at"), 50), "updated_at": text.get(row.get("updated_at"), 50),
                       "closed_at": text.get(row.get("closed_at"), 50), "body": text.get(row.get("body"), max_body_chars),
                       "body_truncated": isinstance(row.get("body"), str) and len(row["body"]) > max_body_chars})
    result.update({"state": state, "labels_filter": labels, "excluded_pull_requests": excluded,
                   "note": "Page size counts provider rows before excluding PRs; a page can contain no issues while has_more is true."})
    return _finish(result, text, "issues", issues)


def list_github_pull_requests(owner, repo, state="open", base="", head="", limit=20, page=1):
    _choice(state, {"open", "closed", "all"}, "state")
    _ref(base, "base")
    if head:
        if len(head) > 240 or any(ord(c) < 33 for c in head):
            raise ValueError("head must be an owner:branch filter of at most 240 characters")
        pieces = head.split(":")
        if len(pieces) != 2:
            raise ValueError("head must be owner:branch")
        _ref(pieces[-1], "head branch")
        if not pieces[-1] or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", pieces[0]):
            raise ValueError("head must be owner:branch")
    params = {"state": state, "sort": "updated", "direction": "desc"}
    if base:
        params["base"] = base
    if head:
        params["head"] = head
    rows, result = _page(owner, repo, "/pulls", limit, page, params)
    pulls, text = [], _Text()
    for row in rows:
        _object(row)
        if type(row.get("number")) is not int or row["number"] < 1:
            raise ValueError("GitHub returned invalid PR number")
        branches = {}
        for key in ("base", "head"):
            branch = _map(row.get(key))
            branches[key] = {"ref": text.get(branch.get("ref")), "sha": text.get(branch.get("sha"), 64),
                             "label": text.get(branch.get("label"), 250)}
        pulls.append({"id": row["id"], "number": row["number"], "title": text.get(row.get("title"), 1000),
                      "state": text.get(row.get("state"), 50), "draft": _boolean(row.get("draft")),
                      "url": text.get(row.get("html_url"), 2000), "author": _person(row.get("user"), text),
                      "created_at": text.get(row.get("created_at"), 50), "updated_at": text.get(row.get("updated_at"), 50),
                      "closed_at": text.get(row.get("closed_at"), 50), "merged_at": text.get(row.get("merged_at"), 50), **branches})
    result.update({"state": state, "base_filter": base, "head_filter": head})
    return _finish(result, text, "pull_requests", pulls)


def list_github_branches(owner, repo, limit=20, page=1):
    rows, result = _page(owner, repo, "/branches", limit, page)
    text, branches = _Text(), []
    for row in rows:
        commit = _object(_map(row.get("commit")), "sha")
        if not isinstance(row.get("name"), str):
            raise ValueError("GitHub returned invalid branch name")
        branches.append({"name": text.get(row["name"]), "sha": commit["sha"], "protected": _boolean(row.get("protected"))})
    return _finish(result, text, "branches", branches)


def list_github_tags(owner, repo, limit=20, page=1):
    rows, result = _page(owner, repo, "/tags", limit, page)
    text, tags = _Text(), []
    for row in rows:
        commit = _object(_map(row.get("commit")), "sha")
        if not isinstance(row.get("name"), str):
            raise ValueError("GitHub returned invalid tag name")
        tags.append({"name": text.get(row["name"]), "commit_sha": commit["sha"]})
    result["note"] = "Provider order; no semantic version sorting or release association inferred."
    return _finish(result, text, "tags", tags)


def list_github_commits(owner, repo, ref="", path="", limit=20, page=1, max_message_chars=1000):
    _ref(ref)
    if (len(path) > 512 or "\\" in path or any(ord(c) < 32 for c in path)
            or (path and any(part in {"", ".", ".."} for part in path.split("/")))):
        raise ValueError("path must be a repository-relative path of at most 512 characters")
    if not 100 <= max_message_chars <= 10000:
        raise ValueError("max_message_chars must be 100-10000")
    params = {}
    if ref:
        params["sha"] = ref
    if path:
        params["path"] = path
    rows, result = _page(owner, repo, "/commits", limit, page, params)
    commits, text = [], _Text()
    for row in rows:
        _object(row, "sha")
        commit = _map(row.get("commit"))
        parents = row.get("parents", [])
        if not isinstance(parents, list):
            raise ValueError("GitHub returned invalid commit parents")
        for parent in parents:
            _object(parent, "sha")
        text.truncated |= len(parents) > 20
        verification = _map(commit.get("verification"))
        commits.append({"sha": row["sha"], "url": text.get(row.get("html_url"), 2000),
                        "author": _person(row.get("author"), text),
                        "authored_at": text.get(_map(commit.get("author")).get("date"), 50),
                        "committed_at": text.get(_map(commit.get("committer")).get("date"), 50),
                        "message": text.get(commit.get("message"), max_message_chars),
                        "message_truncated": isinstance(commit.get("message"), str) and len(commit["message"]) > max_message_chars,
                        "parent_shas": [parent["sha"] for parent in parents[:20]],
                        "provider_verified": _boolean(verification.get("verified")),
                        "verification_reason": text.get(verification.get("reason"), 100)})
    result.update({"ref": ref or "default branch", "path_filter": path,
                   "note": "Provider signature-verification declarations only; no independent cryptographic verification."})
    return _finish(result, text, "commits", commits)


def list_github_contributors(owner, repo, limit=20, page=1):
    rows, result = _page(owner, repo, "/contributors", limit, page, allow_empty=True)
    contributors, text = [], _Text()
    for row in rows:
        _object(row)
        if _integer(row.get("contributions")) is None:
            raise ValueError("GitHub returned invalid contributor counts")
        contributors.append({"id": row["id"], **_person(row, text), "type": text.get(row.get("type"), 50),
                             "contributions": row["contributions"]})
    result["note"] = "Provider contribution counts; anonymous contributors and email addresses omitted. Cached counts do not establish ownership or maintainer authority."
    return _finish(result, text, "contributors", contributors)


def get_github_repository_languages(owner, repo, limit=100):
    if not 1 <= limit <= 500:
        raise ValueError("limit must be 1-500")
    data, _ = _request(_repo_path(owner, repo), "/languages")
    if not isinstance(data, dict) or any(_integer(count) is None for count in data.values()):
        raise ValueError("GitHub returned invalid language byte counts")
    total, text = sum(data.values()), _Text()
    rows = [{"language": text.get(name, 100), "bytes": size,
             "percent": round(size / total * 100, 4) if total else 0}
            for name, size in sorted(data.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]]
    return {"owner": owner, "repo": repo, "total_reported_bytes": total, "language_count": len(data),
            "languages": rows, "truncated": len(data) > limit or text.truncated,
            "note": "GitHub language byte classification; not lines of code, runtime usage or dependency inventory."}


def get_github_repository_license(owner, repo, ref="", max_chars=20000):
    _ref(ref)
    if not 100 <= max_chars <= 50000:
        raise ValueError("max_chars must be 100-50000")
    data, _ = _request(_repo_path(owner, repo), "/license", {"ref": ref} if ref else None)
    if (not isinstance(data, dict) or data.get("encoding") != "base64"
            or not isinstance(data.get("content"), str) or not isinstance(data.get("sha"), str)
            or not _SHA.fullmatch(data["sha"]) or _integer(data.get("size")) is None
            or data["size"] > 1000000):
        raise ValueError("GitHub did not return an inline license file")
    try:
        raw = base64.b64decode("".join(data["content"].split()), validate=True)
        if len(raw) != data["size"]:
            raise ValueError("License content does not match the declared file size")
        content = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise ValueError("GitHub license content is not valid Base64 UTF-8 text") from None
    license = _map(data.get("license"))
    text = _Text()
    result = {"owner": owner, "repo": repo, "ref": ref or "default branch", "sha": data["sha"],
              "path": text.get(data.get("path"), 2000), "url": text.get(data.get("html_url"), 2000),
              "spdx_id": text.get(license.get("spdx_id"), 100), "name": text.get(license.get("name")),
              "content": text.get(content, max_chars), "content_truncated": len(content) > max_chars,
              "decoded_bytes": len(raw), "note": "Provider detected license file only; not a legal conclusion or repository-wide license audit."}
    result["truncated"] = text.truncated
    return result


def list_github_workflows(owner, repo, limit=20, page=1):
    rows, result = _page(owner, repo, "/actions/workflows", limit, page, envelope="workflows")
    text, workflows = _Text(), []
    for row in rows:
        _object(row)
        workflows.append({"id": row["id"], "name": text.get(row.get("name")), "path": text.get(row.get("path"), 2000),
                          "state": text.get(row.get("state"), 50), "url": text.get(row.get("html_url"), 2000),
                          "created_at": text.get(row.get("created_at"), 50), "updated_at": text.get(row.get("updated_at"), 50)})
    return _finish(result, text, "workflows", workflows)


def get_github_workflow_run(owner, repo, run_id):
    _id(run_id, "run_id")
    data, _ = _request(_repo_path(owner, repo), f"/actions/runs/{run_id}")
    _object(data)
    if data["id"] != run_id:
        raise ValueError("GitHub returned a different workflow run")
    text = _Text()
    pulls = data.get("pull_requests", [])
    if not isinstance(pulls, list):
        raise ValueError("GitHub returned invalid associated PR metadata")
    for pull in pulls:
        _object(pull, "number")
    text.truncated |= len(pulls) > 50
    result = {"owner": owner, "repo": repo, "id": data["id"],
              "workflow_id": _integer(data.get("workflow_id")), "run_number": _integer(data.get("run_number")),
              "run_attempt": _integer(data.get("run_attempt")), "name": text.get(data.get("name")),
              "title": text.get(data.get("display_title"), 500), "event": text.get(data.get("event"), 50),
              "status": text.get(data.get("status"), 50), "conclusion": text.get(data.get("conclusion"), 50),
              "head_branch": text.get(data.get("head_branch")), "head_sha": text.get(data.get("head_sha"), 64),
              "actor": _person(data.get("actor"), text), "triggering_actor": _person(data.get("triggering_actor"), text),
              "url": text.get(data.get("html_url"), 2000), "path": text.get(data.get("path"), 2000),
              "created_at": text.get(data.get("created_at"), 50), "updated_at": text.get(data.get("updated_at"), 50),
              "run_started_at": text.get(data.get("run_started_at"), 50),
              "pull_request_numbers": [pull["number"] for pull in pulls[:50]],
              "note": "Live run metadata, not logs, artifacts, required-check satisfaction or deployment proof."}
    result["truncated"] = text.truncated
    return result


def get_github_workflow_job(owner, repo, job_id, max_steps=50):
    _id(job_id, "job_id")
    if not 1 <= max_steps <= 100:
        raise ValueError("max_steps must be 1-100")
    data, _ = _request(_repo_path(owner, repo), f"/actions/jobs/{job_id}")
    _object(data)
    if data["id"] != job_id:
        raise ValueError("GitHub returned a different workflow job")
    steps = data.get("steps", [])
    if not isinstance(steps, list) or any(not isinstance(step, dict) or _integer(step.get("number")) is None for step in steps):
        raise ValueError("GitHub returned invalid workflow steps")
    text = _Text()
    rows = [{"number": step["number"], "name": text.get(step.get("name")), "status": text.get(step.get("status"), 50),
             "conclusion": text.get(step.get("conclusion"), 50), "started_at": text.get(step.get("started_at"), 50),
             "completed_at": text.get(step.get("completed_at"), 50)} for step in steps[:max_steps]]
    result = {"owner": owner, "repo": repo, "id": job_id, "run_id": _integer(data.get("run_id")),
              "name": text.get(data.get("name")), "workflow_name": text.get(data.get("workflow_name")),
              "status": text.get(data.get("status"), 50), "conclusion": text.get(data.get("conclusion"), 50),
              "head_sha": text.get(data.get("head_sha"), 64), "head_branch": text.get(data.get("head_branch")),
              "url": text.get(data.get("html_url"), 2000), "started_at": text.get(data.get("started_at"), 50),
              "completed_at": text.get(data.get("completed_at"), 50), "runner_name": text.get(data.get("runner_name")),
              "runner_group_name": text.get(data.get("runner_group_name")), "labels": _strings(data.get("labels"), text),
              "step_count": len(steps), "steps": rows, "steps_truncated": len(steps) > max_steps,
              "note": "Selected job/step metadata only; logs and secrets are not retrieved."}
    result["truncated"] = text.truncated or len(steps) > max_steps
    return result


def get_github_release(owner, repo, tag="", max_body_chars=12000):
    _ref(tag, "tag")
    if not 100 <= max_body_chars <= 50000:
        raise ValueError("max_body_chars must be 100-50000")
    suffix = "/releases/tags/" + quote(tag, safe="") if tag else "/releases/latest"
    data, _ = _request(_repo_path(owner, repo), suffix)
    _object(data)
    assets = data.get("assets", [])
    if not isinstance(assets, list):
        raise ValueError("GitHub returned invalid embedded release assets")
    text = _Text()
    result = {"owner": owner, "repo": repo, "id": data["id"], "selector": tag or "latest published release",
              "tag_name": text.get(data.get("tag_name")), "name": text.get(data.get("name")),
              "target_commitish": text.get(data.get("target_commitish")), "draft": _boolean(data.get("draft")),
              "prerelease": _boolean(data.get("prerelease")), "immutable": _boolean(data.get("immutable")),
              "author": _person(data.get("author"), text), "url": text.get(data.get("html_url"), 2000),
              "created_at": text.get(data.get("created_at"), 50), "published_at": text.get(data.get("published_at"), 50),
              "body": text.get(data.get("body"), max_body_chars),
              "body_truncated": isinstance(data.get("body"), str) and len(data["body"]) > max_body_chars,
              "embedded_asset_count": len(assets),
              "note": "Latest uses GitHub's published non-draft/non-prerelease selection, not semantic version ranking. Use release ID with list_github_release_assets; target_commitish may be a moving ref."}
    result["truncated"] = text.truncated
    return result


def list_github_release_assets(owner, repo, release_id, limit=20, page=1):
    _id(release_id, "release_id")
    rows, result = _page(owner, repo, f"/releases/{release_id}/assets", limit, page)
    assets, text = [], _Text()
    for row in rows:
        _object(row)
        assets.append({"id": row["id"], "name": text.get(row.get("name"), 500), "label": text.get(row.get("label"), 500),
                       "content_type": text.get(row.get("content_type"), 100), "state": text.get(row.get("state"), 50),
                       "size_bytes": _integer(row.get("size")), "download_count": _integer(row.get("download_count")),
                       "digest": text.get(row.get("digest"), 200),
                       "download_url": text.get(row.get("browser_download_url"), 2000),
                       "created_at": text.get(row.get("created_at"), 50), "updated_at": text.get(row.get("updated_at"), 50)})
    result.update({"release_id": release_id, "note": "Uploaded release asset metadata only; archives/binaries are not downloaded and declared digests are not verified. Auto-generated source archives are not uploaded assets."})
    return _finish(result, text, "assets", assets)
