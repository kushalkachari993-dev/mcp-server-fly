import csv
import io


_MAX_INPUT_CHARS = 200000
_MAX_ROWS = 1000


def _validate_input(value, delimiter):
    if not isinstance(value, str) or len(value) > _MAX_INPUT_CHARS:
        raise ValueError(f"Input must be text of at most {_MAX_INPUT_CHARS} characters")
    if not isinstance(delimiter, str) or len(delimiter) != 1 or delimiter in {'"', "\r", "\n", "\0"}:
        raise ValueError("Delimiter must be one character other than a quote, newline, or NUL")


def read_csv(csv_text, delimiter, *, max_columns=None):
    _validate_input(csv_text, delimiter)
    reader = csv.reader(io.StringIO(csv_text.lstrip("\ufeff"), newline=""), delimiter=delimiter, strict=True)
    headers = next(reader, None)
    if not headers or any(not header.strip() for header in headers):
        raise ValueError("CSV must have a nonempty header for each column")
    if len(headers) != len(set(headers)):
        raise ValueError("CSV headers must be unique")
    if max_columns is not None and len(headers) > max_columns:
        raise ValueError(f"CSV must not exceed {max_columns} columns")
    rows = []
    for row in reader:
        if not row:
            continue
        if len(row) != len(headers):
            raise ValueError(f"CSV row ending on line {reader.line_num} has an incorrect number of cells")
        if len(rows) >= _MAX_ROWS:
            raise ValueError(f"CSV must not exceed {_MAX_ROWS} data rows")
        rows.append(row)
    return headers, rows
