import base64
import json


def _decode_base64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def register(mcp):

    @mcp.tool()
    def decode_jwt(token: str) -> str:
        """
        Decode a JWT header and payload without verifying the signature.
        Useful for inspection only; this does not validate authenticity.
        """

        parts = token.strip().split(".")
        if len(parts) != 3:
            return "Error: JWT must have three dot-separated parts"

        try:
            header = json.loads(_decode_base64url(parts[0]))
            payload = json.loads(_decode_base64url(parts[1]))

            return (
                "Signature verified: false\n"
                "Header:\n"
                f"{json.dumps(header, indent=2)}\n\n"
                "Payload:\n"
                f"{json.dumps(payload, indent=2)}"
            )
        except Exception as e:
            return f"Error: Could not decode JWT - {e}"
