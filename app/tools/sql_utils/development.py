import json
import logging
import multiprocessing
import os

from . import service


_MAX_OUTPUT = 100000
_OPERATIONS = {
    "inspect": ("ddl",), "compare": ("before", "after"),
    "transpile": ("sql",), "lineage": ("sql", "schema_json"),
}


class _SqlError(ValueError):
    pass


class _UnknownQualifiers(Exception):
    def __init__(self, references):
        self.references = references


def _dump(result):
    output = json.dumps(result, indent=2, allow_nan=False)
    if len(output) > _MAX_OUTPUT:
        raise _SqlError("SQL tool output exceeds 100000 characters; reduce the input or limit")
    return output


def _bound_ast(trees):
    from sqlglot import exp

    stack, count = [(tree, 0) for tree in trees], 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > 10000 or depth > 100:
            raise _SqlError("SQL exceeds 10000 AST nodes or 100 nested levels")
        if isinstance(node, exp.Command):
            raise _SqlError("SQL contains a command the parser cannot fully analyze")
        if isinstance(node, exp.Identifier):
            _name(node.name)
        stack.extend((child, depth + 1) for child in node.iter_expressions())


def _name(value):
    if not isinstance(value, str) or not value or len(value) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise _SqlError("SQL identifiers must be nonempty, at most 200 characters, and contain no controls")
    return value


def _parse(content, dialect, maximum=50, normalize=True):
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.normalize_identifiers import normalize_identifiers

    trees = [tree for tree in sqlglot.parse(content, read=dialect, error_level=sqlglot.ErrorLevel.RAISE)
             if tree is not None and not isinstance(tree, exp.Semicolon)]
    if not trees or len(trees) > maximum:
        raise _SqlError(f"Provide between 1 and {maximum} SQL statements")
    _bound_ast(trees)
    return [normalize_identifiers(tree, dialect=dialect) for tree in trees] if normalize else trees


def _table(table, dialect):
    from sqlglot import exp

    if not isinstance(table, exp.Table) or not isinstance(table.this, exp.Identifier):
        raise _SqlError("Only literal table identifiers are supported")
    if any(value for key, value in table.args.items() if key not in {"this", "db", "catalog", "alias"}):
        raise _SqlError("Table modifiers are not supported")
    parts = [_name(part.name) for part in table.parts]
    plain = table.copy()
    plain.set("alias", None)
    return {"identity": parts, "name": plain.sql(dialect=dialect, comments=False)}


def _identifiers(nodes):
    from sqlglot import exp

    if not nodes or any(not isinstance(node, exp.Identifier) for node in nodes):
        raise _SqlError("Keys must contain explicit column identifiers")
    names = [_name(node.name) for node in nodes]
    if len(names) != len(set(names)):
        raise _SqlError("Duplicate columns in a key are not supported")
    return names


def _declared_type(kind, dialect):
    from sqlglot import exp

    if not isinstance(kind, exp.DataType) or kind.args.get("nested"):
        raise _SqlError("Schema inspection supports scalar declared column types only")
    allowed = (exp.DataType, exp.DataTypeParam, exp.Literal, exp.Identifier)
    for node in kind.walk():
        if not isinstance(node, allowed) or isinstance(node, exp.Literal) and (node.is_string or not node.is_number):
            raise _SqlError("Complex or literal-valued column types are not supported")
    text = kind.sql(dialect=dialect, comments=False)
    if len(text) > 500:
        raise _SqlError("Declared type exceeds 500 characters")
    return text


def _foreign_key(columns, reference, name, dialect):
    from sqlglot import exp

    if any(value for key, value in reference.args.items() if key not in {"this", "options"}):
        raise _SqlError("Unsupported foreign key reference modifiers")
    target = reference.this
    targets = _identifiers(target.expressions) if isinstance(target, exp.Schema) and target.expressions else []
    table = _table(target.this if isinstance(target, exp.Schema) else target, dialect)
    if targets and len(targets) != len(columns):
        raise _SqlError("Foreign key column counts do not match")
    options = reference.args.get("options") or []
    allowed = {f"ON {event} {action}" for event in ("DELETE", "UPDATE")
               for action in ("CASCADE", "RESTRICT", "SET NULL", "SET DEFAULT", "NO ACTION")}
    allowed.update({"DEFERRABLE", "NOT DEFERRABLE", "INITIALLY DEFERRED", "INITIALLY IMMEDIATE",
                    "MATCH FULL", "MATCH SIMPLE", "MATCH PARTIAL"})
    if any(not isinstance(option, str) or option not in allowed for option in options):
        raise _SqlError("Unsupported foreign key options")
    return {"name": name, "columns": columns, "referenced_table": table,
            "referenced_columns": targets, "options": sorted(options)}


def _schema(ddl, dialect, allow_empty=False):
    from sqlglot import exp

    if allow_empty and not ddl.strip():
        return []
    tables, identities, total_columns = [], set(), 0
    for tree in _parse(ddl, dialect):
        if (not isinstance(tree, exp.Create) or tree.args.get("kind") != "TABLE"
                or not isinstance(tree.this, exp.Schema) or not isinstance(tree.this.this, exp.Table)):
            raise _SqlError("Schema snapshots require explicit CREATE TABLE column declarations only")
        if any(value for key, value in tree.args.items() if key not in {"this", "kind"}):
            raise _SqlError("CREATE TABLE modifiers, properties, indexes and AS queries are not supported")
        row = _table(tree.this.this, dialect)
        identity = tuple(row["identity"])
        if identity in identities:
            raise _SqlError("Duplicate normalized table identities are not supported")
        identities.add(identity)
        columns, primary, unique, foreign, omitted, named = [], [], [], [], [], set()

        def constraint(kind, name=None, column=None):
            if name is not None:
                _name(name)
                if name in named:
                    raise _SqlError("Duplicate named constraints are not supported")
                named.add(name)
            if isinstance(kind, (exp.PrimaryKey, exp.PrimaryKeyColumnConstraint)):
                if any(value for key, value in kind.args.items() if key not in {"expressions", "include"}):
                    raise _SqlError("Primary key modifiers are not supported")
                keys = [column] if column else _identifiers(kind.expressions)
                if isinstance(kind, exp.PrimaryKey) and kind.args.get("include"):
                    if any(value for value in kind.args["include"].args.values()):
                        raise _SqlError("Primary key index options are not supported")
                primary.append({"name": name, "columns": keys})
            elif isinstance(kind, exp.UniqueColumnConstraint):
                keys = [column] if column else _identifiers(kind.this.expressions if isinstance(kind.this, exp.Schema) else [])
                if any(value for key, value in kind.args.items() if key not in {"this", "nulls"}):
                    raise _SqlError("Unique key index options are not supported")
                unique.append({"name": name, "columns": keys, "nulls_not_distinct": bool(kind.args.get("nulls"))})
            elif isinstance(kind, (exp.Reference, exp.ForeignKey)):
                if isinstance(kind, exp.ForeignKey) and any(value for key, value in kind.args.items() if key not in {"expressions", "reference"}):
                    raise _SqlError("Foreign key modifiers are not supported")
                keys = [column] if column else _identifiers(kind.expressions)
                reference = kind if isinstance(kind, exp.Reference) else kind.args.get("reference")
                if not isinstance(reference, exp.Reference):
                    raise _SqlError("Foreign keys require an explicit referenced table")
                foreign.append(_foreign_key(keys, reference, name, dialect))
            elif isinstance(kind, (exp.DefaultColumnConstraint, exp.CheckColumnConstraint)):
                return "default" if isinstance(kind, exp.DefaultColumnConstraint) else "check"
            else:
                raise _SqlError("Unsupported constraint in the CREATE TABLE subset")
            return None

        for item in tree.this.expressions:
            if isinstance(item, exp.ColumnDef):
                if not isinstance(item.this, exp.Identifier):
                    raise _SqlError("Columns require explicit identifier names")
                if any(value for key, value in item.args.items() if key not in {"this", "kind", "constraints"}):
                    raise _SqlError("Column declaration modifiers are not supported")
                name = _name(item.name)
                nullable, flags = None, []
                for wrapper in item.args.get("constraints") or []:
                    kind = wrapper.args.get("kind")
                    label = wrapper.this.name if isinstance(wrapper.this, exp.Identifier) else None
                    if isinstance(kind, exp.NotNullColumnConstraint):
                        if any(value for key, value in kind.args.items() if key != "allow_null"):
                            raise _SqlError("Nullability modifiers are not supported")
                        value = bool(kind.args.get("allow_null"))
                        if nullable is not None:
                            raise _SqlError("Multiple nullability declarations are not supported")
                        nullable = value
                    else:
                        flag = constraint(kind, label, name)
                        if flag:
                            flags.append(flag)
                columns.append({"name": name, "type": _declared_type(item.args.get("kind"), dialect),
                                "declared_nullable": nullable, "default_count": flags.count("default"),
                                "check_count": flags.count("check")})
            else:
                kinds = item.expressions if isinstance(item, exp.Constraint) else [item]
                label = item.this.name if isinstance(item, exp.Constraint) and isinstance(item.this, exp.Identifier) else None
                if len(kinds) != 1:
                    raise _SqlError("Named constraints must have one definition")
                flag = constraint(kinds[0], label)
                if flag:
                    omitted.append(flag)
        names = [column["name"] for column in columns]
        total_columns += len(columns)
        if not columns or len(columns) > 100 or total_columns > 1000:
            raise _SqlError("Schema limits are 100 columns per table and 1000 total columns")
        if len(names) != len(set(names)):
            raise _SqlError("Duplicate normalized column identities are not supported")
        if len(primary) > 1:
            raise _SqlError("Multiple primary key declarations are not supported")
        for key in primary + unique + foreign:
            if not set(key["columns"]).issubset(names):
                raise _SqlError("A key references an undeclared local column")
        row.update(columns=columns, primary_key=primary[0] if primary else None,
                   unique_keys=sorted(unique, key=lambda key: json.dumps(key, sort_keys=True)),
                   foreign_keys=sorted(foreign, key=lambda key: json.dumps(key, sort_keys=True)),
                   table_check_count=omitted.count("check"))
        tables.append(row)
    return tables


def _take(rows, limit, state):
    state["truncated"] |= len(rows) > limit
    return rows[:limit]


def _table_view(row, limit, state):
    result = dict(row)
    for key, count in (("columns", "column_count"), ("unique_keys", "unique_key_count"), ("foreign_keys", "foreign_key_count")):
        result[count] = len(row[key])
        result[key] = _take(row[key], limit, state)
    return result


_SCHEMA_NOTES = [
    "Selected declarations only. SQLGlot identifier normalization is used; database collation/search paths are not inferred.",
    "Nullability is explicitly declared: null means unspecified, including primary key columns. Types are parser-normalized, not database-resolved.",
    "Default and CHECK expressions, comments and literals are omitted; only their counts are compared. Other constraints or CREATE modifiers are rejected.",
    "No migration interpretation, referenced-table validation, rename guessing, execution, database validity or migration safety verdict.",
]


def _inspect(ddl, dialect, limit):
    rows, state = _schema(ddl, dialect), {"truncated": False}
    tables = [_table_view(row, limit, state) for row in _take(rows, limit, state)]
    return {"dialect": dialect, "table_count": len(rows), "column_count": sum(len(row["columns"]) for row in rows),
            "tables": tables, **state, "notes": _SCHEMA_NOTES}


def _compare(before, after, dialect, limit):
    old = {tuple(row["identity"]): row for row in _schema(before, dialect, allow_empty=True)}
    new = {tuple(row["identity"]): row for row in _schema(after, dialect, allow_empty=True)}
    state, comparisons = {"truncated": False}, []
    added, removed = sorted(new.keys() - old.keys()), sorted(old.keys() - new.keys())
    counts = {"added_tables": len(added), "removed_tables": len(removed), "changed_tables": 0,
              "added_columns": 0, "removed_columns": 0, "changed_columns": 0, "changed_constraint_groups": 0}
    for identity in sorted(old.keys() & new.keys()):
        left, right = old[identity], new[identity]
        a = {column["name"]: column for column in left["columns"]}
        b = {column["name"]: column for column in right["columns"]}
        column_added, column_removed = sorted(b.keys() - a.keys()), sorted(a.keys() - b.keys())
        column_changes = [{"name": name, "before": a[name], "after": b[name]}
                          for name in sorted(a.keys() & b.keys()) if a[name] != b[name]]
        groups = []
        for key in ("primary_key", "unique_keys", "foreign_keys", "table_check_count"):
            if left[key] != right[key]:
                change = {"kind": key, "before": left[key], "after": right[key]}
                if isinstance(left[key], list):
                    change.update(before_count=len(left[key]), after_count=len(right[key]),
                                  before=_take(left[key], limit, state), after=_take(right[key], limit, state))
                groups.append(change)
        counts["added_columns"] += len(column_added)
        counts["removed_columns"] += len(column_removed)
        counts["changed_columns"] += len(column_changes)
        counts["changed_constraint_groups"] += len(groups)
        if column_added or column_removed or column_changes or groups:
            comparisons.append({"identity": list(identity), "name": right["name"],
                                "added_column_count": len(column_added), "removed_column_count": len(column_removed),
                                "changed_column_count": len(column_changes), "changed_constraint_group_count": len(groups),
                                "added_columns": _take([b[name] for name in column_added], limit, state),
                                "removed_columns": _take([a[name] for name in column_removed], limit, state),
                                "column_changes": _take(column_changes, limit, state), "constraint_changes": _take(groups, limit, state)})
    counts["changed_tables"] = len(comparisons)
    return {"dialect": dialect, "before_table_count": len(old), "after_table_count": len(new),
            "matched_table_count": len(old.keys() & new.keys()), "counts": counts,
            "selected_fields_equal": not (added or removed or comparisons),
            "added_tables": _take([{"identity": list(key), "name": new[key]["name"]} for key in added], limit, state),
            "removed_tables": _take([{"identity": list(key), "name": old[key]["name"]} for key in removed], limit, state),
            "comparisons": _take(comparisons, limit, state), **state,
            "notes": _SCHEMA_NOTES + ["Counts use complete bounded snapshots before display limits. Table/column order and key declaration order are ignored. Column counts describe matched tables only."]}


def _transpile(sql, dialect, target_dialect):
    import sqlglot

    trees = _parse(sql, dialect, maximum=10, normalize=False)
    if any(tree.key not in service._STATEMENTS for tree in trees):
        raise _SqlError("Unsupported statement type for SQL translation")
    statements = [tree.sql(dialect=target_dialect, pretty=True, comments=False,
                           unsupported_level=sqlglot.ErrorLevel.RAISE) for tree in trees]
    # Verify generated text is parseable by the same target parser, not by a database.
    for statement in statements:
        _parse(statement, target_dialect, maximum=1, normalize=False)
    return {"source_dialect": dialect, "target_dialect": target_dialect, "statement_count": len(statements),
            "statements": statements, "truncated": False,
            "notes": ["Known unsupported translations raise errors. Generated statements are target-parser checked, not database validated.",
                      "Complete SQL is returned with comments omitted; literals and identifiers can be sensitive.",
                      "No schema/type inference, execution, optimization or guarantee of equivalent semantics. Test on the target database."]}


def _schema_json(content, dialect):
    from sqlglot import exp
    from sqlglot.optimizer.normalize_identifiers import normalize_identifiers

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise _SqlError("Duplicate schema JSON keys are not supported")
            result[key] = value
        return result

    def invalid_constant(value):
        raise _SqlError("Schema JSON must not contain nonfinite numbers")

    try:
        schema = json.loads(content, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (json.JSONDecodeError, RecursionError) as error:
        raise _SqlError("Invalid schema JSON; diagnostic values omitted") from error
    if not isinstance(schema, dict):
        raise _SqlError("Schema JSON must be a nested table-to-column-type object")
    stack, depths, tables, columns = [(schema, 0)], set(), 0, 0
    while stack:
        mapping, depth = stack.pop()
        if not mapping:
            if depth:
                raise _SqlError("Schema JSON cannot contain empty nested objects")
            continue
        if depth > 3:
            raise _SqlError("Schema JSON supports table, schema/table, or catalog/schema/table nesting")
        names = [normalize_identifiers(exp.to_identifier(_name(name)), dialect=dialect).name for name in mapping]
        if len(names) != len(set(names)):
            raise _SqlError("Duplicate normalized schema JSON identifiers are not supported")
        if all(isinstance(value, str) for value in mapping.values()):
            if depth == 0 or len(mapping) > 100:
                raise _SqlError("Schema JSON tables require 1 to 100 column/type entries")
            for value in mapping.values():
                _name(value)
            depths.add(depth)
            tables += 1
            columns += len(mapping)
        elif all(isinstance(value, dict) for value in mapping.values()):
            stack.extend((value, depth + 1) for value in mapping.values())
        else:
            raise _SqlError("Schema JSON requires uniform nested objects with string column types")
        if tables > 50 or columns > 1000:
            raise _SqlError("Schema JSON exceeds 50 tables or 1000 columns")
    if len(depths) > 1:
        raise _SqlError("Schema JSON table qualification depth must be uniform")
    return schema


def _lineage(sql, column, dialect, schema_json, limit):
    import sqlglot
    from sqlglot import exp
    from sqlglot.lineage import lineage
    from sqlglot.optimizer.qualify import qualify
    from sqlglot.optimizer.scope import build_scope
    from sqlglot.optimizer.normalize_identifiers import normalize_identifiers

    tree, = _parse(sql, dialect, maximum=1)
    if tree.key not in {"select", "union", "intersect", "except"} or tree.find(exp.Into):
        raise _SqlError("Lineage requires one SELECT/set query without INTO")
    for node in tree.find_all(exp.With):
        if node.args.get("recursive"):
            raise _SqlError("Recursive CTE lineage is not supported")
        names = [cte.alias_or_name for cte in node.expressions]
        if len(names) != len(set(names)):
            raise _SqlError("Duplicate normalized CTE names are ambiguous")
    for cte in tree.find_all(exp.CTE):
        if cte.this.unnest().key not in {"select", "union", "intersect", "except"}:
            raise _SqlError("CTE lineage supports SELECT/set query bodies only")
    if tree.find(exp.Pivot, exp.UDTF, exp.Lateral):
        raise _SqlError("Pivot, lateral and table-function lineage is not supported")
    for table in tree.find_all(exp.Table):
        _table(table, dialect)
    schema = _schema_json(schema_json, dialect)
    state, sources, unresolved = {"truncated": False}, {}, {}
    selected = column

    def unknown(reference, reason):
        unresolved[(reference, reason)] = {"reference": reference, "reason": reason}

    try:
        initial_scope = build_scope(tree)
        unknown_qualifiers = []
        if initial_scope:
            for item in initial_scope.traverse():
                if item.is_correlated_subquery:
                    raise _SqlError("Correlated subquery lineage is not supported")
                unknown_qualifiers.extend(value.sql(dialect=dialect, comments=False) for value in item.columns
                                          if value.table and value.table not in item.sources)
        # Qualification can reinterpret unknown qualifiers as struct fields. Do not guess.
        if unknown_qualifiers:
            raise _UnknownQualifiers(unknown_qualifiers)
        qualified = qualify(tree, dialect=dialect, schema=schema, infer_schema=not bool(schema),
                            validate_qualify_columns=False, identify=False)
        _bound_ast([qualified])
        scope = build_scope(qualified)
        if scope is None:
            raise _SqlError("Cannot build SELECT lineage scope")
        for item in scope.traverse():
            if item.is_correlated_subquery:
                raise _SqlError("Correlated subquery lineage is not supported")
            names = [value.alias_or_name for value in item.expression.selects if not value.is_star and value.alias_or_name]
            if len(names) != len(set(names)):
                raise _SqlError("Duplicate output column names are ambiguous; use distinct aliases")
        names = [value.alias_or_name for value in scope.expression.selects if not value.is_star]
        normalized = normalize_identifiers(exp.to_identifier(column), dialect=dialect).name
        selected = column if column in names else normalized
        if selected not in names:
            if scope.expression.is_star:
                unknown(column, "wildcard_requires_schema")
            else:
                raise _SqlError("Requested output column was not found; alias expressions explicitly")
        else:
            root = lineage(exp.column(selected, quoted=True), qualified, dialect=dialect, scope=scope, schema=schema)
            stack, visited = [root], set()
            while stack:
                node = stack.pop()
                if id(node) in visited:
                    continue
                visited.add(id(node))
                if len(visited) > 10000:
                    raise _SqlError("Lineage exceeds 10000 graph nodes")
                if node.expression.is_star:
                    unknown(selected, "wildcard_requires_schema")
                    continue
                if node.downstream:
                    stack.extend(node.downstream)
                elif isinstance(node.expression, exp.Table):
                    reference = sqlglot.parse_one(node.name, read=dialect, into=exp.Column)
                    if reference.is_star:
                        unknown(selected, "wildcard_requires_schema")
                    else:
                        table = _table(node.expression, dialect)
                        name = _name(reference.name)
                        sources[(tuple(table["identity"]), name)] = {"table": table, "column": name}
                elif isinstance(node.expression, exp.Placeholder):
                    reference = sqlglot.parse_one(node.name, read=dialect, into=exp.Column)
                    unknown(reference.sql(dialect=dialect, comments=False), "unresolved_or_ambiguous_reference")
    except _UnknownQualifiers as error:
        for reference in error.references:
            unknown(reference, "unknown_qualifier_or_unsupported_struct_reference")
    except sqlglot.errors.OptimizeError:
        unknown(column, "qualification_failed")
    source_rows = [sources[key] for key in sorted(sources)]
    unknown_rows = [unresolved[key] for key in sorted(unresolved)]
    return {"dialect": dialect, "output_column": selected, "schema_supplied": bool(schema),
            "column_references_resolved": not unresolved, "source_count": len(source_rows), "unresolved_count": len(unknown_rows),
            "sources": _take(source_rows, limit, state), "unresolved": _take(unknown_rows, limit, state), **state,
            "notes": ["Static projection-expression column lineage through aliases, CTEs and set queries; supplied schemas are caller assertions.",
                      "Without metadata, single-source columns may be inferred syntactically; ambiguous references and unexpanded wildcards remain unknown.",
                      "Constants and COUNT(*) may have no direct source columns. Joins, filters, row counts and control/row dependencies are not comprehensive lineage.",
                      "Expressions, literals and comments are omitted. Names may still be sensitive. No execution, runtime lineage or database validity guarantee."]}


def _worker(sender, operation, arguments):
    try:
        if os.name == "posix":
            import resource

            memory = 128 * 1024 * 1024
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            resource.setrlimit(resource.RLIMIT_AS, (memory if soft == resource.RLIM_INFINITY else min(soft, memory), hard))
            resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
        logging.getLogger("sqlglot").setLevel(logging.CRITICAL)
        function = {"inspect": _inspect, "compare": _compare, "transpile": _transpile, "lineage": _lineage}[operation]
        sender.send({"result": _dump(function(**arguments))})
    except _SqlError as error:
        sender.send({"error": str(error)})
    except Exception:
        sender.send({"error": "SQL parsing, translation or resolution failed; source and diagnostic values omitted"})
    finally:
        sender.close()


def run(operation, arguments):
    if operation not in _OPERATIONS:
        raise ValueError("Unsupported SQL tool operation")
    for name in _OPERATIONS[operation]:
        value = arguments.get(name)
        if not isinstance(value, str) or len(value) > 50000 or (operation != "compare" and not value.strip()):
            raise ValueError(f"{name} must be at most 50000 characters and nonempty except for comparison snapshots")
    for name in ("dialect", "target_dialect"):
        if name == "target_dialect" and operation != "transpile":
            continue
        if arguments.get(name) not in service._DIALECTS:
            raise ValueError("Supported dialects: " + ", ".join(sorted(service._DIALECTS)))
    if operation != "transpile" and (type(arguments.get("limit")) is not int or not 1 <= arguments["limit"] <= 50):
        raise ValueError("limit must be an integer between 1 and 50")
    if operation == "lineage":
        _name(arguments.get("column") or "")
    if not service._SQL_SLOT.acquire(blocking=False):
        raise ValueError("SQL analysis is busy; retry shortly")
    receiver = sender = process = None
    try:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_worker, args=(sender, operation, arguments))
        process.start()
        sender.close()
        if not receiver.poll(service._SQL_TIMEOUT):
            raise ValueError("SQL tool exceeded its 5-second limit")
        result = receiver.recv()
        if "error" in result:
            raise ValueError(result["error"])
        if not isinstance(result.get("result"), str) or len(result["result"]) > _MAX_OUTPUT:
            raise ValueError("SQL tool output exceeds 100000 characters")
        return result["result"]
    except EOFError as error:
        raise ValueError("SQL worker exited without a result (possibly a resource limit)") from error
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
            process.close()
        service._SQL_SLOT.release()
