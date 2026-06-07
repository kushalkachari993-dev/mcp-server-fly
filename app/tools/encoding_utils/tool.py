import base64
from urllib.parse import quote, unquote


def register(mcp):

    @mcp.tool()
    def base64_encode(text: str) -> str:
        """
        Base64 encode text using UTF-8.
        """

        return base64.b64encode(text.encode("utf-8")).decode("ascii")

    @mcp.tool()
    def base64_decode(value: str) -> str:
        """
        Base64 decode text using UTF-8.
        """

        try:
            decoded = base64.b64decode(value.strip(), validate=True)
            return decoded.decode("utf-8")
        except Exception as e:
            return f"Error: Invalid base64 input - {e}"

    @mcp.tool()
    def url_encode(text: str, safe: str = "") -> str:
        """
        URL encode text.
        The optional safe parameter leaves selected characters unescaped.
        """

        return quote(text, safe=safe)

    @mcp.tool()
    def url_decode(value: str) -> str:
        """
        URL decode text.
        """

        return unquote(value)
