import json

from packaging.version import Version
from semver import Version as SemVersion


def register(mcp):

    @mcp.tool()
    def compare_versions(first: str, second: str, scheme: str = "semver") -> str:
        """Compare first against second using strict semver or Python pep440 ordering.
        Returns -1 (older), 0 (equal precedence), or 1 (newer), plus normalized versions.
        SemVer requires major.minor.patch and ignores build metadata in ordering;
        PEP 440 supports epochs, pre/dev/post/local releases. Exact versions only,
        at most 200 characters each. Does not assess compatibility or upgrade safety.
        """
        try:
            if scheme not in {"semver", "pep440"}:
                raise ValueError("scheme must be semver or pep440")
            for value in (first, second):
                if not 1 <= len(value) <= 200 or value != value.strip() or any(ord(char) < 32 for char in value):
                    raise ValueError("Versions must be 1-200 characters without surrounding whitespace or controls")
            parse = SemVersion.parse if scheme == "semver" else Version
            left, right = parse(first), parse(second)
            comparison = (left > right) - (left < right)
            return json.dumps({"scheme": scheme, "first": str(left), "second": str(right),
                               "comparison": comparison,
                               "relation": {-1: "older", 0: "equal", 1: "newer"}[comparison],
                               "notice": "Version ordering only; not an assessment of compatibility or safety."}, indent=2)
        except ValueError as error:
            return f"Error: {error}"
