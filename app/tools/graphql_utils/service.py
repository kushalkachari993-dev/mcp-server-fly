import json
import multiprocessing
import os
import threading
from collections import Counter

from graphql import (
    GraphQLError, Undefined, build_ast_schema, find_breaking_changes,
    find_dangerous_changes, is_enum_type, is_input_object_type, is_interface_type,
    is_object_type, is_required_argument, is_required_input_field, is_scalar_type,
    is_specified_directive, is_specified_scalar_type, is_union_type, parse,
    specified_rules, validate, validate_schema, value_from_ast,
)
from graphql.language import Lexer, Node, Source, TokenKind

from app.tools.report_utils.service import _Summary


_WORKER_TIMEOUT = 5
_WORKER_SLOT = threading.BoundedSemaphore(1)


class _AnalysisError(ValueError):
    pass


def _parse(content, maximum):
    lexer, count, depth = Lexer(Source(content)), 0, 0
    while True:
        token = lexer.advance()
        if token.kind == TokenKind.EOF:
            break
        count += 1
        if count > maximum:
            raise _AnalysisError(f"GraphQL exceeds {maximum} tokens")
        if token.kind == TokenKind.NAME and len(token.value) > 1000:
            raise _AnalysisError("GraphQL names exceed 1000 characters")
        if token.kind in {TokenKind.BRACE_L, TokenKind.BRACKET_L, TokenKind.PAREN_L}:
            depth += 1
            if depth > 50:
                raise _AnalysisError("GraphQL exceeds 50 nesting levels")
        elif token.kind in {TokenKind.BRACE_R, TokenKind.BRACKET_R, TokenKind.PAREN_R}:
            depth -= 1
    document = parse(content, max_tokens=maximum)
    if len(document.definitions) > 200:
        raise _AnalysisError("GraphQL exceeds 200 definitions")
    stack, nodes = [document], 0
    while stack:
        node = stack.pop()
        nodes += 1
        if nodes > 10000:
            raise _AnalysisError("GraphQL exceeds 10000 AST nodes")
        for key in node.keys:
            if key == "loc":
                continue
            value = getattr(node, key, None)
            if isinstance(value, Node):
                stack.append(value)
            elif isinstance(value, tuple):
                stack.extend(child for child in value if isinstance(child, Node))
    return document


def _build(content):
    try:
        document = _parse(content, 8000)
        schema = build_ast_schema(document)
        if validate_schema(schema):
            raise TypeError("invalid schema")
        defaults = [argument for directive in schema.directives for argument in directive.args.values()]
        for value in _types(schema):
            if is_input_object_type(value):
                defaults.extend(value.fields.values())
            elif is_object_type(value) or is_interface_type(value):
                defaults.extend(argument for field in value.fields.values() for argument in field.args.values())
        for value in defaults:
            node = value.ast_node.default_value if value.ast_node else None
            if node is not None and value_from_ast(node, value.type) is Undefined:
                raise TypeError("invalid default literal")
        return schema
    except _AnalysisError:
        raise
    except (GraphQLError, TypeError, ValueError) as error:
        raise _AnalysisError("Invalid GraphQL schema SDL; source and diagnostic values omitted") from error


def _kind(value):
    for name, predicate in (("object", is_object_type), ("interface", is_interface_type), ("input_object", is_input_object_type),
                            ("enum", is_enum_type), ("union", is_union_type), ("scalar", is_scalar_type)):
        if predicate(value):
            return name
    raise ValueError("Unsupported GraphQL type")


def _roots(schema):
    return {name: getattr(schema, f"{name}_type").name if getattr(schema, f"{name}_type") else None
            for name in ("query", "mutation", "subscription")}


def _types(schema):
    return [value for name, value in schema.type_map.items() if not name.startswith("__")]


def _argument(name, value, input_field=False):
    return {"name": name, "type": str(value.type), "has_default": value.default_value is not Undefined,
            "required": is_required_input_field(value) if input_field else is_required_argument(value),
            "deprecated": value.deprecation_reason is not None}


def _inspect(content, limit):
    summary, schema = _Summary(content, limit), _build(content)
    types, kinds, total_fields, total_arguments, deprecated = [], Counter(), 0, 0, Counter()
    for value in _types(schema):
        kind = _kind(value)
        kinds[kind] += 1
        row = {"name": value.name, "kind": kind, "specified_scalar": is_specified_scalar_type(value)}
        if kind in {"object", "interface", "input_object"}:
            fields = []
            for name, field in value.fields.items():
                total_fields += 1
                if kind == "input_object":
                    item = _argument(name, field, True)
                else:
                    arguments = [_argument(key, argument) for key, argument in field.args.items()]
                    total_arguments += len(arguments)
                    deprecated["arguments"] += sum(argument["deprecated"] for argument in arguments)
                    item = {"name": name, "type": str(field.type), "deprecated": field.deprecation_reason is not None,
                            "argument_count": len(arguments), "arguments": summary.take(arguments)}
                deprecated["input_fields" if kind == "input_object" else "fields"] += item["deprecated"]
                fields.append(item)
            row.update(field_count=len(fields), fields=summary.take(fields))
            if kind != "input_object":
                row.update(interface_count=len(value.interfaces), interfaces=summary.take([item.name for item in value.interfaces]))
        elif kind == "enum":
            values = [{"name": name, "deprecated": item.deprecation_reason is not None} for name, item in value.values.items()]
            deprecated["enum_values"] += sum(item["deprecated"] for item in values)
            row.update(value_count=len(values), values=summary.take(values))
        elif kind == "union":
            row.update(member_count=len(value.types), members=summary.take([item.name for item in value.types]))
        types.append(row)
    directives = []
    for directive in schema.directives:
        arguments = [_argument(name, value) for name, value in directive.args.items()]
        directives.append({"name": directive.name, "specified": is_specified_directive(directive),
                           "repeatable": directive.is_repeatable, "locations": [location.name for location in directive.locations],
                           "argument_count": len(arguments), "arguments": summary.take(arguments)})
    return {"valid_schema": True, "operation_roots": _roots(schema), "type_count": len(types), "type_counts": dict(sorted(kinds.items())),
            "field_count": total_fields, "field_argument_count": total_arguments, "directive_count": len(directives),
            "deprecated_counts": {name: deprecated[name] for name in ("fields", "arguments", "input_fields", "enum_values")},
            "types": summary.take(types), "directives": summary.take(directives), "truncated": summary.truncated,
            "notes": ["GraphQL-core 3.2 SDL/schema validation. Introspection types are excluded; referenced specified scalars/directives are identified.",
                      "Descriptions, default values, scalar URLs, directive application values and deprecation reasons are omitted. Names may still be sensitive.",
                      "No import resolution, introspection requests, resolvers, variable coercion or custom scalar execution. Validity does not prove runtime behavior or authorization."]}


def _diagnostic(error, summary, rule=None):
    nodes = error.nodes or []
    names = list(dict.fromkeys(node.name.value for node in nodes if getattr(node, "name", None) is not None))
    return {"rule": rule or error.extensions.get("validation_rule", "ValidationAborted"),
            "message": "GraphQL syntax is invalid." if rule == "SyntaxError" else "GraphQL validation rule failed; literal values omitted.",
            "locations": summary.take([{"line": location.line, "column": location.column} for location in error.locations or []], 5),
            "node_kinds": summary.take(list(dict.fromkeys(node.kind for node in nodes)), 5), "identifiers": summary.take(names, 5)}


def _validate(schema_sdl, document, limit):
    summary, schema = _Summary(document, limit), _build(schema_sdl)
    try:
        parsed = _parse(document, 4000)
    except GraphQLError as error:
        return {"valid": False, "phase": "syntax", "error_count": 1, "errors_capped": False,
                "errors": [_diagnostic(error, summary, "SyntaxError")], "truncated": summary.truncated}
    operations = [node for node in parsed.definitions if node.kind == "operation_definition"]
    fragments = [node for node in parsed.definitions if node.kind == "fragment_definition"]
    errors = []
    if not operations:
        errors.append(GraphQLError("operation required", extensions={"validation_rule": "ExecutableOperationRequired"}))
    # Keep library rule algorithms unchanged; separate passes give reliable diagnostic IDs.
    for rule in specified_rules:
        budget = 50 - len(errors)
        found = validate(schema, parsed, rules=(rule,), max_errors=budget)
        for index, error in enumerate(found):
            error.extensions = {"validation_rule": rule.__name__ if index < budget else "ValidationAborted"}
        errors.extend(found)
        if len(errors) > 50:
            break
    rows = [{"name": node.name.value if node.name else None, "operation": node.operation.value,
             "variable_count": len(node.variable_definitions), "variables": summary.take([
                 {"name": variable.variable.name.value, "has_default": variable.default_value is not None}
                 for variable in node.variable_definitions])} for node in operations]
    diagnostics = [_diagnostic(error, summary) for error in errors]
    return {"valid": not errors, "phase": "validation", "operation_count": len(operations), "fragment_count": len(fragments),
            "operations": summary.take(rows), "error_count": len(errors), "errors_capped": len(errors) > 50,
            "errors": summary.take(diagnostics), "truncated": summary.truncated,
            "notes": ["All operations/fragments are statically checked with GraphQL-core's specified rules, not executed. Error counts are capped observations, not total errors beyond the abort limit.",
                      "Rule IDs, node kinds, identifiers and locations replace library messages to avoid echoing literal values. Identifiers may still be sensitive.",
                      "Runtime variable values, custom scalar semantics, authorization, query costs and resolver behavior are not validated. SDL/default values are not returned."]}


def _compare(before, after, limit):
    summary, old, new = _Summary(before, limit), _build(before), _build(after)
    breaking, dangerous = find_breaking_changes(old, new), find_dangerous_changes(old, new)

    def rows(changes):
        return [{"kind": change.type.name, "description": "Argument default changed; values omitted."
                 if change.type.name == "ARG_DEFAULT_VALUE_CHANGE" else summary.text(change.description)} for change in changes]

    old_roots, new_roots = _roots(old), _roots(new)
    root_changes = [{"operation": name, "before": old_roots[name], "after": new_roots[name],
                     "kind": "root_added" if old_roots[name] is None else "root_removed" if new_roots[name] is None else "root_replaced",
                     "needs_review": True} for name in old_roots if old_roots[name] != new_roots[name]]
    old_names, new_names = {value.name for value in _types(old)}, {value.name for value in _types(new)}
    return {"before": {"type_count": len(old_names), "operation_roots": old_roots},
            "after": {"type_count": len(new_names), "operation_roots": new_roots},
            "breaking_change_count": len(breaking), "dangerous_change_count": len(dangerous),
            "breaking_changes": summary.take(rows(breaking)), "dangerous_changes": summary.take(rows(dangerous)),
            "root_change_count": len(root_changes), "root_changes": summary.take(root_changes),
            "added_type_count": len(new_names - old_names), "removed_type_count": len(old_names - new_names),
            "added_types": summary.take(sorted(new_names - old_names)), "removed_types": summary.take(sorted(old_names - new_names)),
            "truncated": summary.truncated,
            "notes": ["GraphQL-core 3.2 breaking/dangerous categories, plus root changes for separate review. Not an exhaustive compatibility proof, generic text diff or classification of every addition.",
                      "Default-change values are replaced with a fixed description; descriptions/defaults/directive application values are not returned. Names and type references may be sensitive.",
                      "Root replacement is a review item, not automatically a breaking client contract. Custom scalar/directive semantics, resolver behavior, auth and runtime variable coercion are outside scope."]}


def _resource_limits():
    if os.name == "posix":
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (4, 4))


def _worker(sender, action, arguments):
    try:
        _resource_limits()
        result = {"inspect": _inspect, "validate": _validate, "compare": _compare}[action](*arguments)
        output = json.dumps(result, allow_nan=False)
        if len(output) > 100000:
            raise _AnalysisError("GraphQL summary exceeds 100000 characters; reduce input/limit")
        sender.send({"result": result})
    except _AnalysisError as error:
        sender.send({"error": str(error)})
    except Exception:
        sender.send({"error": "GraphQL analysis failed; source and diagnostic values omitted"})
    finally:
        sender.close()


def _run_worker(action, arguments):
    if not _WORKER_SLOT.acquire(blocking=False):
        raise ValueError("GraphQL worker is busy; retry later")
    receiver = sender = process = None
    try:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_worker, args=(sender, action, arguments))
        process.start()
        sender.close()
        if not receiver.poll(_WORKER_TIMEOUT):
            raise ValueError("GraphQL analysis exceeded its five-second worker limit")
        result = receiver.recv()
        if "error" in result:
            raise ValueError(result["error"])
        return result["result"]
    except (EOFError, OSError) as error:
        raise ValueError("GraphQL worker exited or could not start; source omitted") from error
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
        _WORKER_SLOT.release()


def inspect_schema(schema_sdl, limit):
    _Summary(schema_sdl, limit)
    return _run_worker("inspect", (schema_sdl, limit))


def validate_operation(schema_sdl, document, limit):
    _Summary(schema_sdl, limit)
    _Summary(document, limit)
    return _run_worker("validate", (schema_sdl, document, limit))


def compare_schemas(before_sdl, after_sdl, limit):
    _Summary(before_sdl, limit)
    _Summary(after_sdl, limit)
    return _run_worker("compare", (before_sdl, after_sdl, limit))
