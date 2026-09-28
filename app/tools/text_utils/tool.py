import difflib
import hashlib
import json
import re

import anyio


_URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")


def _diff(before, after, context_lines, max_chars):
    if max(len(before), len(after)) > 100000:
        raise ValueError("Each input must not exceed 100000 characters")
    old_lines = before.splitlines(keepends=True)
    new_lines = after.splitlines(keepends=True)
    if max(len(old_lines), len(new_lines)) > 1000:
        raise ValueError("Each input must not exceed 1000 lines")
    chunks = []
    size = 0
    truncated = False
    for line in difflib.unified_diff(old_lines, new_lines, fromfile="before", tofile="after", n=context_lines):
        if not line.endswith(("\n", "\r")):
            line += "\n\\ No newline at end of file\n"
        remaining = max_chars - size
        if len(line) > remaining:
            chunks.append(line[:remaining])
            truncated = True
            break
        chunks.append(line)
        size += len(line)
    return {"equal": before == after, "diff": "".join(chunks), "truncated": truncated}


def register(mcp):

    @mcp.tool()
    async def diff_text(before: str, after: str, context_lines: int = 3, max_chars: int = 20000) -> str:
        """Compare text and return JSON with equal, unified diff, and truncated.
        Preserves line endings and marks missing final newlines. Accepts at most
        100000 characters and 1000 lines per input, 0-10 context lines, and
        100-50000 output diff characters. Does not read or modify files.
        """
        try:
            if not 0 <= context_lines <= 10 or not 100 <= max_chars <= 50000:
                raise ValueError("context_lines must be 0-10 and max_chars must be 100-50000")
            result = await anyio.to_thread.run_sync(_diff, before, after, context_lines, max_chars)
            return json.dumps(result, indent=2)
        except ValueError as error:
            return f"Error: {error}"

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
