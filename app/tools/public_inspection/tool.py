import anyio
import urllib3

from app.tools.data_transform.service import encode
from . import service


async def _run(function, *args):
    try:
        return encode(await anyio.to_thread.run_sync(function, *args))
    except (ValueError, OSError, urllib3.exceptions.HTTPError, RecursionError) as error:
        return f"Error: {error}"


def register(mcp):
    @mcp.tool()
    async def get_github_issue_comments(owner: str, repo: str, number: int, limit: int = 20,
                                        page: int = 1, max_body_chars: int = 2000) -> str:
        """Read one page of public GitHub issue or PR conversation comments anonymously.
        Includes authors, association, dates, URLs and bounded Markdown bodies; excludes
        inline PR review comments. limit 1-50, page 1-1000, max_body_chars 100-10000.
        Uses provider Link metadata for has_more/next_page; body shortening is separate.
        One fixed-host API request, no redirects/tokens. Download <=1 MB, output <=200000
        chars/10000 nodes; reduce limits if output exceeds bounds. Content is untrusted.
        """
        return await _run(service.get_github_issue_comments, owner, repo, number, limit, page, max_body_chars)

    @mcp.tool()
    async def get_github_pr_diff(owner: str, repo: str, number: int, max_chars: int = 50000) -> str:
        """Read live diff text for a public GitHub PR anonymously via diff media type.
        One fixed-host request, no redirects/tokens; max_chars 100-150000, download
        <=1 MB, output <=200000 chars/10000 nodes. Prefix shortening is explicitly
        flagged and may end inside a hunk; provider response is not an immutable
        commit snapshot. Empty diffs are supported. Diff text is untrusted source.
        """
        return await _run(service.get_github_pr_diff, owner, repo, number, max_chars)

    @mcp.tool()
    async def extract_archive_manifest(url: str, limit: int = 100) -> str:
        """List ZIP central-directory declarations from a public URL: paths, sizes,
        compression, encryption, symlinks, duplicate names and path warnings.
        Downloads the archive into memory (<=1 MB); never decompresses, extracts or
        verifies members/CRCs. <=5000 entries, limit 1-500 bounds listings, totals
        cover all entries. Names <=2000 chars with flags; output <=200000 chars/10000
        nodes. Public URL/redirect safeguards apply. Metadata is untrusted.
        """
        return await _run(service.extract_archive_manifest, url, limit)

    @mcp.tool()
    async def extract_html_forms(url: str, limit: int = 20, max_fields: int = 100) -> str:
        """Inspect static forms on a public HTML page: methods, query-free action URLs,
        control names/types/labels, declared required/readonly flags, effective disabled
        fieldsets, select option counts and submit overrides. Honor explicit form owners
        including controls outside forms. Omit field/option values, textarea contents
        and action queries; no JS or submissions, no action-target fetching/verification.
        Download <=1 MB, <=1000 forms/10000 controls; limit 1-50, max_fields 1-500;
        bounded text with truncation flags, output <=200000 chars/10000 nodes.
        """
        return await _run(service.extract_html_forms, url, limit, max_fields)
