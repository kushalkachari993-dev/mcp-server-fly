import json

import anyio
import urllib3

from . import service


def register(mcp):

    @mcp.tool()
    async def get_github_file(owner: str, repo: str, path: str, ref: str = "", max_chars: int = 20000) -> str:
        """Read a UTF-8 file from a public GitHub repository at a ref or default branch.
        Returns content, SHA, and truncation flag. File limit 1 MB; output 100-50000
        characters. Public repositories only; no token is used or accepted.
        """
        try:
            if not 100 <= max_chars <= 50000:
                raise ValueError("max_chars must be between 100 and 50000")
            result = await anyio.to_thread.run_sync(service.read_file, owner, repo, path, ref, max_chars)
            return json.dumps(result, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def list_github_directory(owner: str, repo: str, path: str = "", ref: str = "",
                                    limit: int = 100) -> str:
        """List up to 100 entries in a public GitHub repository directory.
        An empty path lists the root. Returns names, paths, types, sizes, SHAs,
        URLs, and a truncation flag. Does not recurse or access private repos.
        """
        try:
            if not 1 <= limit <= 100:
                raise ValueError("limit must be between 1 and 100")
            result = await anyio.to_thread.run_sync(service.list_directory, owner, repo, path, ref, limit)
            return json.dumps(result, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def get_github_issue(owner: str, repo: str, number: int) -> str:
        """Read a public GitHub issue, including status, author, labels, and body.
        Body is limited to 12000 characters. Pull requests use a separate tool.
        """
        try:
            if number < 1:
                raise ValueError("number must be positive")
            result = await anyio.to_thread.run_sync(service.read_issue, owner, repo, number)
            return json.dumps(result, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def get_github_pull_request(owner: str, repo: str, number: int, max_files: int = 20) -> str:
        """Read a public pull request and summarize up to 50 changed file paths.
        Makes one request for PR metadata and one for changed files when needed.
        Body is limited to 12000 characters; file patches are not downloaded.
        """
        try:
            if number < 1 or not 1 <= max_files <= 50:
                raise ValueError("number must be positive and max_files must be 1-50")
            result = await anyio.to_thread.run_sync(service.read_pull_request, owner, repo, number, max_files)
            return json.dumps(result, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def list_github_releases(owner: str, repo: str, limit: int = 5) -> str:
        """List up to 20 published releases of a public GitHub repository.
        Returns tag, name, URL, publish time, prerelease flag, and short notes.
        Does not include tags that are not GitHub releases.
        """
        try:
            if not 1 <= limit <= 20:
                raise ValueError("limit must be between 1 and 20")
            result = await anyio.to_thread.run_sync(service.list_releases, owner, repo, limit)
            return json.dumps(result, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def compare_github_refs(owner: str, repo: str, base: str, head: str,
                                  max_commits: int = 20, max_files: int = 30) -> str:
        """Compare two refs in a public GitHub repository. Returns ahead/behind counts,
        up to 50 commit summaries, and up to 50 changed file paths. No patches or
        private repository access; results indicate when lists are truncated.
        """
        try:
            if not 1 <= max_commits <= 50 or not 1 <= max_files <= 50:
                raise ValueError("max_commits and max_files must be between 1 and 50")
            result = await anyio.to_thread.run_sync(
                service.compare_refs, owner, repo, base, head, max_commits, max_files
            )
            return json.dumps(result, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"
