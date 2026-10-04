import json
import re

import yaml

from app.tools.config_utils.service import _ConfigLoader
from app.tools.json_query.service import _check_tree
from app.tools.manifest_utils.service import _unique_object
from app.tools.openapi_utils.service import _METHODS
from app.tools.performance_utils.service import _json_report
from app.tools.postman_utils.service import inspect_collection
from app.tools.report_comparison.service import _match
from app.tools.report_utils.service import _Summary
from app.tools.schema_utils.service import validate_schema
from app.tools.yaml_utils.tool import _json_compatible


_MAX_OPERATIONS = 500
_JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
_OAS_DIALECT = "https://spec.openapis.org/oas/3.1/dialect/base"
_SCHEMA_TYPES = {"array", "boolean", "integer", "null", "number", "object", "string"}


class _OpenAPILoader(_ConfigLoader):
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if type(key) is int and 100 <= key <= 599:
                key = str(key)
            if not isinstance(key, str) or key in result:
                raise ValueError("OpenAPI YAML requires unique string keys (HTTP response numbers may be unquoted)")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _document(content):
    if not isinstance(content, str) or not content.strip() or len(content) > 200000:
        raise ValueError("OpenAPI document must be nonempty text of at most 200000 characters")
    if content.lstrip().startswith(("{", "[")):
        data = _json_report(content)
    else:
        try:
            data = _json_compatible(yaml.load(content, Loader=_OpenAPILoader))
        except (yaml.YAMLError, ValueError, RecursionError) as error:
            raise ValueError("Invalid or oversized OpenAPI YAML; duplicate keys and unsafe values are rejected") from error
        if not isinstance(data, dict):
            raise ValueError("OpenAPI YAML must have a mapping root")
    version = data.get("openapi")
    if not isinstance(version, str) or not re.fullmatch(r"3\.(?:0|1)\.\d+", version):
        raise ValueError("Only OpenAPI 3.0.x and 3.1.x documents are supported")
    if not isinstance(data.get("info"), dict) or not isinstance(data.get("paths"), dict):
        raise ValueError("OpenAPI info and paths must be objects")
    return data


def _pointer(document, ref):
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    node = document
    for token in ref[2:].split("/"):
        if re.search(r"~(?![01])", token):
            return None
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if token not in node:
                return None
            node = node[token]
        elif isinstance(node, list) and len(token) <= 10 and token.isdecimal() and str(int(token)) == token and int(token) < len(node):
            node = node[int(token)]
        else:
            return None
    return node


def _resolve(value, document):
    seen = set()
    for _ in range(20):
        if not isinstance(value, dict) or "$ref" not in value:
            return value, True
        ref = value["$ref"]
        if not isinstance(ref, str) or ref in seen:
            return None, False
        seen.add(ref)
        value = _pointer(document, ref)
        if value is None:
            return None, False
    return None, False


def _text(value, label, required=False):
    if value is None and not required:
        return None
    if (not isinstance(value, str) or (required and not value) or len(value) > 10000
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(f"OpenAPI {label} must be text of at most 10000 characters without controls")
    return value


def _ref_status(document):
    result = {"total": 0, "resolved_local": 0, "unresolved_local": 0, "external_or_invalid": 0}
    stack = [document]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if "$ref" in node:
                result["total"] += 1
                ref = node["$ref"]
                if isinstance(ref, str) and ref.startswith("#/"):
                    result["resolved_local" if _pointer(document, ref) is not None else "unresolved_local"] += 1
                else:
                    result["external_or_invalid"] += 1
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return result


def _schema_shape(raw, document):
    if raw is None:
        return {"status": "missing"}
    schema, resolved = _resolve(raw, document)
    if not resolved or not isinstance(schema, (dict, bool)):
        return {"status": "unresolved"}
    if isinstance(schema, bool):
        return {"status": "known", "boolean": schema}
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    required = schema.get("required", [])
    if not isinstance(required, list) or any(not isinstance(name, str) for name in required):
        required = []
    property_types = []
    for name, value in properties.items():
        value, resolved = _resolve(value, document)
        property_types.append((name, _schema_type(value.get("type")) if resolved and isinstance(value, dict) else None))
    return {"status": "known", "type": _schema_type(schema.get("type")), "required": sorted(set(required)),
            "property_types": sorted(property_types)}


def _schema_type(value):
    if value is None:
        return None
    if isinstance(value, str) and value in _SCHEMA_TYPES:
        return value
    if isinstance(value, list) and value and len(value) <= 7 and all(isinstance(item, str) and item in _SCHEMA_TYPES for item in value):
        return sorted(set(value))
    return "unknown"


def _media(value, document):
    if not isinstance(value, dict):
        raise ValueError("OpenAPI content must be an object")
    if len(value) > 100:
        raise ValueError("OpenAPI content exceeds 100 media types")
    result = {}
    for media_type, media in value.items():
        _text(media_type, "media type", True)
        if not isinstance(media, dict):
            raise ValueError("OpenAPI media entries must be objects")
        result[media_type] = _schema_shape(media.get("schema"), document)
    return result


def _parameters(path_item, operation, document):
    rows, unresolved = {}, 0
    for source in (path_item, operation):
        seen = set()
        values = source.get("parameters", [])
        if not isinstance(values, list) or len(values) > 500:
            raise ValueError("OpenAPI parameters must be an array of at most 500 entries")
        for raw in values:
            param, resolved = _resolve(raw, document)
            if not resolved or not isinstance(param, dict):
                unresolved += 1
                continue
            name = _text(param.get("name"), "parameter name", True)
            location = param.get("in")
            if location not in {"query", "header", "path", "cookie"}:
                raise ValueError("OpenAPI parameter location must be query, header, path or cookie")
            required = param.get("required", False)
            if type(required) is not bool:
                raise ValueError("OpenAPI parameter required must be boolean")
            key = (location, name)
            if key in seen:
                raise ValueError("Duplicate OpenAPI parameters in one declaration")
            seen.add(key)
            rows[key] = {"name": name, "in": location, "required": required,
                         "schema": _schema_shape(param.get("schema"), document)}
    return rows, unresolved


def _request_body(operation, document):
    if "requestBody" not in operation:
        return {"present": False, "required": False, "media": {}, "unresolved": False}
    value, resolved = _resolve(operation["requestBody"], document)
    if not resolved or not isinstance(value, dict):
        return {"present": True, "required": None, "media": {}, "unresolved": True}
    required = value.get("required", False)
    if type(required) is not bool:
        raise ValueError("OpenAPI requestBody required must be boolean")
    return {"present": True, "required": required, "media": _media(value.get("content", {}), document), "unresolved": False}


def _responses(operation, document):
    values = operation.get("responses", {})
    if not isinstance(values, dict) or len(values) > 100:
        raise ValueError("OpenAPI responses must be an object with at most 100 entries")
    result = {}
    for status, raw in values.items():
        if not isinstance(status, str) or not re.fullmatch(r"(?:[1-5][0-9]{2}|[1-5]XX|default)", status):
            raise ValueError("OpenAPI response keys must be HTTP statuses, ranges or default")
        value, resolved = _resolve(raw, document)
        result[status] = {"media": _media(value.get("content", {}), document), "unresolved": False} if resolved and isinstance(value, dict) else {"media": {}, "unresolved": True}
    return result


def _security(operation, document):
    value = operation.get("security", document.get("security", []))
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("OpenAPI security must be an array of at most 100 alternatives")
    alternatives = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("OpenAPI security alternatives must be objects")
        declarations = []
        for name, scopes in item.items():
            _text(name, "security scheme", True)
            if not isinstance(scopes, list) or any(not isinstance(scope, str) for scope in scopes):
                raise ValueError("OpenAPI security scopes must be string arrays")
            declarations.append((name, tuple(sorted(scopes))))
        alternatives.append(tuple(sorted(declarations)))
    return sorted(alternatives)


def _operations(document):
    rows, unknown_paths, unknown_operations = {}, 0, 0
    for path, raw_item in document["paths"].items():
        _text(path, "path", True)
        if not path.startswith("/"):
            raise ValueError("OpenAPI paths must begin with /")
        path_item, resolved = _resolve(raw_item, document)
        if not resolved or not isinstance(path_item, dict):
            unknown_paths += 1
            continue
        for method in sorted(_METHODS):
            if method not in path_item:
                continue
            operation, resolved = _resolve(path_item[method], document)
            if not resolved or not isinstance(operation, dict):
                unknown_operations += 1
                continue
            if len(rows) >= _MAX_OPERATIONS:
                raise ValueError("OpenAPI document exceeds 500 operations")
            rows[(path, method.upper())] = {"path": path, "method": method.upper(),
                                            "parameters": _parameters(path_item, operation, document),
                                            "request_body": _request_body(operation, document),
                                            "responses": _responses(operation, document),
                                            "security": _security(operation, document)}
    return rows, unknown_paths, unknown_operations


def _show_shape(shape):
    if shape["status"] != "known":
        return {"status": shape["status"]}
    if "boolean" in shape:
        return shape
    return {"status": "known", "type": shape["type"], "required_property_count": len(shape["required"]),
            "property_count": len(shape["property_types"])}


def _shape_details(before, after, summary):
    if before["status"] != "known" or after["status"] != "known" or "boolean" in before or "boolean" in after:
        return {}
    old_types, new_types = dict(before["property_types"]), dict(after["property_types"])
    changed = [{"name": summary.text(name), "before_type": old_types.get(name), "after_type": new_types.get(name)}
               for name in sorted(old_types.keys() | new_types.keys()) if old_types.get(name) != new_types.get(name)
               or (name in old_types) != (name in new_types)]
    return {"required_added": summary.take([summary.text(name) for name in sorted(set(after["required"]) - set(before["required"]))]),
            "required_removed": summary.take([summary.text(name) for name in sorted(set(before["required"]) - set(after["required"]))]),
            "property_type_changes": summary.take(changed)}


def _show_media(media, summary):
    return summary.take([{"media_type": name, "schema": _show_shape(shape)} for name, shape in sorted(media.items())])


def _show_operation(row, summary):
    params, unresolved = row["parameters"]
    return {"path": summary.text(row["path"]), "method": row["method"],
            "parameters": summary.take([{"name": summary.text(name), "in": location, "required": value["required"],
                                         "schema": _show_shape(value["schema"])}
                                        for (location, name), value in sorted(params.items())]),
            "unresolved_parameter_count": unresolved,
            "request_body": {"present": row["request_body"]["present"], "required": row["request_body"]["required"],
                             "unresolved": row["request_body"]["unresolved"],
                             "media": _show_media(row["request_body"]["media"], summary)},
            "responses": summary.take([{"status": status, "unresolved": value["unresolved"],
                                        "media": _show_media(value["media"], summary)}
                                       for status, value in sorted(row["responses"].items())]),
            "security": _show_security(row["security"], summary)}


def _show_security(alternatives, summary):
    return summary.take([{"schemes": [{"name": summary.text(name), "scopes": summary.take([summary.text(scope) for scope in scopes])}
                                        for name, scopes in alternative]} for alternative in alternatives])


def inspect_openapi_document(content, limit):
    summary = _Summary(content, limit)
    document = _document(content)
    rows, unknown_paths, unknown_operations = _operations(document)
    info = document["info"]
    return {"openapi": document["openapi"], "title": summary.text(info.get("title")),
            "version": summary.text(info.get("version")), "operation_count": len(rows),
            "unknown_path_count": unknown_paths, "unknown_operation_count": unknown_operations,
            "reference_status": _ref_status(document),
            "operations": summary.take([_show_operation(row, summary) for row in rows.values()]),
            "truncated": summary.truncated,
            "notes": ["Selected declarations only, not full OpenAPI validation or proof of runtime behavior.",
                      "Local references are resolved for selected fields; external, missing and cyclic references remain unknown and are never fetched.",
                      "Schema summaries cover top-level type, required/property counts and direct property types only; constraints, examples and bodies are not returned.",
                      "Names, paths, media types and scopes may contain caller-sensitive text. No file, network or request execution."]}


def _change(changes, path, method, field, before, after, impact="unknown", certainty="declared", item=None, details=None):
    row = {"path": path, "method": method, "field": field, "before": before, "after": after,
           "impact": impact, "certainty": certainty}
    if item is not None:
        row["item"] = item
    if details is not None:
        row["details"] = details
    changes.append(row)


def compare_openapi_contracts(before, after, limit):
    summary = _Summary(before, limit)
    _Summary(after, limit)
    left_doc, right_doc = _document(before), _document(after)
    left, left_unknown_paths, left_unknown_ops = _operations(left_doc)
    right, right_unknown_paths, right_unknown_ops = _operations(right_doc)
    refs = [_ref_status(left_doc), _ref_status(right_doc)]
    incomplete = bool(left_unknown_paths or right_unknown_paths or left_unknown_ops or right_unknown_ops
                      or any(value["unresolved_local"] or value["external_or_invalid"] for value in refs))
    schema_dialect_comparable = left_doc["openapi"].split(".")[:2] == right_doc["openapi"].split(".")[:2]
    if not schema_dialect_comparable:
        incomplete = True
    for row in [*left.values(), *right.values()]:
        params, unknown_params = row["parameters"]
        if unknown_params or row["request_body"]["unresolved"] or any(response["unresolved"] for response in row["responses"].values()):
            incomplete = True
        shapes = [param["schema"] for param in params.values()]
        shapes.extend(row["request_body"]["media"].values())
        for response in row["responses"].values():
            shapes.extend(response["media"].values())
        if any(shape["status"] == "unresolved" for shape in shapes):
            incomplete = True
    changes = []
    for path, method in sorted(left.keys() | right.keys()):
        old, new = left.get((path, method)), right.get((path, method))
        if old is None or new is None:
            _change(changes, path, method, "operation", old is not None, new is not None,
                    "potential_breaking" if new is None else "additive",
                    "uncertain" if left_unknown_paths or right_unknown_paths or left_unknown_ops or right_unknown_ops else "declared")
            continue
        old_params, old_unknown = old["parameters"]
        new_params, new_unknown = new["parameters"]
        for key in sorted(old_params.keys() | new_params.keys()):
            previous, current = old_params.get(key), new_params.get(key)
            item = {"in": key[0], "name": summary.text(key[1])}
            if previous is None or current is None:
                _change(changes, path, method, "parameter", previous is not None, current is not None,
                        "potential_breaking" if current is not None and current["required"] else "unknown",
                        "uncertain" if old_unknown or new_unknown else "declared", item)
            else:
                for field in ("required", "schema"):
                    if previous[field] != current[field]:
                        _change(changes, path, method, f"parameter_{field}",
                                previous[field] if field == "required" else _show_shape(previous[field]),
                                current[field] if field == "required" else _show_shape(current[field]),
                                "potential_breaking" if field == "required" and current[field] else "unknown",
                                "declared" if field == "required" else "selected_schema_only", item,
                                _shape_details(previous[field], current[field], summary) if field == "schema" else None)
        for field in ("present", "required"):
            if old["request_body"][field] != new["request_body"][field]:
                _change(changes, path, method, f"request_body_{field}", old["request_body"][field],
                        new["request_body"][field], "potential_breaking" if new["request_body"]["required"] else "unknown",
                        "uncertain" if old["request_body"]["unresolved"] or new["request_body"]["unresolved"] else "declared")
        _compare_media(changes, path, method, "request", old["request_body"]["media"], new["request_body"]["media"], summary)
        for status in sorted(old["responses"].keys() | new["responses"].keys()):
            previous, current = old["responses"].get(status), new["responses"].get(status)
            if previous is None or current is None:
                _change(changes, path, method, "response_status", previous is not None, current is not None,
                        "unknown", "declared", status)
            else:
                _compare_media(changes, path, method, f"response:{status}", previous["media"], current["media"], summary)
        if old["security"] != new["security"]:
            _change(changes, path, method, "security_requirements",
                    _show_security(old["security"], summary), _show_security(new["security"], summary),
                    "unknown", "declared")
    rendered = []
    for change in summary.take(changes):
        change = dict(change)
        change["path"] = summary.text(change["path"])
        rendered.append(change)
    return {"before_openapi": left_doc["openapi"], "after_openapi": right_doc["openapi"],
            "before_operation_count": len(left), "after_operation_count": len(right),
            "reference_status": {"before": refs[0], "after": refs[1]},
            "unknown_path_counts": {"before": left_unknown_paths, "after": right_unknown_paths},
            "unknown_operation_counts": {"before": left_unknown_ops, "after": right_unknown_ops},
            "comparison_complete": not incomplete, "schema_dialect_comparable": schema_dialect_comparable,
            "selected_change_count": len(changes),
            "changes": rendered, "truncated": summary.truncated,
            "notes": ["Only selected declared endpoint, parameter, request/response media/status, shallow schema shape and security fields are compared. comparison_complete means selected references were resolved, not full contract coverage.",
                      "Definite means a declaration differs, not that runtime clients break. Potential breaking is advisory; no complete compatibility verdict.",
                      "Unresolved/external references, cross-version schema dialects and unselected constraints can hide changes; no renames are inferred. Names, paths and scopes may be sensitive."]}


def _compare_media(changes, path, method, label, old, new, summary):
    for media_type in sorted(old.keys() | new.keys()):
        previous, current = old.get(media_type), new.get(media_type)
        if previous is None or current is None:
            _change(changes, path, method, f"{label}_media", previous is not None, current is not None,
                    "unknown", "declared", media_type)
        elif previous != current:
            _change(changes, path, method, f"{label}_schema_shape", _show_shape(previous), _show_shape(current),
                    "unknown", "selected_schema_only", summary.text(media_type),
                    _shape_details(previous, current, summary))


def _identity_name(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 1000 and not any(ord(c) < 32 or ord(c) == 127 for c in value)


def _postman_key(row):
    names = [*row["ancestry"], row["name"]]
    return tuple(names) if all(_identity_name(name) for name in names) else None


def _postman_identity(row, summary):
    return {"folder_path": [summary.text(name) for name in row["ancestry"]], "name": summary.text(row["name"])}


def _target_view(target, summary):
    if target["status"] != "http":
        return {"status": target["status"]}
    return {"status": "http", "scheme": target["scheme"], "host": target["host"],
            "port": target["port"], "path": summary.text(target["path"])}


def compare_postman_collections(before, after, limit):
    summary = _Summary(before, limit)
    _Summary(after, limit)
    records = [{}, {}]
    views = [inspect_collection(before, 50, _records=records[0]), inspect_collection(after, 50, _records=records[1])]
    changes, matching = [], {}
    for kind in ("folders", "requests"):
        match = _match(records[0][kind], records[1][kind], _postman_key)
        matching[kind] = {"matched": len(match["matched"]), "added": len(match["added"]),
                          "removed": len(match["removed"]), "ambiguous": len(match["ambiguous"]),
                          "unmatchable_before": match["unmatchable_before_count"],
                          "unmatchable_after": match["unmatchable_after_count"]}
        for row in match["added"]:
            changes.append({"kind": kind[:-1], "identity": _postman_identity(row, summary), "field": "item", "before": False, "after": True})
        for row in match["removed"]:
            changes.append({"kind": kind[:-1], "identity": _postman_identity(row, summary), "field": "item", "before": True, "after": False})
        for old, new in match["matched"]:
            identity = _postman_identity(old, summary)
            for field in ("declared_auth_type", "effective_auth_type", "auth_source"):
                if old[field] != new[field]:
                    changes.append({"kind": kind[:-1], "identity": identity, "field": field,
                                    "before": old[field], "after": new[field]})
            if kind == "requests":
                if old["method"] != new["method"]:
                    changes.append({"kind": "request", "identity": identity, "field": "method",
                                    "before": old["method"], "after": new["method"]})
                old_target, new_target = old["target"], new["target"]
                if old_target["status"] != new_target["status"] or old_target["status"] == "http" and new_target["status"] == "http" and any(old_target[key] != new_target[key] for key in ("scheme", "host", "port", "path")):
                    changes.append({"kind": "request", "identity": identity, "field": "sanitized_target",
                                    "before": _target_view(old_target, summary), "after": _target_view(new_target, summary)})
    uncertain_targets = [sum(row["target"]["status"] != "http" for row in records[index]["requests"]) for index in (0, 1)]
    return {"before_request_count": views[0]["request_count"], "after_request_count": views[1]["request_count"],
            "matching": matching, "uncertain_target_counts": {"before": uncertain_targets[0], "after": uncertain_targets[1]},
            "selected_change_count": len(changes), "changes": summary.take(changes), "truncated": summary.truncated,
            "notes": ["Matches use exact full folder-name ancestry and request/folder name; duplicate or missing names remain ambiguous/unmatchable. Reordering is ignored; renames are not inferred.",
                      "Only methods, sanitized HTTP scheme/host/port/path and declared/effective auth types are compared. Unresolved templates, components-only and unsupported targets cannot be compared by raw URL.",
                      "Credentials, userinfo, query/fragment, variables, headers, bodies, scripts and examples are omitted. Auth declarations do not prove runtime behavior; names/hosts/paths may be sensitive."]}


def _body_json(content):
    if not isinstance(content, str) or len(content) > 200000:
        raise ValueError("JSON body must be text of at most 200000 characters")
    try:
        value = json.loads(content, object_pairs_hook=_unique_object)
        _check_tree(value, max_nodes=20000, max_depth=50)
        return value
    except (ValueError, RecursionError) as error:
        raise ValueError("Invalid or oversized JSON body; duplicate keys and non-finite numbers are rejected") from error


def _validation_schema(schema, document):
    if not isinstance(schema, (dict, bool)):
        raise ValueError("Selected OpenAPI media schema must be an object or boolean")
    if isinstance(schema, bool):
        return schema
    components = document.get("components", {})
    schemas = components.get("schemas", {}) if isinstance(components, dict) else {}
    if not isinstance(schemas, dict):
        raise ValueError("OpenAPI components.schemas must be an object")
    if "$defs" in schema and not isinstance(schema["$defs"], dict):
        raise ValueError("Schema $defs must be an object")
    reserved = "_openapi_components"
    while reserved in schema.get("$defs", {}):
        reserved += "_"
    selected = {}
    map_keywords = {"properties", "patternProperties", "$defs", "dependentSchemas", "definitions"}
    list_keywords = {"allOf", "anyOf", "oneOf", "prefixItems"}
    schema_keywords = {"items", "additionalItems", "additionalProperties", "unevaluatedProperties",
                       "propertyNames", "not", "contains", "if", "then", "else", "unevaluatedItems", "contentSchema"}

    def transform(node):
        if not isinstance(node, dict):
            return node
        if any(key in node for key in ("$id", "$schema", "$anchor", "$dynamicRef", "$dynamicAnchor",
                                       "$recursiveRef", "$vocabulary", "nullable", "discriminator", "readOnly", "writeOnly")):
            raise ValueError("Selected schema uses unsupported dialect, dynamic-reference or OpenAPI directional features")
        result = {}
        for key, value in node.items():
            if key == "$ref":
                if not isinstance(value, str) or not value.startswith("#/components/schemas/") or _pointer(document, value) is None:
                    raise ValueError("Only resolvable local #/components/schemas references are supported for body validation")
                component_name = value[len("#/components/schemas/"):].split("/", 1)[0].replace("~1", "/").replace("~0", "~")
                if component_name not in schemas:
                    raise ValueError("Referenced component schema is missing")
                selected[component_name] = None
                result[key] = f"#/$defs/{reserved}/" + value[len("#/components/schemas/"):]
            elif key in map_keywords and isinstance(value, dict):
                result[key] = {name: transform(child) for name, child in value.items()}
            elif key in list_keywords and isinstance(value, list):
                result[key] = [transform(child) for child in value]
            elif key in schema_keywords:
                result[key] = transform(value)
            else:
                result[key] = value
        return result

    root = transform(schema)
    expanded = {}
    while len(expanded) < len(selected):
        for name in list(selected):
            if name in expanded:
                continue
            component = schemas[name]
            if not isinstance(component, (dict, bool)):
                raise ValueError("Referenced component schema must be an object or boolean")
            expanded[name] = transform(component)
    if expanded:
        defs = root.get("$defs", {})
        if not isinstance(defs, dict):
            raise ValueError("Schema $defs must be an object")
        root["$defs"] = {**defs, reserved: expanded}
    root["$schema"] = _JSON_SCHEMA_DRAFT
    return root


def validate_openapi_json_body(spec, path, method, direction, body, status="200", media_type="application/json", limit=20):
    _Summary(spec, limit)
    document = _document(spec)
    if not document["openapi"].startswith("3.1."):
        raise ValueError("JSON body validation supports OpenAPI 3.1.x only; 3.0 schema semantics differ")
    if document.get("jsonSchemaDialect", _OAS_DIALECT) != _OAS_DIALECT:
        raise ValueError("Custom OpenAPI JSON Schema dialects are unsupported")
    path = _text(path, "path", True)
    method = _text(method, "method", True).lower()
    if method not in _METHODS or direction not in {"request", "response"}:
        raise ValueError("method must be an HTTP operation method and direction must be request or response")
    media_type = _text(media_type, "media type", True)
    if media_type != "application/json" and not media_type.endswith("+json"):
        raise ValueError("Only application/json or +json media types are supported")
    if not isinstance(status, str) or not re.fullmatch(r"[1-5][0-9]{2}", status):
        raise ValueError("status must be a three-digit HTTP status")
    path_item, resolved = _resolve(document["paths"].get(path), document)
    if not resolved or not isinstance(path_item, dict):
        raise ValueError("Selected OpenAPI path is missing or has an unresolved reference")
    operation, resolved = _resolve(path_item.get(method), document)
    if not resolved or not isinstance(operation, dict):
        raise ValueError("Selected OpenAPI operation is missing or has an unresolved reference")
    if direction == "request":
        selected, resolved = _resolve(operation.get("requestBody"), document)
    else:
        responses = operation.get("responses", {})
        if not isinstance(responses, dict):
            raise ValueError("OpenAPI responses must be an object")
        selected, resolved = _resolve(responses.get(status, responses.get(status[0] + "XX", responses.get("default"))), document)
    if not resolved or not isinstance(selected, dict):
        raise ValueError("Selected request/response body is missing or has an unresolved reference")
    content = selected.get("content", {})
    if not isinstance(content, dict) or media_type not in content or not isinstance(content[media_type], dict):
        raise ValueError("Selected JSON media type is not declared")
    schema = _validation_schema(content[media_type].get("schema"), document)
    instance = _body_json(body)
    try:
        result = validate_schema(instance, schema)
    except ValueError as error:
        raise ValueError("JSON Schema validation failed or exceeded its time limit; unsupported schema features may be present") from error
    errors = [{"path": entry["path"], "schema_path": entry["schema_path"]} for entry in result["errors"]]
    return {"valid": result["valid"], "direction": direction, "path": path[:1000], "method": method.upper(),
            "status": status if direction == "response" else None, "media_type": media_type,
            "error_count_returned": len(errors), "errors": errors[:limit],
            "truncated": result["truncated"] or len(errors) > limit,
            "notes": ["OpenAPI 3.1 JSON Schema 2020-12 subset only; local component-schema references are rewritten in memory. No remote retrieval, request execution or file access.",
                      "Validation does not implement OpenAPI discriminator, readOnly/writeOnly directionality, custom dialects or all extensions. Unknown formats may not be checked.",
                      "Error messages and body values are omitted; JSON pointer paths can contain caller-supplied property names."]}
