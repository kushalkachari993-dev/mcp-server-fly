import yaml

from app.tools.json_utils.tool import _load_bounded_json
from app.tools.yaml_utils.tool import _JsonSafeLoader, _json_compatible


_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
_SPEC_TYPES = {"application/json", "application/yaml", "application/x-yaml",
               "text/yaml", "text/x-yaml", "text/plain"}


def inspect_spec(body, url, max_operations):
    try:
        value = body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("OpenAPI description must be UTF-8") from error
    if len(value) > 200000:
        raise ValueError("OpenAPI description exceeds 200000 characters")
    try:
        if value.lstrip().startswith(("{", "[")):
            data = _load_bounded_json(value)
        else:
            data = _json_compatible(yaml.load(value, Loader=_JsonSafeLoader))
    except (yaml.YAMLError, RecursionError) as error:
        raise ValueError(f"Could not parse OpenAPI description: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("openapi"), str) or not data["openapi"].startswith("3."):
        raise ValueError("An OpenAPI 3.x description is required")
    info = data.get("info")
    paths = data.get("paths")
    if not isinstance(info, dict) or not isinstance(paths, dict):
        raise ValueError("OpenAPI description must contain info and paths objects")
    operations = []
    truncated = False
    unresolved_paths = 0
    unresolved_operations = 0
    for path, item in paths.items():
        if not isinstance(path, str) or not path.startswith("/") or not isinstance(item, dict):
            continue
        if "$ref" in item:
            unresolved_paths += 1
            continue
        for method, operation in item.items():
            if method not in _METHODS or not isinstance(operation, dict):
                continue
            if "$ref" in operation:
                unresolved_operations += 1
                continue
            if len(operations) >= max_operations:
                truncated = True
                break
            security = operation.get("security", data.get("security", []))
            names = sorted({name for requirement in security if isinstance(requirement, dict)
                            for name in requirement}) if isinstance(security, list) else []
            tags = operation.get("tags", [])
            operations.append({"path": path[:500], "method": method.upper(),
                               "operation_id": str(operation.get("operationId", ""))[:200],
                               "summary": str(operation.get("summary", ""))[:300],
                               "tags": [str(tag)[:100] for tag in tags[:5]] if isinstance(tags, list) else [],
                               "security_schemes": names[:10]})
        if truncated:
            break
    servers = data.get("servers", [])
    return {"url": url, "openapi": data["openapi"],
            "title": str(info.get("title", ""))[:300],
            "version": str(info.get("version", ""))[:100],
            "servers": [str(item.get("url", ""))[:500] for item in servers[:5]
                        if isinstance(item, dict)] if isinstance(servers, list) else [],
            "operations": operations, "truncated": truncated,
            "unresolved_path_refs": unresolved_paths,
            "unresolved_operation_refs": unresolved_operations}
