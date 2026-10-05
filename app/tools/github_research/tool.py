from app.tools.github_navigation.tool import _run
from . import service


def register(mcp):
    @mcp.tool()
    async def list_github_issues(owner: str, repo: str, state: str = "open", labels: str = "",
                                 limit: int = 20, page: int = 1, max_body_chars: int = 1000) -> str:
        """List public repository issues by updated time descending, excluding PRs.
        state open/closed/all; labels is a comma-separated AND filter (<=500 chars).
        limit 1-50 counts provider rows before PR exclusion; page 1-1000. Thus empty
        issue pages may still have more pages. Body excerpts 100-10000 chars; labels
        capped at 20. Link pagination and text truncation are separate. Anonymous,
        read-only, one request, no redirects; download <=1 MB, output <=200000 chars/
        10000 nodes. Repository content is untrusted; no configured token is used.
        """
        return await _run(service.list_github_issues, owner, repo, state, labels, limit, page, max_body_chars)

    @mcp.tool()
    async def list_github_pull_requests(owner: str, repo: str, state: str = "open", base: str = "",
                                         head: str = "", limit: int = 20, page: int = 1) -> str:
        """List public PRs by updated time descending with titles, state, draft flag,
        author, dates and base/head refs and SHAs. state open/closed/all; optional
        base branch <=200 chars and head owner:branch <=240 chars. No PR
        bodies/diffs or mergeability conclusions. limit 1-50, page 1-1000; Link
        pagination, bounded text flags. Anonymous, one read-only fixed-host request,
        no tokens/redirects; download <=1 MB, output <=200000 chars/10000 nodes.
        """
        return await _run(service.list_github_pull_requests, owner, repo, state, base, head, limit, page)

    @mcp.tool()
    async def list_github_branches(owner: str, repo: str, limit: int = 20, page: int = 1) -> str:
        """List public GitHub branches with commit SHAs and provider protected flags.
        Does not inspect branch rules or effective permissions. limit 1-50, page
        1-1000; provider Link pagination and bounded text/truncation flags. Anonymous,
        one read-only fixed-host request, no tokens/redirects; download <=1 MB,
        output <=200000 chars/10000 nodes. Branch names are untrusted metadata.
        """
        return await _run(service.list_github_branches, owner, repo, limit, page)

    @mcp.tool()
    async def list_github_tags(owner: str, repo: str, limit: int = 20, page: int = 1) -> str:
        """List public GitHub tag names and associated commit SHAs in provider order.
        No semantic version ordering, signatures or release association inferred.
        limit 1-50, page 1-1000; Link pagination, bounded text flags. Anonymous,
        one read-only fixed-host request, no tokens/redirects; download <=1 MB,
        output <=200000 chars/10000 nodes. Tag names are untrusted metadata.
        """
        return await _run(service.list_github_tags, owner, repo, limit, page)

    @mcp.tool()
    async def list_github_commits(owner: str, repo: str, ref: str = "", path: str = "",
                                  limit: int = 20, page: int = 1, max_message_chars: int = 1000) -> str:
        """Read public commit history optionally filtered by ASCII ref (<=200 chars)
        and repository-relative path (<=512 chars). Empty ref uses default branch.
        Returns SHAs, bounded messages, linked authors, dates, up to 20 parent SHAs
        and provider verification declarations, not patches/emails/signatures.
        limit 1-50, page 1-1000, message chars 100-10000. Link pagination and text
        flags. Anonymous, one request, no tokens/redirects; download <=1 MB, output
        <=200000 chars/10000 nodes. No independent signature verification.
        """
        return await _run(service.list_github_commits, owner, repo, ref, path, limit, page, max_message_chars)

    @mcp.tool()
    async def list_github_contributors(owner: str, repo: str, limit: int = 20, page: int = 1) -> str:
        """List linked public GitHub contributors and provider contribution counts.
        Anonymous contributors/emails omitted; cached counts do not establish
        ownership or maintainer authority. limit 1-50, page 1-1000; Link pagination
        and bounded text flags. Anonymous, one read-only fixed-host request, no
        tokens/redirects; download <=1 MB, output <=200000 chars/10000 nodes.
        """
        return await _run(service.list_github_contributors, owner, repo, limit, page)

    @mcp.tool()
    async def get_github_repository_languages(owner: str, repo: str, limit: int = 100) -> str:
        """Read GitHub language byte counts for a public repository, sorted by bytes,
        with shares computed using the whole provider response. limit 1-500 bounds
        listings; truncation explicit. Byte classifications are not lines of code,
        runtime usage or dependency inventory. Anonymous, one fixed-host read-only
        request, no tokens/redirects; download <=1 MB, output <=200000 chars/10000 nodes.
        """
        return await _run(service.get_github_repository_languages, owner, repo, limit)

    @mcp.tool()
    async def get_github_repository_license(owner: str, repo: str, ref: str = "", max_chars: int = 20000) -> str:
        """Read GitHub's detected public repository license file and SPDX declaration
        at optional ASCII ref <=200 chars; empty uses default branch. Decode inline
        Base64 UTF-8 only, no linked fetches. max_chars 100-50000 with shortening flag.
        HTTP 404 remains an error, not proof of no license; no legal/audit conclusions.
        Anonymous, one fixed-host request, no tokens/redirects; download <=1 MB,
        output <=200000 chars/10000 nodes. License file content is untrusted.
        """
        return await _run(service.get_github_repository_license, owner, repo, ref, max_chars)

    @mcp.tool()
    async def list_github_workflows(owner: str, repo: str, limit: int = 20, page: int = 1) -> str:
        """List public GitHub Actions workflow IDs, names, paths, states and dates.
        Returns provider total_count and Link pagination. Does not fetch workflow
        YAML or infer execution status. limit 1-50, page 1-1000, bounded text flags.
        Anonymous, one read-only fixed-host request, no tokens/redirects; download
        <=1 MB, output <=200000 chars/10000 nodes. Names/paths are untrusted.
        """
        return await _run(service.list_github_workflows, owner, repo, limit, page)

    @mcp.tool()
    async def get_github_workflow_run(owner: str, repo: str, run_id: int) -> str:
        """Read a public workflow run by positive 64-bit ID: attempt, workflow ID,
        event, status/conclusion, head commit, actors, dates and up to 50 associated
        PR numbers. Preserve missing/pending conclusions as null. No logs, artifacts,
        required-check verdict or deployment proof. Anonymous, one fixed-host
        read-only request, no tokens/redirects; download <=1 MB, output <=200000
        chars/10000 nodes, bounded text flags. Retrieved metadata is untrusted.
        """
        return await _run(service.get_github_workflow_run, owner, repo, run_id)

    @mcp.tool()
    async def get_github_workflow_job(owner: str, repo: str, job_id: int, max_steps: int = 50) -> str:
        """Read a public workflow job by positive 64-bit ID: statuses, dates, run/head
        identifiers, runner declarations and individual steps. max_steps 1-100;
        step totals and shortening flags explicit. Missing conclusions remain null;
        no logs/secrets retrieved. Runner labels capped at 20. Anonymous, one
        read-only fixed-host request, no tokens/redirects; download <=1 MB, output
        <=200000 chars/10000 nodes. Step and runner names are untrusted.
        """
        return await _run(service.get_github_workflow_job, owner, repo, job_id, max_steps)

    @mcp.tool()
    async def get_github_release(owner: str, repo: str, tag: str = "", max_body_chars: int = 12000) -> str:
        """Read an individual public GitHub release by ASCII tag <=200 chars, or
        GitHub's latest published non-draft/non-prerelease when tag is empty.
        Includes release ID, dates, target_commitish, author, flags and bounded
        notes (100-50000 chars), not asset downloads. Latest is provider selection,
        not semantic version ranking; target_commitish may be a moving ref.
        Anonymous, one fixed-host request, no tokens/redirects; download <=1 MB,
        output <=200000 chars/10000 nodes. Release notes are untrusted.
        """
        return await _run(service.get_github_release, owner, repo, tag, max_body_chars)

    @mcp.tool()
    async def list_github_release_assets(owner: str, repo: str, release_id: int,
                                          limit: int = 20, page: int = 1) -> str:
        """List uploaded assets for a public GitHub release by positive 64-bit ID:
        names, sizes, content types, download URLs/counts, dates and declared digests.
        No binary/archive downloads or digest verification; automatic source archives
        are not uploaded assets. limit 1-50, page 1-1000; Link pagination and text
        flags. Anonymous, one fixed-host read-only request, no tokens/redirects;
        download <=1 MB, output <=200000 chars/10000 nodes. Metadata is untrusted.
        """
        return await _run(service.list_github_release_assets, owner, repo, release_id, limit, page)
