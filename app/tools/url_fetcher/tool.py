from app.tools.webpage.service import request_public


_MAX_CHARS = 6000


def register(mcp):

    @mcp.tool()
    def fetch_url(url: str) -> str:
        """
        Fetch a public HTTP/HTTPS URL and return status, content type, and text.
        Blocks localhost, private, reserved, and link-local network addresses.
        """

        url = url.strip()
        try:
            status, headers, body, final_url = request_public(url, timeout_seconds=10)
            content_type = next((value for key, value in headers.items()
                                 if key.lower() == "content-type"), "unknown")
            decoded = body.decode("utf-8", errors="replace")
            text = decoded[:_MAX_CHARS]
            truncated = len(decoded) > _MAX_CHARS

            return (
                f"Status: {status}\n"
                f"Content-Type: {content_type}\n"
                f"Final URL: {final_url}\n"
                f"Truncated: {truncated}\n\n"
                f"{text}"
            )
        except Exception as e:
            return f"Error: {e}"
