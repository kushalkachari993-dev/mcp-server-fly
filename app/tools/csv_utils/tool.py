import csv
import io
import json
import math


_MAX_INPUT_CHARS = 200000
_MAX_ROWS = 1000


def _validate_input(value: str, delimiter: str) -> None:
    if len(value) > _MAX_INPUT_CHARS:
        raise ValueError(f"Input must not exceed {_MAX_INPUT_CHARS} characters")
    if len(delimiter) != 1 or delimiter in {'"', "\r", "\n", "\0"}:
        raise ValueError("Delimiter must be one character other than a quote, newline, or NUL")


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
            _validate_input(csv_text, delimiter)
            reader = csv.reader(
                io.StringIO(csv_text.lstrip("\ufeff"), newline=""),
                delimiter=delimiter,
                strict=True,
            )
            headers = next(reader, None)
            if not headers or any(not header.strip() for header in headers):
                raise ValueError("CSV must have a nonempty header for each column")
            if len(headers) != len(set(headers)):
                raise ValueError("CSV headers must be unique")

            rows = []
            for row in reader:
                if not row:
                    continue
                if len(row) != len(headers):
                    raise ValueError(f"CSV row ending on line {reader.line_num} has an incorrect number of cells")
                if len(rows) >= _MAX_ROWS:
                    raise ValueError(f"CSV must not exceed {_MAX_ROWS} data rows")
                rows.append(dict(zip(headers, row)))
            return json.dumps(rows, indent=2)
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
