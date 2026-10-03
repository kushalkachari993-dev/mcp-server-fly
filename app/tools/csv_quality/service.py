import csv
import io
import json
import multiprocessing
import os
import threading
from collections import defaultdict

from app.tools.csv_utils.service import read_csv
from app.tools.json_query.service import _check_tree
from app.tools.json_utils.tool import _parse_float, _reject_constant
from app.tools.manifest_utils.service import _unique_object
from app.tools.schema_utils.service import _make_validator, _pointer


_VALIDATION_SLOT = threading.BoundedSemaphore(1)
_WORKER_TIMEOUT = 5
_MAX_ERRORS = 50


class _Summary:
    def __init__(self, limit):
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        self.limit, self.truncated = limit, False

    def display(self, value):
        if isinstance(value, str):
            self.truncated |= len(value) > 1000
            return value[:1000]
        if isinstance(value, list):
            self.truncated |= len(value) > self.limit
            return [self.display(item) for item in value[:self.limit]]
        if isinstance(value, dict):
            return {key: self.display(item) for key, item in value.items()}
        return value


def _input(value):
    if not isinstance(value, str) or len(value) > 200000:
        raise ValueError("Input must be text of at most 200000 characters")


def _name(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 200
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("Column names must be nonempty strings of at most 200 characters without controls")
    return value


def _read(content, delimiter):
    _input(content)
    try:
        headers, rows = read_csv(content, delimiter, max_columns=100)
    except csv.Error as error:
        raise ValueError("Invalid or unsupported CSV; source values omitted") from error
    for name in headers:
        _name(name)
    return headers, rows


def _json(value):
    _input(value)
    try:
        result = json.loads(value, object_pairs_hook=_unique_object, parse_constant=_reject_constant, parse_float=_parse_float)
        _check_tree(result)
        return result
    except (ValueError, RecursionError) as error:
        raise ValueError("Invalid JSON: unique keys and finite values required; maximum 10000 nodes and depth 50; source omitted") from error


def _columns(value, *, allow_empty=False):
    names = _json(value)
    if not isinstance(names, list) or len(names) > 100 or (not names and not allow_empty):
        raise ValueError("Column selection must be a JSON array of " + ("0-100" if allow_empty else "1-100") + " names")
    names = [_name(name) for name in names]
    if len(names) != len(set(names)):
        raise ValueError("Selected column names must be unique")
    return names


def _require_columns(names, headers):
    if not set(names).issubset(headers):
        raise ValueError("Every selected column must exist in the supplied CSV header")


def profile(content, delimiter, limit):
    summary = _Summary(limit)
    headers, rows = _read(content, delimiter)
    columns = []
    for index, name in enumerate(headers):
        values = [row[index] for row in rows]
        nonempty = [value for value in values if value != ""]
        lengths = [len(value) for value in values]
        columns.append({"name": name, "empty_count": len(values) - len(nonempty), "nonempty_count": len(nonempty),
                        "whitespace_only_count": sum(bool(value) and not value.strip() for value in values),
                        "distinct_value_count": len(set(values)), "distinct_nonempty_value_count": len(set(nonempty)),
                        "min_length": min(lengths) if lengths else None, "max_length": max(lengths) if lengths else None,
                        "mean_length": sum(lengths) / len(lengths) if lengths else None})
    unique_rows = len({tuple(row) for row in rows})
    displayed = summary.display(columns)
    return {"row_count": len(rows), "column_count": len(headers), "unique_row_count": unique_rows,
            "duplicate_row_count": len(rows) - unique_rows, "columns": displayed, "truncated": summary.truncated,
            "notes": ["Counts and string lengths only; cell values, samples and inferred types are not returned.",
                      "Empty means exactly an empty string; whitespace-only cells are nonempty and counted separately. Distinct values and duplicate rows use exact case-sensitive strings.",
                      "String lengths count Unicode code points, not bytes/graphemes. Empty tables have zero distinct counts and null length statistics.",
                      "Header required; malformed/ragged rows rejected. Blank physical records skipped; row counts exclude headers. No file/network access or execution."]}


def _index_rows(headers, rows, keys):
    positions = [headers.index(key) for key in keys]
    index, unkeyed = defaultdict(list), []
    for number, row in enumerate(rows, 1):
        identity = tuple(row[position] for position in positions)
        if any(not value.strip() for value in identity):
            unkeyed.append(number)
        else:
            index[identity].append((number, dict(zip(headers, row))))
    return index, unkeyed


def compare(before, after, key_columns_json, delimiter, limit):
    summary = _Summary(limit)
    keys = _columns(key_columns_json)
    tables = [_read(content, delimiter) for content in (before, after)]
    for headers, _ in tables:
        _require_columns(keys, headers)
    indexes = [_index_rows(*table, keys) for table in tables]
    (left, unkeyed_before), (right, unkeyed_after) = indexes
    added, removed, ambiguous, changes = [], [], [], []
    matched = unchanged = cell_changes = 0
    for identity in dict.fromkeys([*left, *right]):
        old, new = left.get(identity, []), right.get(identity, [])
        key = dict(zip(keys, identity))
        if len(old) > 1 or len(new) > 1:
            ambiguous.append({"key": key, "before_count": len(old), "after_count": len(new),
                              "before_rows": [row[0] for row in old], "after_rows": [row[0] for row in new]})
        elif not old:
            added.append({"key": key, "row": new[0][0]})
        elif not new:
            removed.append({"key": key, "row": old[0][0]})
        else:
            matched += 1
            old_number, old_row = old[0]
            new_number, new_row = new[0]
            differences = []
            for column in dict.fromkeys([*old_row, *new_row]):
                if column not in old_row or column not in new_row or old_row[column] != new_row[column]:
                    differences.append({"column": column, "type": "added" if column not in old_row else "removed" if column not in new_row else "changed",
                                        "before_present": column in old_row, "after_present": column in new_row,
                                        "before": old_row.get(column), "after": new_row.get(column)})
            if differences:
                changes.append({"key": key, "before_row": old_number, "after_row": new_number,
                                "change_count": len(differences), "changes": differences})
                cell_changes += len(differences)
            else:
                unchanged += 1
    old_headers, new_headers = tables[0][0], tables[1][0]
    added_columns = [name for name in new_headers if name not in old_headers]
    removed_columns = [name for name in old_headers if name not in new_headers]
    uncertain = bool(ambiguous or unkeyed_before or unkeyed_after)
    known_change = bool(changes or added or removed or added_columns or removed_columns)
    result = {"before": {"row_count": len(tables[0][1]), "column_count": len(old_headers)},
              "after": {"row_count": len(tables[1][1]), "column_count": len(new_headers)},
              "key_column_count": len(keys), "key_columns": keys,
              "equal": False if known_change else None if uncertain else True,
              "column_order_changed": old_headers != new_headers if not added_columns and not removed_columns else None,
              "row_order_changed": list(left) != list(right) if not uncertain and not added and not removed else None,
              "added_column_count": len(added_columns), "removed_column_count": len(removed_columns),
              "added_columns": added_columns, "removed_columns": removed_columns,
              "matched_row_count": matched, "unchanged_row_count": unchanged, "changed_row_count": len(changes),
              "changed_cell_count": cell_changes, "added_row_count": len(added), "removed_row_count": len(removed),
              "ambiguous_key_count": len(ambiguous), "unkeyed_before_count": len(unkeyed_before), "unkeyed_after_count": len(unkeyed_after),
              "added_rows": added, "removed_rows": removed, "ambiguous_keys": ambiguous,
              "unkeyed_before_rows": unkeyed_before, "unkeyed_after_rows": unkeyed_after, "changes": changes}
    result = summary.display(result)
    result["truncated"] = summary.truncated
    result["notes"] = [
        "Exact composite string keys; no concatenation, numeric conversion, case folding or trimming. Empty/whitespace-only key components make rows unkeyed; duplicates are ambiguous even on only one side.",
        "Equal ignores row/column order, which is reported separately when comparable. Known data/schema changes give false; only ambiguous/unkeyed records give null, not a guessed match.",
        "Row numbers are 1-based data-record ordinals after skipped blank records, not physical lines. Added/removed rows return keys/ordinals only; matched changes return cell values with presence flags.",
        "Full bounded rows and strings compared before limiting lists/1000-character previews. Empty cells differ from absent columns; counts include changes beyond display limits.",
        "Keys, headers and changed values may be sensitive. No file/network access, implicit keys, row-position pairing or completeness/causal inference."]
    return result


def redact(content, columns_json, delimiter, mask):
    names = _columns(columns_json)
    if not isinstance(mask, str) or len(mask) > 200 or "\0" in mask:
        raise ValueError("mask must be text of at most 200 characters without NUL")
    headers, rows = _read(content, delimiter)
    _require_columns(names, headers)
    selected = {headers.index(name) for name in names}
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([mask if index in selected else value for index, value in enumerate(row)])
        if output.tell() > 100000:
            raise ValueError("Redacted CSV exceeds 100000 characters; reduce input/mask")
    return {"row_count": len(rows), "column_count": len(headers), "redacted_columns": names,
            "replacement_count": len(rows) * len(names), "csv": output.getvalue(), "truncated": False,
            "notes": ["Every selected cell, including empty cells, is replaced; headers and all unselected cell values are retained.",
                      "CSV quoting is regenerated and record separators normalized to CRLF; blank records skipped. Embedded newlines/commas/quotes and leading zeros in retained cells are preserved.",
                      "Only explicit columns are redacted. No automatic secret/PII discovery, complete anonymization, formula-injection sanitization, file/network access or execution. Output is complete or an error, never a partial table."]}


def _validate_rows(headers, rows, schema, required, limit):
    summary = _Summary(limit)
    validator = _make_validator(schema)
    missing = [name for name in required if name not in headers]
    errors, invalid_rows = [], []
    capped = False
    for number, row in enumerate(rows, 1):
        invalid = False
        for error in validator.iter_errors(dict(zip(headers, row))):
            invalid = True
            if len(errors) == _MAX_ERRORS:
                capped = True
                break
            errors.append({"row": number, "path": _pointer(error.absolute_path),
                           "schema_path": _pointer(error.absolute_schema_path), "keyword": error.validator or "false_schema"})
        if invalid:
            invalid_rows.append(number)
    result = summary.display({"valid": not missing and not invalid_rows, "row_count": len(rows), "column_count": len(headers),
                              "header_check": {"required_count": len(required), "missing_count": len(missing), "missing_columns": missing},
                              "validated_row_count": len(rows), "valid_row_count": len(rows) - len(invalid_rows),
                              "invalid_row_count": len(invalid_rows), "invalid_rows": invalid_rows,
                              "reported_error_count": len(errors), "errors": errors, "errors_capped": capped})
    result["truncated"] = summary.truncated or capped
    result["notes"] = [
        "Each row is an object mapping exact column names to string cells; no number/boolean/null conversion, trimming, defaults or inferred types. Empty string is present, not a missing property; use minLength to reject it.",
        "required_columns_json is an independent explicit header check, including header-only tables. JSON Schema required/conditional/reference rules apply to actual rows only; with no data rows, per-row validation is vacuous.",
        "Known JSON Schema drafts supported; default 2020-12. Local references and installed format checks work; unknown formats remain unchecked. External resource retrieval is disabled.",
        "All rows classified within worker bounds. At most 50 diagnostics collected; after that the first failure classifies each remaining row without enumerating further errors. reported_error_count is collected diagnostics, not total possible violations.",
        "Diagnostics contain row ordinals, keyword IDs and JSON Pointer paths, not library messages or cell/schema literals. Names/paths can still be sensitive. No file/network access or execution."]
    return result


def _resource_limits():
    if os.name == "posix":
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (4, 4))


def _validation_worker(sender, headers, rows, schema, required, limit):
    try:
        # Isolate schema regex/reference work so a timeout can stop it completely.
        _resource_limits()
        result = _validate_rows(headers, rows, schema, required, limit)
        if len(json.dumps(result, allow_nan=False)) > 100000:
            sender.send({"error": "CSV validation output exceeds 100000 characters; reduce input/limit"})
        else:
            sender.send({"result": result})
    except Exception:
        sender.send({"error": "CSV schema validation failed; schema and cell values omitted"})
    finally:
        sender.close()


def _run_validation(headers, rows, schema, required, limit):
    if not _VALIDATION_SLOT.acquire(blocking=False):
        raise ValueError("CSV schema worker is busy; retry later")
    receiver = sender = process = None
    try:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_validation_worker, args=(sender, headers, rows, schema, required, limit))
        process.start()
        sender.close()
        if not receiver.poll(_WORKER_TIMEOUT):
            raise ValueError("CSV schema validation exceeded its five-second worker limit")
        result = receiver.recv()
        if "error" in result:
            raise ValueError(result["error"])
        return result["result"]
    except (EOFError, OSError) as error:
        raise ValueError("CSV schema worker exited or could not start; source omitted") from error
    finally:
        if sender is not None:
            sender.close()
        if receiver is not None:
            receiver.close()
        if process is not None and process.pid is not None:
            process.join(timeout=0.2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join()
        if process is not None:
            process.close()
        _VALIDATION_SLOT.release()


def validate(content, schema_json, required_columns_json, delimiter, limit):
    _Summary(limit)
    required = _columns(required_columns_json, allow_empty=True)
    schema = _json(schema_json)
    if not isinstance(schema, (dict, bool)):
        raise ValueError("schema_json must be a JSON Schema object or boolean")
    headers, rows = _read(content, delimiter)
    return _run_validation(headers, rows, schema, required, limit)
