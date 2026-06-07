import re


_MAX_TEXT_CHARS = 20000
_MAX_MATCHES = 100


def register(mcp):

    @mcp.tool()
    def test_regex(pattern: str, text: str, flags: str = "") -> str:
        """
        Test a regular expression against text.
        flags may include i for ignorecase, m for multiline, s for dotall.
        """

        if len(text) > _MAX_TEXT_CHARS:
            return f"Error: Text is too large. Maximum is {_MAX_TEXT_CHARS} characters"

        flag_value = 0
        flags = flags.lower()
        if "i" in flags:
            flag_value |= re.IGNORECASE
        if "m" in flags:
            flag_value |= re.MULTILINE
        if "s" in flags:
            flag_value |= re.DOTALL

        try:
            compiled = re.compile(pattern, flag_value)
            matches = []

            for index, match in enumerate(compiled.finditer(text), start=1):
                if index > _MAX_MATCHES:
                    break

                matches.append(
                    {
                        "match": match.group(0),
                        "start": match.start(),
                        "end": match.end(),
                        "groups": match.groups(),
                        "named_groups": match.groupdict(),
                    }
                )

            if not matches:
                return "No matches found."

            lines = [f"Matches: {len(matches)}"]
            for index, match in enumerate(matches, start=1):
                lines.append(
                    f"{index}. [{match['start']}, {match['end']}): {match['match']}"
                )
                if match["groups"]:
                    lines.append(f"   Groups: {match['groups']}")
                if match["named_groups"]:
                    lines.append(f"   Named groups: {match['named_groups']}")

            return "\n".join(lines)
        except re.error as e:
            return f"Error: Invalid regex - {e}"
