import copy
import json

import jsonpatch
from jsonpointer import JsonPointer, JsonPointerException

from app.tools.json_query.service import _check_tree
from app.tools.json_utils.tool import _load_bounded_json


_MAX_OUTPUT = 200000


class _JsonPointer(JsonPointer):
    def walk(self, doc, part):
        if not isinstance(doc, (dict, list)):
            raise JsonPointerException("Cannot traverse a JSON scalar")
        return super().walk(doc, part)

    def to_last(self, doc):
        parent, part = super().to_last(doc)
        if part is not None and not isinstance(parent, (dict, list)):
            raise JsonPointerException("Cannot traverse a JSON scalar")
        return parent, part


def _json_equal(left, right):
    pairs = [(left, right)]
    while pairs:
        first, second = pairs.pop()
        if type(first) in (int, float) and type(second) in (int, float):
            if first != second:
                return False
        elif type(first) is not type(second):
            return False
        elif isinstance(first, dict):
            if first.keys() != second.keys():
                return False
            pairs.extend((first[key], second[key]) for key in first)
        elif isinstance(first, list):
            if len(first) != len(second):
                return False
            pairs.extend(zip(first, second))
        elif first != second:
            return False
    return True


def _encode(value):
    chunks, length = [], 0
    for chunk in json.JSONEncoder(allow_nan=False, ensure_ascii=True).iterencode(value):
        length += len(chunk)
        if length > _MAX_OUTPUT:
            raise ValueError("JSON Patch result exceeds 200000 characters")
        chunks.append(chunk)
    return "".join(chunks)


def _pointer(value):
    if not isinstance(value, str) or len(value) > 1000:
        raise ValueError("Patch pointers must be strings of at most 1000 characters")
    pointer = _JsonPointer(value)
    if len(pointer.parts) > 50:
        raise ValueError("Patch pointers must not exceed 50 nested levels")
    return pointer


def apply(value, patch):
    document = _load_bounded_json(value)
    operations = _load_bounded_json(patch)
    _check_tree(document)
    _check_tree(operations)
    if not isinstance(operations, list) or len(operations) > 50:
        raise ValueError("patch must be a JSON array of at most 50 operations")
    for index, operation in enumerate(operations, 1):
        try:
            if not isinstance(operation, dict) or not isinstance(operation.get("op"), str):
                raise ValueError("Each patch operation must be an object with an op")
            kind = operation["op"]
            if kind not in jsonpatch.JsonPatch.operations:
                raise ValueError("Supported operations: add, remove, replace, move, copy, test")
            target = _pointer(operation.get("path"))
            if kind in {"add", "replace", "test"} and "value" not in operation:
                raise ValueError("This operation requires value")
            source = _pointer(operation.get("from")) if kind in {"move", "copy"} else None
            if (kind == "move" and len(target.parts) > len(source.parts)
                    and target.parts[:len(source.parts)] == source.parts):
                raise ValueError("Cannot move a value into its own descendant")
            # Adapt the library's root and test behavior to JSON document semantics.
            if kind == "test":
                if not _json_equal(target.resolve(document), operation["value"]):
                    raise ValueError("JSON Patch test failed")
            elif kind == "remove" and not target.parts:
                raise ValueError("Removing the document root is unsupported; use replace with null")
            elif kind in {"add", "replace"} and not target.parts:
                document = copy.deepcopy(operation["value"])
            elif kind == "replace" and target.parts[-1] == "-":
                parent, part = target.to_last(document)
                if not isinstance(parent, dict) or part not in parent:
                    raise ValueError("replace requires an existing object key or array index")
                document = jsonpatch.JsonPatch([
                    {"op": "add", "path": operation["path"], "value": operation["value"]}
                ], pointer_cls=_JsonPointer).apply(document, in_place=True)
            elif source is not None and (not source.parts or not target.parts):
                if kind == "move" and not source.parts and target.parts:
                    raise ValueError("Cannot move the document root into its own descendant")
                selected = copy.deepcopy(source.resolve(document))
                if not target.parts:
                    document = selected
                else:
                    document = jsonpatch.JsonPatch([
                        {"op": "add", "path": operation["path"], "value": selected}
                    ], pointer_cls=_JsonPointer).apply(document, in_place=True)
            else:
                document = jsonpatch.JsonPatch([operation], pointer_cls=_JsonPointer).apply(document, in_place=True)
            _check_tree(document)
            output = _encode(document)
        except (jsonpatch.JsonPatchException, JsonPointerException, ValueError, TypeError,
                KeyError, IndexError, RecursionError) as error:
            raise ValueError(f"Patch operation {index} failed: {str(error)[:200]}") from error
    return output if operations else _encode(document)
