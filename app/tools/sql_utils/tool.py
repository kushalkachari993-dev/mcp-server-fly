import re

import anyio

from . import service


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
