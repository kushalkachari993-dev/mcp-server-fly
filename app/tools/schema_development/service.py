import json
import multiprocessing
import threading
from urllib.parse import unquote

from jsonschema import Draft7Validator, Draft201909Validator, Draft202012Validator
from referencing import Registry

from app.tools.data_transform.service import load, encode, parts
from app.tools.json_query.service import _check_tree
from app.tools.json_utils.tool import _pointer_token
from app.tools.schema_utils.service import _deny_remote_reference, _pointer


_DIALECTS = {
    "http://json-schema.org/draft-07/schema#": Draft7Validator,
    "https://json-schema.org/draft/2019-09/schema": Draft201909Validator,
    "https://json-schema.org/draft/2020-12/schema": Draft202012Validator,
}
_DEFAULT = "https://json-schema.org/draft/2020-12/schema"
_SLOTS = threading.BoundedSemaphore(2)
_TIMEOUT = 3
_MAPS = {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}
_SINGLE = {"additionalProperties", "additionalItems", "contains", "propertyNames", "not",
           "if", "then", "else", "unevaluatedProperties", "unevaluatedItems", "contentSchema"}
_ARRAYS = {"allOf", "anyOf", "oneOf", "prefixItems"}
_CONSTRAINTS = {"type", "required", "enum", "const", "minimum", "maximum", "exclusiveMinimum",
                "exclusiveMaximum", "multipleOf", "minLength", "maxLength", "pattern", "format",
                "minItems", "maxItems", "uniqueItems", "minContains", "maxContains",
                "minProperties", "maxProperties", "dependentRequired", "additionalProperties",
                "unevaluatedProperties", "unevaluatedItems"}


def nodes(schema, path=""):
    yield path, schema
    if not isinstance(schema, dict):
        return
    for key, value in schema.items():
        child = path + "/" + _pointer_token(key)
        if key in _MAPS and isinstance(value, dict):
            for name, item in value.items():
                yield from nodes(item, child + "/" + _pointer_token(name))
        elif key in _SINGLE and isinstance(value, (dict, bool)):
            yield from nodes(value, child)
        elif key in _ARRAYS or key == "items":
            if isinstance(value, list):
                for index, item in enumerate(value):
                    yield from nodes(item, child + "/" + str(index))
            elif key == "items" and isinstance(value, (dict, bool)):
                yield from nodes(value, child)
        elif key == "dependencies" and isinstance(value, dict):
            for name, item in value.items():
                if isinstance(item, (dict, bool)):
                    yield from nodes(item, child + "/" + _pointer_token(name))


def schema_info(text):
    schema = load(text)
    if not isinstance(schema, (dict, bool)):
        raise ValueError("Schema must be an object or boolean")
    dialect = schema.get("$schema", _DEFAULT) if isinstance(schema, dict) else _DEFAULT
    if not isinstance(dialect, str) or dialect not in _DIALECTS:
        raise ValueError("Supported dialects are draft-07, 2019-09 and 2020-12 (canonical $schema URI)")
    for path, node in nodes(schema):
        if not isinstance(node, dict):
            continue
        if "$schema" in node and node["$schema"] != dialect:
            raise ValueError("Nested dialect changes are unsupported")
        # IDs change reference scope, so reject them instead of guessing resolution.
        if "$id" in node:
            raise ValueError("$id scope declarations are unsupported; use fragment references")
        if "$dynamicRef" in node or "$recursiveRef" in node:
            raise ValueError("Dynamic and recursive references are unsupported")
        if "$ref" in node and (not isinstance(node["$ref"], str) or not node["$ref"].startswith("#")):
            raise ValueError("Only local fragment $ref references are supported")
    cls = _DIALECTS[dialect]
    try:
        cls.check_schema(schema)
    except Exception:
        raise ValueError("Invalid schema for the selected dialect") from None
    return schema, dialect, cls


def limit_check(limit):
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")


def select(document, pointer):
    node = document
    for token in parts(pointer):
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isascii() and token.isdigit() and (token == "0" or not token.startswith("0")) and len(token) <= 5 and int(token) < len(node):
            node = node[int(token)]
        else:
            raise ValueError("Pointer does not resolve to an existing value")
    return node


def inspect_json_schema(schema, limit=100):
    limit_check(limit)
    doc, dialect, _ = schema_info(schema)
    declarations, references = [], []
    known = dict(nodes(doc))
    for path, node in known.items():
        if isinstance(node, bool):
            declarations.append({"path": path, "boolean_schema": node})
            continue
        declarations.append({"path": path, "constraints": {k: v for k, v in node.items() if k in _CONSTRAINTS},
                             "properties": list(node.get("properties", {}))})
        if "$ref" in node:
            ref = node["$ref"]
            fragment = unquote(ref[1:])
            if fragment == "" or fragment.startswith("/"):
                try:
                    resolved = fragment in known and isinstance(select(doc, fragment), (dict, bool))
                except ValueError:
                    resolved = False
            else:
                resolved = any(isinstance(n, dict) and n.get("$anchor") == fragment for n in known.values())
            references.append({"path": path + "/$ref", "reference": ref, "resolved": resolved})
    return {"dialect": dialect, "schema_nodes": len(known), "declarations": declarations[:limit],
            "references": references[:limit], "truncated": len(declarations) > limit or len(references) > limit}


def compare_json_schemas(before, after, limit=100):
    limit_check(limit)
    first, old_dialect, _ = schema_info(before)
    second, new_dialect, _ = schema_info(after)
    changes, count = [], 0
    def walk(a, b, path):
        nonlocal count
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()):
                child = path + "/" + _pointer_token(key)
                if key not in a or key not in b:
                    count += 1
                    if len(changes) < limit:
                        changes.append({"path": child, "change": "added" if key not in a else "removed"})
                else:
                    walk(a[key], b[key], child)
        elif type(a) is not type(b) or json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
            count += 1
            if len(changes) < limit:
                changes.append({"path": path, "change": "changed"})
    walk(first, second, "")
    return {"before_dialect": old_dialect, "after_dialect": new_dialect,
            "change_count": count, "changes": changes, "truncated": count > limit,
            "compatibility_assessed": False}


def infer_json_schema(examples):
    samples = load(examples)
    if not isinstance(samples, list) or not samples:
        raise ValueError("examples must be a nonempty JSON array of sample documents")
    def infer(values):
        groups = {}
        for value in values:
            kind = {dict: "object", list: "array", str: "string", bool: "boolean",
                    int: "integer", float: "number", type(None): "null"}[type(value)]
            groups.setdefault(kind, []).append(value)
        if "integer" in groups and "number" in groups:
            groups["number"].extend(groups.pop("integer"))
        variants = []
        for kind, items in sorted(groups.items()):
            schema = {"type": kind}
            if kind == "object":
                keys = sorted(set().union(*(item.keys() for item in items)))
                schema["properties"] = {key: infer([item[key] for item in items if key in item]) for key in keys}
                required = [key for key in keys if all(key in item for item in items)]
                if required:
                    schema["required"] = required
            if kind == "array":
                children = [child for item in items for child in item]
                schema["items"] = infer(children) if children else {}
            variants.append(schema)
        return variants[0] if len(variants) == 1 else {"anyOf": variants}
    result = infer(samples)
    result["$schema"] = _DEFAULT
    return {"schema": result, "sample_count": len(samples),
            "uncertainty": ["Types and required fields reflect only supplied samples.",
                            "Additional properties remain allowed; no enums, formats, ranges or string patterns are inferred.",
                            "Empty arrays have unconstrained items; array positions are not inferred."]}


def validate_records(records, schema, limit, malformed=None):
    limit_check(limit)
    doc, dialect, cls = schema_info(schema)
    validator = cls(doc, registry=Registry(retrieve=_deny_remote_reference))
    errors, invalid, evaluated = [], 0, 0
    for index, instance in records:
        evaluated += 1
        failed = False
        try:
            # One diagnostic per failing record; continue evaluating all records.
            error = next(validator.iter_errors(instance), None)
        except Exception:
            raise ValueError("Schema evaluation failed; check references or recursive constraints") from None
        if error is not None:
            failed = True
            if len(errors) < limit:
                errors.append({"record": index, "path": _pointer(error.absolute_path),
                               "schema_path": _pointer(error.absolute_schema_path), "keyword": error.validator})
        invalid += failed
    malformed = malformed or []
    return {"dialect": dialect, "valid": invalid == 0 and not malformed,
            "evaluated_records": evaluated, "invalid_records": invalid,
            "errors": errors, "malformed_line_count": len(malformed), "malformed_lines": malformed[:limit],
            "truncated": invalid > limit or len(malformed) > limit,
            "format_assertions": False}


def validate_json_schema_batch(value, schema, limit=100):
    samples = load(value)
    if not isinstance(samples, list):
        raise ValueError("value must be a JSON array")
    report = validate_records(enumerate(samples), schema, limit)
    report["record_identity"] = "zero-based array index"
    return report


def validate_jsonl_schema(content, schema, limit=100):
    if len(content) > 200000:
        raise ValueError("Input must not exceed 200000 characters")
    records, malformed = [], []
    for number, line in enumerate(content.split("\n"), 1):
        if not line.strip():
            continue
        try:
            records.append((number, load(line)))
        except (ValueError, RecursionError):
            malformed.append(number)
    _check_tree([item for _, item in records])
    report = validate_records(records, schema, limit, malformed)
    report["record_identity"] = "one-based line number"
    return report


def resolve_json_schema_pointer(schema, pointer):
    doc, _, _ = schema_info(schema)
    if len(pointer) > 200000:
        raise ValueError("Input must not exceed 200000 characters")
    if pointer not in dict(nodes(doc)):
        # Check pointer syntax even when it does not identify a schema node.
        parts(pointer)
        raise ValueError("Pointer must select a schema node, not an annotation or keyword value")
    return select(doc, pointer)


def _worker(sender, name, args):
    try:
        response = {"result": encode(globals()[name](*args))}
    except Exception as error:
        response = {"error": str(error) if type(error) is ValueError else "Invalid input or schema evaluation failed"}
    try:
        sender.send(response)
    except (BrokenPipeError, EOFError, OSError):
        # The parent may close the pipe after its timeout expires.
        pass
    finally:
        sender.close()


def run(name, *args):
    if not _SLOTS.acquire(blocking=False):
        raise ValueError("Schema workers are busy; retry later")
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(sender, name, args))
    try:
        process.start()
        sender.close()
        if not receiver.poll(_TIMEOUT):
            raise ValueError("Schema operation exceeded its 3-second limit")
        response = receiver.recv()
        if "error" in response:
            raise ValueError(response["error"])
        return response["result"]
    except EOFError:
        raise ValueError("Schema worker exited without a result") from None
    finally:
        sender.close()
        receiver.close()
        if process.pid is not None:
            process.join(timeout=0.2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join()
            process.close()
        _SLOTS.release()
