import json

from app.tools.vulnerability_utils.service import _ECOSYSTEMS
from app.tools.webpage.service import request_public


_ENDPOINT = "https://api.osv.dev/v1/querybatch"
_MAX_PACKAGES = 50


def _validate_package(item, index):
    if not isinstance(item, dict):
        raise ValueError(f"Package {index} must be an object")
    ecosystem, name, version = item.get("ecosystem"), item.get("name"), item.get("version")
    if ecosystem not in _ECOSYSTEMS:
        raise ValueError("Supported ecosystems: " + ", ".join(sorted(_ECOSYSTEMS)))
    for label, value, maximum in (("name", name, 200), ("version", version, 100)):
        if (not isinstance(value, str) or not 1 <= len(value) <= maximum
                or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError(f"Package {index} {label} must be 1-{maximum} characters without whitespace or controls")
    if any(char in version for char in "<>=*|^") or version.startswith("~"):
        raise ValueError(f"Package {index} version must be exact, not a range")
    return {"ecosystem": ecosystem, "name": name, "version": version}


def _text(value, maximum):
    return value[:maximum] if isinstance(value, str) else ""


def _summarize_vulnerabilities(rows, limit):
    if not isinstance(rows, list):
        raise ValueError("OSV returned invalid batch results")
    summaries = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            raise ValueError("OSV returned an invalid vulnerability record")
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
            raise ValueError("OSV returned invalid vulnerability aliases")
        summaries.append({
            "id": _text(row["id"], 100),
            "aliases": [_text(alias, 100) for alias in aliases[:10]],
            "summary": _text(row.get("summary") or row.get("details"), 500),
        })
    return summaries[:limit], len(summaries) > limit


def check_packages(packages, limit):
    if not isinstance(packages, list) or not 1 <= len(packages) <= _MAX_PACKAGES:
        raise ValueError(f"packages must contain 1-{_MAX_PACKAGES} package objects")
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    queries = [_validate_package(item, index) for index, item in enumerate(packages, 1)]
    payload = {"queries": [{"package": {"ecosystem": row["ecosystem"], "name": row["name"]},
                             "version": row["version"]} for row in queries]}
    status, headers, body, _ = request_public(
        _ENDPOINT, method="POST", headers={"Accept": "application/json", "Content-Type": "application/json"},
        body=json.dumps(payload).encode("utf-8"), allowed_host="api.osv.dev",
    )
    if not 200 <= status < 300:
        raise ValueError(f"OSV returned HTTP {status}")
    content_type = next((value for key, value in headers.items() if key.lower() == "content-type"), "")
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise ValueError("OSV returned an unsupported content type")
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("OSV returned invalid JSON") from error
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list) or len(results) != len(queries):
        raise ValueError("OSV returned results that do not match the package batch")

    output = []
    for query, result in zip(queries, results):
        if not isinstance(result, dict):
            raise ValueError("OSV returned an invalid package result")
        vulnerabilities, truncated = _summarize_vulnerabilities(result.get("vulns", []), limit)
        truncated |= bool(result.get("next_page_token"))
        output.append({**query, "vulnerability_count": len(vulnerabilities),
                       "vulnerabilities": vulnerabilities, "truncated": truncated})
    return {
        "source": "https://osv.dev",
        "packages": output,
        "package_count": len(output),
        "vulnerable_package_count": sum(bool(row["vulnerabilities"]) for row in output),
        "notice": "Known advisories only; no matches do not prove safety. Results are bounded summaries.",
    }
