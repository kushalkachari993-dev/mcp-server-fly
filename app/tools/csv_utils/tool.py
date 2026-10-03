import csv
import io
import json
import math

from .service import _MAX_ROWS, _validate_input, read_csv


def _reject_constant(value: str):
    raise ValueError(f"Invalid JSON number: {value}")


def _parse_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON number is outside the supported range")
    return number


def register(mcp):

    @mcp.tool()
    def csv_to_json(csv_text: str, delimiter: str = ",") -> str:
        """Convert CSV with a header row to a JSON array of objects.
        Preserves cell values as strings, including leading zeros and quoted newlines.
        Requires unique, nonempty headers and matching row widths. Maximum 1000 rows.
        Use delimiter='\\t' for tab-separated data.
        """
        try:
            headers, rows = read_csv(csv_text, delimiter)
            return json.dumps([dict(zip(headers, row)) for row in rows], indent=2)
        except (ValueError, csv.Error) as error:
            return f"Error: {error}"

    @mcp.tool()
    def json_to_csv(value: str, delimiter: str = ",") -> str:
        """Convert a JSON array of flat objects to CSV with a header row.
        Columns are the union of keys in first-seen order. Missing or null values
        become empty cells; booleans become true/false. Nested values are rejected.
        Maximum 1000 rows. An empty array returns an empty string.
        """
        try:
            _validate_input(value, delimiter)
            rows = json.loads(value, parse_constant=_reject_constant, parse_float=_parse_float)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("JSON must be an array of objects")
            if len(rows) > _MAX_ROWS:
                raise ValueError(f"JSON must not exceed {_MAX_ROWS} rows")
            if not rows:
                return ""
            headers = list(dict.fromkeys(key for row in rows for key in row))
            if not headers or any(not header.strip() for header in headers):
                raise ValueError("Objects must have nonempty column names")
            if any(isinstance(cell, (dict, list)) for row in rows for cell in row.values()):
                raise ValueError("Nested objects or arrays cannot be converted to CSV")

            output = io.StringIO(newline="")
            writer = csv.writer(output, delimiter=delimiter, lineterminator="\n")
            writer.writerow(headers)
            for row in rows:
                cells = []
                for header in headers:
                    cell = row.get(header)
                    if cell is None:
                        cell = ""
                    elif isinstance(cell, bool):
                        cell = "true" if cell else "false"
                    cells.append(cell)
                writer.writerow(cells)
            return output.getvalue()
        except (ValueError, csv.Error, RecursionError) as error:
            return f"Error: {error}"
