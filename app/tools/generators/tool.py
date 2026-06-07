import secrets
import string
import uuid


def register(mcp):

    @mcp.tool()
    def generate_uuid(count: int = 1) -> str:
        """
        Generate one or more UUID v4 values.
        """

        if count < 1 or count > 50:
            return "Error: Count must be between 1 and 50"

        return "\n".join(str(uuid.uuid4()) for _ in range(count))

    @mcp.tool()
    def generate_password(
        length: int = 20,
        include_symbols: bool = True,
        include_numbers: bool = True,
    ) -> str:
        """
        Generate a cryptographically strong random password.
        """

        if length < 8 or length > 128:
            return "Error: Length must be between 8 and 128"

        alphabet = string.ascii_letters
        if include_numbers:
            alphabet += string.digits
        if include_symbols:
            alphabet += "!@#$%^&*()-_=+[]{};:,.?"

        return "".join(secrets.choice(alphabet) for _ in range(length))
