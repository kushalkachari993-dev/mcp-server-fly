import re
from collections import Counter

from app.tools.performance_utils.service import _har_url, _json_report
from app.tools.report_utils.service import _Summary, _array, _mapping, _name


_SCHEMAS = {
    "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    "https://schema.postman.com/json/collection/v2.1.0/collection.json",
    "https://schema.getpostman.com/json/draft-07/collection/v2.1.0/",
    "https://schema.postman.com/collection/json/v2.1.0/draft-07/collection.json",
}
_AUTH_TYPES = {"apikey", "awsv4", "basic", "bearer", "digest", "edgegrid", "hawk", "noauth", "oauth1", "oauth2", "ntlm"}


def _auth(value):
    if value is None:
        return None
    kind = _mapping(value).get("type")
    if not isinstance(kind, str) or kind not in _AUTH_TYPES:
        raise ValueError("Unsupported Postman v2.1 auth type; values omitted")
    return kind


def _target(value, summary):
    if value is None:
        return {"status": "missing", "scheme": None, "host": None, "port": None, "path": None}
    source = "string"
    if isinstance(value, dict):
        source = "raw"
        if "raw" not in value:
            return {"status": "components_only", "scheme": None, "host": None, "port": None, "path": None}
        value = value["raw"]
    if not isinstance(value, str) or len(value) > 10000 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Postman URL must be text of at most 10000 characters without controls")
    if "{{" in value or "}}" in value:
        return {"status": "unresolved_template", "scheme": None, "host": None, "port": None, "path": None}
    target = _har_url(value, summary)
    supported = target.pop("supported")
    return {"status": "http" if supported else "unsupported", "source": source, **target}


def inspect_collection(content, limit):
    summary, data = _Summary(content, limit), _json_report(content)
    info = _mapping(data.get("info"))
    schema = info.get("schema")
    if not isinstance(schema, str) or schema not in _SCHEMAS:
        raise ValueError("Supply a Postman Collection v2.1 export using a supported official schema URL")
    name = summary.text(info.get("name"))
    if name is None:
        raise ValueError("Postman collection info.name is required")
    items = _array(data.get("item"), 1000)
    collection_auth = _auth(data.get("auth"))
    folders, requests, methods, auth_counts, statuses = [], [], Counter(), Counter(), Counter()
    item_count = 0

    def visit(children, ancestry, inherited, inherited_source):
        nonlocal item_count
        for raw in children:
            item_count += 1
            if item_count > 1000:
                raise ValueError("Postman collection exceeds 1000 total folder/request items")
            item = _mapping(raw)
            item_name = summary.text(item.get("name"))
            if ("item" in item) == ("request" in item):
                raise ValueError("Postman items must be a folder or a request, not both or neither")
            if "item" in item:
                declared = _auth(item.get("auth"))
                effective = declared if declared is not None else inherited
                source = "folder" if declared is not None else inherited_source
                index = len(folders)
                folders.append({"index": index, "name": item_name, "parent_folder_index": ancestry[-1] if ancestry else None,
                                "declared_auth_type": declared, "inherited_auth_type": inherited,
                                "effective_declared_auth_type": effective, "auth_source": source})
                visit(_array(item["item"], 1000), [*ancestry, index], effective, source)
                continue
            request = item["request"]
            if isinstance(request, str):
                method, url, declared = "GET", request, None
            else:
                request = _mapping(request)
                method, url, declared = request.get("method"), request.get("url"), _auth(request.get("auth"))
            if method is not None:
                _name(method, required=True)
                if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,100}", method):
                    raise ValueError("Invalid Postman HTTP method token")
            effective = declared if declared is not None else inherited
            target = _target(url, summary)
            if method is not None:
                methods[method] += 1
            auth_counts[effective if effective is not None else "unknown"] += 1
            statuses[target["status"]] += 1
            requests.append({"index": len(requests), "name": item_name, "folder_path": list(ancestry), "method": method,
                             "target": target, "declared_auth_type": declared, "inherited_auth_type": inherited,
                             "effective_declared_auth_type": effective, "auth_source": "request" if declared is not None else inherited_source})

    visit(items, [], collection_auth, "collection" if collection_auth is not None else "unknown")
    return {"format": "Postman", "version": "2.1.0", "name": name, "collection_auth_type": collection_auth,
            "item_count": item_count, "folder_count": len(folders), "request_count": len(requests),
            "method_counts": dict(sorted(methods.items())), "missing_method_count": sum(row["method"] is None for row in requests),
            "effective_declared_auth_counts": dict(sorted(auth_counts.items())),
            "target_status_counts": dict(sorted(statuses.items())), "folders": summary.take(folders), "requests": summary.take(requests),
            "truncated": summary.truncated,
            "notes": ["Selected Postman v2.1 export fields only, not complete JSON Schema validation or execution. String requests mean GET; absent object methods stay unknown.",
                      "Auth null/absence inherits nearest folder/collection declaration; noauth explicitly stops inheritance. Missing declarations stay unknown, not proof of unauthenticated runtime requests.",
                      "Only URL strings or object raw fields are inspected. Object components are not reconstructed or checked against raw; components-only, templates, non-HTTP targets and missing URLs have no returned target text.",
                      "HTTP targets omit userinfo, query and fragment. Credentials/auth values, variables, headers, bodies, scripts, descriptions, examples, certificates and proxy settings are omitted. No templates/environment/script resolution or network/source-file access.",
                      "Names/hosts/paths can still be caller-sensitive. Limits shorten output only; counts and selected-field checks cover all bounded items."]}
