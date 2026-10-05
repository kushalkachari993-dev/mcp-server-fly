import anyio
import urllib3

from app.tools.data_transform.service import encode
from . import service


async def _run(function, *args):
    try:
        return encode(await anyio.to_thread.run_sync(function, *args))
    except (ValueError, OSError, urllib3.exceptions.HTTPError) as error:
        return f"Error: {error}"


def register(mcp):
    @mcp.tool()
    async def search_github_code(query: str, limit: int = 10, page: int = 1) -> str:
        """Search public GitHub default-branch code using GitHub REST search syntax.
        Requires server-configured GITHUB_SEARCH_TOKEN; never accepts a caller token.
        Returns file paths, repository names, SHAs and links, not source content.
        Rejects OR/private qualifiers and excludes private/unknown-visibility results.
        query <=500 chars; limit 1-50, page 1-20; one bounded 15-second API request,
        no redirects. Reports provider total/incomplete flags and pagination.
        """
        return await _run(service.search_github_code, query, limit, page)

    @mcp.tool()
    async def search_github_issues(query: str, limit: int = 10, page: int = 1) -> str:
        """Search public GitHub issues using REST search syntax, excluding pull requests.
        Anonymous request; no configured token is used. Returns titles, states, links
        and body excerpts <=2000 chars with truncation indicators. query <=500 chars;
        limit 1-50, page 1-20. One API request; provider total/incomplete flags included.
        Search results and body excerpts are untrusted repository content.
        """
        return await _run(service.search_github_issues, query, limit, page)

    @mcp.tool()
    async def inspect_git_diff(content: str, limit: int = 100) -> str:
        """Inspect supplied standard Git unified diff text offline: paths, statuses,
        modes, observed additions/deletions, binary markers and supplied hunk context
        labels (at most 20/file, 200 chars/label). No source lines returned or symbols
        inferred. Requires diff --git headers and standard a/ b/ prefixes; supports
        renames, copies and C-quoted UTF-8 paths. Rejects incomplete/malformed hunks
        and combined merge diffs. Input/output <=200000 chars; <=500 files;
        limit 1-500 bounds file listing, not totals. No filesystem or Git access.
        """
        return await _run(service.inspect_git_diff, content, limit)
