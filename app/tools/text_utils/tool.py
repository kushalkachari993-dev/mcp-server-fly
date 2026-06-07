import hashlib
import re


_URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")


def register(mcp):

    @mcp.tool()
    def analyze_text(text: str) -> str:
        """
        Count characters, words, lines, sentences, and paragraphs in text.
        """

        words = re.findall(r"\b\w+\b", text)
        sentences = re.findall(r"[^.!?]+[.!?]?", text)
        paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p]

        return (
            f"Characters: {len(text)}\n"
            f"Characters without spaces: {len(text.replace(' ', ''))}\n"
            f"Words: {len(words)}\n"
            f"Lines: {len(text.splitlines())}\n"
            f"Sentences: {len([s for s in sentences if s.strip()])}\n"
            f"Paragraphs: {len(paragraphs)}"
        )

    @mcp.tool()
    def transform_text(text: str, operation: str) -> str:
        """
        Transform text. Operations: upper, lower, title, slug, snake, kebab, reverse.
        """

        operation = operation.strip().lower()
        if operation == "upper":
            return text.upper()
        if operation == "lower":
            return text.lower()
        if operation == "title":
            return text.title()
        if operation == "slug" or operation == "kebab":
            value = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
            return value.strip("-")
        if operation == "snake":
            value = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower())
            return value.strip("_")
        if operation == "reverse":
            return text[::-1]

        return "Error: Unsupported operation"

    @mcp.tool()
    def extract_urls(text: str) -> str:
        """
        Extract HTTP and HTTPS URLs from text.
        """

        urls = _URL_PATTERN.findall(text)
        if not urls:
            return "No URLs found."

        return "\n".join(urls)

    @mcp.tool()
    def hash_text(text: str, algorithm: str = "sha256") -> str:
        """
        Hash text using md5, sha1, sha256, or sha512.
        """

        algorithm = algorithm.strip().lower()
        if algorithm not in {"md5", "sha1", "sha256", "sha512"}:
            return "Error: Algorithm must be md5, sha1, sha256, or sha512"

        digest = hashlib.new(algorithm)
        digest.update(text.encode("utf-8"))
        return digest.hexdigest()
