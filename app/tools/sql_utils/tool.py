import re

import anyio

from . import development, service


_KEYWORDS = [
    "SELECT",
    "FROM",
    "WHERE",
    "GROUP BY",
    "ORDER BY",
    "HAVING",
    "LIMIT",
    "OFFSET",
    "JOIN",
    "LEFT JOIN",
    "RIGHT JOIN",
    "INNER JOIN",
    "OUTER JOIN",
    "FULL JOIN",
    "CROSS JOIN",
    "ON",
    "UNION",
    "VALUES",
    "INSERT INTO",
    "UPDATE",
    "SET",
    "DELETE FROM",
    "RETURNING",
]


def _normalize_spaces(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip())


def _uppercase_keywords(sql: str) -> str:
    for keyword in sorted(_KEYWORDS, key=len, reverse=True):
        pattern = r"\b" + re.escape(keyword).replace(r"\ ", r"\s+") + r"\b"
        sql = re.sub(pattern, keyword, sql, flags=re.IGNORECASE)
    return sql


def register(mcp):

    @mcp.tool()
    async def inspect_sql_schema(ddl: str, dialect: str = "postgres", limit: int = 20) -> str:
        """Inspect a supplied CREATE TABLE subset offline: scalar declared types,
        explicit nullability, primary/unique/foreign keys, default/CHECK counts.
        Expressions/literals are omitted; other constraints and CREATE modifiers
        are rejected. Not a migration interpreter or database validity check.
        Nine analyze_sql dialects; 50000 characters, 50 tables, 100 columns/table,
        1000 columns total; limit 1-50, 100000 output characters, 5-second worker.
        """
        try:
            return await anyio.to_thread.run_sync(development.run, "inspect", {"ddl": ddl, "dialect": dialect, "limit": limit})
        except (ValueError, RecursionError, OSError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def compare_sql_schemas(before: str, after: str, dialect: str = "postgres", limit: int = 20) -> str:
        """Compare supported supplied CREATE TABLE snapshots by normalized qualified
        table and column identifiers. Complete bounded counts precede limit 1-50.
        Compare selected types, explicit nullability and keys, not default/CHECK
        expressions or declaration order. Empty strings represent empty snapshots.
        No rename guesses or migration safety verdict. Same input/schema/worker
        limits as inspect_sql_schema.
        """
        try:
            return await anyio.to_thread.run_sync(development.run, "compare", {
                "before": before, "after": after, "dialect": dialect, "limit": limit})
        except (ValueError, RecursionError, OSError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def transpile_sql(sql: str, source_dialect: str, target_dialect: str) -> str:
        """Translate up to 10 SQL statements between explicit analyze_sql dialects
        with SQLGlot, raising on known unsupported translations. Return complete
        target-parser-checked SQL without comments; literals are NOT redacted.
        No execution or semantic equivalence guarantee. 50000 input characters,
        100000 output characters and shared 5-second isolated SQL worker.
        """
        try:
            return await anyio.to_thread.run_sync(development.run, "transpile", {
                "sql": sql, "dialect": source_dialect, "target_dialect": target_dialect})
        except (ValueError, RecursionError, OSError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def extract_sql_lineage(sql: str, column: str, dialect: str = "postgres", schema_json: str = "{}", limit: int = 20) -> str:
        """Trace one named SELECT output's projection column dependencies through
        aliases, CTEs and set queries. Optional schema JSON: {table:{column:type}},
        optionally uniformly nested by schema/catalog; ambiguous columns and
        wildcards without metadata remain unresolved. Not row/control/runtime
        lineage; no recursive/DML CTE, correlated/lateral/pivot/table-function support.
        50000 characters/input, 50 schema tables/1000 columns, limit 1-50,
        100000 output characters, shared 5-second worker. Never execute SQL.
        """
        try:
            return await anyio.to_thread.run_sync(development.run, "lineage", {
                "sql": sql, "column": column, "dialect": dialect, "schema_json": schema_json, "limit": limit})
        except (ValueError, RecursionError, OSError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def analyze_sql(sql: str, dialect: str = "postgres") -> str:
        """Analyze SQL with SQLGlot without executing it. Returns statement types,
        syntactic table/column references (including CTE names), and wildcard flags.
        Supports postgres, mysql, sqlite, bigquery, snowflake, tsql, duckdb, redshift,
        and trino. No schema validation or safety guarantee. Limits: 50000 input
        characters, 10 statements, 100 references of each kind per statement,
        100000 output characters, and one isolated worker with a 5-second timeout.
        """
        try:
            return await anyio.to_thread.run_sync(service.analyze, sql, dialect)
        except (ValueError, RecursionError, OSError) as error:
            return f"Error: {error}"

    @mcp.tool()
    def format_sql(sql: str) -> str:
        """
        Format common SQL by uppercasing keywords and placing major clauses on new lines.
        This is a lightweight formatter, not a full SQL parser.
        """

        if not sql.strip():
            return "Error: SQL cannot be empty"

        formatted = _uppercase_keywords(_normalize_spaces(sql))

        newline_keywords = [
            " FROM ",
            " WHERE ",
            " GROUP BY ",
            " ORDER BY ",
            " HAVING ",
            " LIMIT ",
            " OFFSET ",
            " RETURNING ",
            " UNION ",
            " VALUES ",
            " SET ",
        ]

        for keyword in newline_keywords:
            formatted = formatted.replace(keyword, "\n" + keyword.strip() + " ")

        join_pattern = re.compile(
            r"\s((?:LEFT|RIGHT|INNER|OUTER|FULL|CROSS)?\s*JOIN)\s",
            flags=re.IGNORECASE,
        )
        formatted = join_pattern.sub(lambda m: "\n" + m.group(1).strip().upper() + " ", formatted)
        formatted = re.sub(r"\sON\s", "\n  ON ", formatted, flags=re.IGNORECASE)
        formatted = re.sub(r",\s*", ",\n  ", formatted)

        return formatted.strip()
