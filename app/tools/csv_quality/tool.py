import json

import anyio

from . import service


async def _run(function, *arguments):
    try:
        result = await anyio.to_thread.run_sync(function, *arguments)
        output = json.dumps(result, indent=2, allow_nan=False)
        if len(output) > 100000:
            raise ValueError("CSV output exceeds 100000 characters; reduce input/limit/mask")
        return output
    except (ValueError, RecursionError) as error:
        return f"Error: {error}"


def register(mcp):
    @mcp.tool()
    async def profile_csv(csv_text: str, delimiter: str = ",", limit: int = 20) -> str:
        """Profile supplied headered CSV/TSV offline: rows/columns, exact
        duplicate rows, empty/whitespace cells, distinct values and string lengths.
        No cell samples, inferred types, conversions, file/network or execution.
        Each input: 200000 chars, 1000 rows, 100 columns; unique nonempty headers
        up to 200 chars without controls, equal row widths. Blank records skipped.
        Full bounded rows counted; limit 1-50 columns, output 100000 chars.
        """
        return await _run(service.profile, csv_text, delimiter, limit)

    @mcp.tool()
    async def validate_csv_schema(csv_text: str, schema_json: str, required_columns_json: str = "[]",
                                  delimiter: str = ",", limit: int = 20) -> str:
        """Validate supplied CSV rows as string-valued objects against JSON
        Schema; optionally require explicit header names even with zero data rows.
        No coercion/defaults. Known drafts (default 2020-12), local references,
        installed format checks; remote retrieval disabled. Diagnostics omit
        literals/messages. Five-second worker, one active CSV validation/process;
        classifies all bounded rows, collects at most 50 errors. Each text input
        200000 chars; CSV 1000 rows/100 columns/200-char control-free headers;
        JSON 10000 nodes/depth 50. Limit 1-50/list, output 100000 chars. Offline.
        """
        return await _run(service.validate, csv_text, schema_json, required_columns_json, delimiter, limit)

    @mcp.tool()
    async def compare_csv_tables(before: str, after: str, key_columns_json: str,
                                 delimiter: str = ",", limit: int = 20) -> str:
        """Compare supplied CSV tables by explicit exact composite string
        keys present in both headers. Added/removed rows, column changes and changed
        cells; duplicates ambiguous and empty/whitespace keys unmatchable. No key
        inference, trimming/coercion or row-position matching; order reported
        separately. Returned keys/cell values may be sensitive. Full bounded rows
        compared before list limits/1000-char previews. Each input 200000 chars,
        1000 rows, 100 columns, 200-char control-free unique headers. Limit 1-50;
        output 100000 chars, explicit truncation. No file/network/execution.
        """
        return await _run(service.compare, before, after, key_columns_json, delimiter, limit)

    @mcp.tool()
    async def redact_csv_columns(csv_text: str, columns_json: str, delimiter: str = ",", mask: str = "[REDACTED]") -> str:
        """Replace every cell in explicitly selected existing CSV columns.
        Returns JSON with complete rewritten CSV and counts; unknown/duplicate or
        empty selections rejected. Headers/unselected values retained exactly;
        quoting regenerated, record separators CRLF. No automatic PII/secret or
        formula sanitization, complete-anonymization claim or file/network access.
        Inputs 200000 chars; 1000 rows/100 columns, unique control-free headers
        200 chars; mask 0-200 chars without NUL. Output 100000 chars, never partial.
        """
        return await _run(service.redact, csv_text, columns_json, delimiter, mask)
