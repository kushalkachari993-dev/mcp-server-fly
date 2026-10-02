import json
import logging
import multiprocessing
import os
import threading


_DIALECTS = {"postgres", "mysql", "sqlite", "bigquery", "snowflake", "tsql", "duckdb", "redshift", "trino"}
_STATEMENTS = {"select", "union", "intersect", "except", "subquery", "insert", "update", "delete",
               "merge", "create", "alter", "drop", "truncatetable"}
_SQL_TIMEOUT = 5
_SQL_SLOT = threading.BoundedSemaphore(1)
_MAX_OUTPUT = 100000


def _analyze(sql, dialect):
    import sqlglot
    from sqlglot import exp

    # SQLGlot retains comments after statement separators as Semicolon nodes.
    trees = [tree for tree in sqlglot.parse(sql, read=dialect, error_level=sqlglot.ErrorLevel.RAISE)
             if tree is not None and not isinstance(tree, exp.Semicolon)]
    if not trees or len(trees) > 10:
        raise ValueError("Provide between 1 and 10 SQL statements")
    statements = []
    node_count = 0
    for tree in trees:
        if tree.key not in _STATEMENTS:
            raise ValueError(f"Unsupported SQL statement type: {tree.key.upper()}")
        row = {"type": tree.key.upper(), "tables": [], "columns": [], "ctes": [],
               "has_wildcards": False, "truncated": False}
        seen = {key: set() for key in ("tables", "columns", "ctes")}

        def collect(key, value):
            if value in seen[key]:
                return
            if len(row[key]) >= 100:
                row["truncated"] = True
                return
            seen[key].add(value)
            row["truncated"] |= len(value) > 500
            row[key].append(value[:500])

        stack = [(tree, 0)]
        while stack:
            node, depth = stack.pop()
            node_count += 1
            if node_count > 10000 or depth > 100:
                raise ValueError("SQL exceeds 10000 AST nodes or 100 nested levels")
            if isinstance(node, exp.Command):
                raise ValueError("SQL contains a command the parser cannot fully analyze")
            if isinstance(node, exp.Table):
                collect("tables", node.sql(dialect=dialect, comments=False))
            elif isinstance(node, exp.Column):
                collect("columns", node.sql(dialect=dialect, comments=False))
            elif isinstance(node, exp.CTE):
                collect("ctes", node.alias_or_name)
            elif isinstance(node, exp.Star):
                row["has_wildcards"] = True
            stack.extend((child, depth + 1) for child in reversed(list(node.iter_expressions())))
        statements.append(row)
    result = {"dialect": dialect, "statement_count": len(statements), "statements": statements,
              "truncated": any(row["truncated"] for row in statements),
              "notice": "Syntactic references only, including CTE references. Aliases, wildcards, schema, "
                        "types, and side effects are not resolved. SQL is never executed; "
                        "successful parsing does not prove database validity or query safety."}
    output = json.dumps(result, indent=2)
    if len(output) > _MAX_OUTPUT:
        raise ValueError("SQL analysis output exceeds 100000 characters; analyze fewer statements")
    return output


def _sql_worker(sender, sql, dialect):
    try:
        if os.name == "posix":
            import resource

            memory = 128 * 1024 * 1024
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            resource.setrlimit(resource.RLIMIT_AS, (memory if soft == resource.RLIM_INFINITY else min(soft, memory), hard))
            resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
        # SQLGlot's fallback warnings can echo the supplied SQL; return bounded errors instead.
        logging.getLogger("sqlglot").setLevel(logging.ERROR)
        sender.send({"result": _analyze(sql, dialect)})
    except Exception as error:
        sender.send({"error": f"SQL analysis failed: {str(error)[:300]}"})
    finally:
        sender.close()


def analyze(sql, dialect):
    if not sql.strip() or len(sql) > 50000:
        raise ValueError("SQL must be nonempty and at most 50000 characters")
    if dialect not in _DIALECTS:
        raise ValueError("Supported dialects: " + ", ".join(sorted(_DIALECTS)))
    if not _SQL_SLOT.acquire(blocking=False):
        raise ValueError("SQL analysis is busy; retry shortly")
    receiver = sender = process = None
    try:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_sql_worker, args=(sender, sql, dialect))
        process.start()
        sender.close()
        if not receiver.poll(_SQL_TIMEOUT):
            raise ValueError("SQL analysis exceeded its 5-second limit")
        result = receiver.recv()
        if "error" in result:
            raise ValueError(result["error"])
        return result["result"]
    except EOFError as error:
        raise ValueError("SQL analysis worker exited without a result (possibly a resource limit)") from error
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
        _SQL_SLOT.release()
