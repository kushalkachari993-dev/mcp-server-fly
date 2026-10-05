import json
import re

from app.tools.json_query.service import _check_tree
from app.tools.json_utils.tool import _parse_float, _pointer_token, _reject_constant


def load(value):
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate JSON object keys are unsupported")
            result[key] = item
        return result

    if len(value) > 200000:
        raise ValueError("Input must not exceed 200000 characters")
    result = json.loads(value, object_pairs_hook=unique,
                        parse_float=_parse_float, parse_constant=_reject_constant)
    _check_tree(result)
    return result


def encode(value):
    _check_tree(value)
    chunks, size = [], 0
    for chunk in json.JSONEncoder(ensure_ascii=True, allow_nan=False).iterencode(value):
        size += len(chunk)
        if size > 200000:
            raise ValueError("Output exceeds 200000 characters")
        chunks.append(chunk)
    return "".join(chunks)


def lines(content):
    if len(content) > 200000:
        raise ValueError("Input must not exceed 200000 characters")
    records, invalid, blanks = [], [], 0
    for number, line in enumerate(content.split("\n"), 1):
        if not line.strip():
            blanks += 1
            continue
        try:
            records.append(load(line))
        except (ValueError, RecursionError):
            invalid.append(number)
    _check_tree(records)
    return records, invalid, blanks


def inspect_jsonl(content, limit=100):
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    records, invalid, blanks = lines(content)
    fields, kinds, objects = {}, {}, 0
    def kind(value):
        return {dict: "object", list: "array", str: "string", int: "number",
                float: "number", bool: "boolean", type(None): "null"}[type(value)]
    for record in records:
        name = kind(record)
        kinds[name] = kinds.get(name, 0) + 1
        if isinstance(record, dict):
            objects += 1
            for key, value in record.items():
                field = fields.setdefault(key, {"present": 0, "types": {}})
                field["present"] += 1
                name = kind(value)
                field["types"][name] = field["types"].get(name, 0) + 1
    for field in fields.values():
        field["missing"] = objects - field["present"]
    return encode({"valid_records": len(records), "record_types": kinds,
                   "object_records": objects, "blank_lines": blanks,
                   "invalid_line_count": len(invalid), "invalid_lines": invalid[:limit],
                   "fields": dict(list(fields.items())[:limit]),
                   "truncated": len(fields) > limit or len(invalid) > limit})


def jsonl_to_json(content):
    records, invalid, _ = lines(content)
    if invalid:
        raise ValueError(f"Invalid JSONL at line {invalid[0]}; no partial conversion returned")
    return encode(records)


def json_to_jsonl(value):
    records = load(value)
    if not isinstance(records, list):
        raise ValueError("value must be a JSON array")
    output = "\n".join(encode(record) for record in records)
    if len(output) > 200000:
        raise ValueError("Output exceeds 200000 characters")
    return output


def flatten_json(value):
    result = {}
    def walk(node, path):
        if isinstance(node, dict) and node:
            for key, child in node.items():
                walk(child, path + "/" + _pointer_token(key))
        else:
            result[path] = node
    walk(load(value), "")
    return encode(result)


def parts(path):
    if not isinstance(path, str) or (path and not path.startswith("/")):
        raise ValueError("Paths must be JSON Pointers (empty for root or starting with /)")
    if re.search(r"~(?![01])", path):
        raise ValueError("Invalid JSON Pointer escape")
    tokens = [] if path == "" else [p.replace("~1", "/").replace("~0", "~") for p in path[1:].split("/")]
    if len(tokens) > 50:
        raise ValueError("Pointers must not exceed 50 nested levels")
    return tokens


def unflatten_json(value):
    flat = load(value)
    if not isinstance(flat, dict):
        raise ValueError("value must be an object mapping JSON Pointers to values")
    root, leaves = {}, set()
    for path, item in flat.items():
        tokens = parts(path)
        if not tokens:
            if len(flat) != 1:
                raise ValueError("Conflicting root and descendant paths")
            return encode(item)
        node, prefix = root, ""
        for token in tokens[:-1]:
            prefix += "/" + _pointer_token(token)
            if prefix in leaves:
                raise ValueError("Conflicting ancestor and descendant paths")
            node = node.setdefault(token, {})
        if tokens[-1] in node:
            raise ValueError("Conflicting ancestor and descendant paths")
        node[tokens[-1]] = item
        leaves.add(path)
    return encode(root)


def redact_json_fields(value, pointers_json, mask="[REDACTED]"):
    if len(mask) > 200000:
        raise ValueError("Mask must not exceed 200000 characters")
    document, paths = load(value), load(pointers_json)
    if not isinstance(paths, list) or len(paths) > 100 or any(not isinstance(p, str) for p in paths):
        raise ValueError("pointers_json must be an array of at most 100 JSON Pointers")
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate redaction pointers are unsupported")
    targets, parsed = [], [parts(path) for path in paths]
    for index, tokens in enumerate(parsed):
        if any(tokens[:len(other)] == other for i, other in enumerate(parsed) if i != index):
            raise ValueError("Overlapping redaction pointers are unsupported")
        node = document
        parent, key = None, None
        for token in tokens:
            parent = node
            if isinstance(node, dict) and token in node:
                key = token
            elif isinstance(node, list) and re.fullmatch(r"0|[1-9][0-9]*", token) and len(token) <= 5 and int(token) < len(node):
                key = int(token)
            else:
                raise ValueError("Redaction pointer does not resolve to an existing value")
            node = node[key]
        targets.append((parent, key))
    for parent, key in targets:
        if parent is None:
            document = mask
        else:
            parent[key] = mask
    return encode(document)
