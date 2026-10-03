MCPSever
========

A reusable MCP server intended for deployment on Fly.io. It exposes utility
tools that can be connected to from other projects or production AI clients.

Available tools
---------------

The server registers 76 tools.

- `get_weather(location)` - current weather for a city via OpenWeather.
- `tavily_search(query)` - web search via Tavily.
- `calculate(expression)` - safe math evaluation.
- `current_time(timezone_name)` - current time in an IANA timezone.
- `convert_time(datetime_text, from_timezone, to_timezone)` - timezone conversion.
- `generate_uuid(count)` - UUID v4 generation.
- `generate_password(length, include_symbols, include_numbers)` - strong password generation.
- `analyze_text(text)` - character, word, line, sentence, and paragraph counts.
- `transform_text(text, operation)` - upper, lower, title, slug, snake, kebab, reverse.
- `extract_urls(text)` - URL extraction.
- `hash_text(text, algorithm)` - md5, sha1, sha256, or sha512 hash.
- `fetch_url(url)` - fetch a public HTTP/HTTPS URL with local/private hosts blocked.
- `validate_json(value)` - validate JSON and report parse errors.
- `format_json(value, indent, sort_keys)` - pretty-print or minify JSON.
- `base64_encode(text)` - Base64 encode UTF-8 text.
- `base64_decode(value)` - Base64 decode UTF-8 text.
- `url_encode(text, safe)` - URL encode text.
- `url_decode(value)` - URL decode text.
- `decode_jwt(token)` - inspect JWT header and payload without signature verification.
- `test_regex(pattern, text, flags)` - test regular expressions and list matches.
- `format_sql(sql)` - lightweight SQL formatting.
- `http_request(url, method, headers_json, body, timeout_seconds)` - make public HTTP requests with private/local hosts blocked.
- `csv_to_json(csv_text, delimiter)` - convert CSV/TSV with headers to JSON objects.
- `json_to_csv(value, delimiter)` - convert flat JSON objects to CSV/TSV.
- `query_json(value, pointer)` - extract a JSON value using JSON Pointer syntax.
- `compare_json(before, after)` - report added, removed, and changed JSON values.
- `timestamp_to_datetime(timestamp, timezone_name, unit)` - convert Unix seconds/milliseconds to an ISO datetime.
- `datetime_to_timestamp(datetime_text, unit)` - convert an ISO datetime to Unix seconds/milliseconds.
- `get_webpage_text(url, max_chars)` - extract readable article/main text from a public webpage.
- `validate_json_schema(value, schema)` - validate JSON fields and types against a JSON Schema.
- `yaml_to_json(value)` - safely convert one YAML document to JSON.
- `json_to_yaml(value)` - convert JSON to YAML while preserving object key order.
- `cron_next_runs(expression, timezone_name, count, from_datetime)` - preview upcoming cron execution times.
- `read_rss_feed(url, limit)` - read news, posts, or releases from a public RSS/Atom feed.
- `extract_webpage_links(url, same_domain_only, limit)` - extract unique webpage links and labels.
- `extract_html_tables(url, max_tables, max_rows)` - convert webpage tables to structured JSON.
- `summarize_numbers(values)` - calculate descriptive statistics for a numeric array.
- `diff_text(before, after, context_lines, max_chars)` - compare text using a unified diff.
- `convert_units(value, from_unit, to_unit)` - convert compatible physical units with Pint.
- `extract_pdf_text(url, start_page, max_pages, max_chars)` - read text from selected pages of a public PDF.
- `get_github_file(owner, repo, path, ref, max_chars)` - read a public repository file at a ref.
- `get_github_issue(owner, repo, number)` - read a public issue and status.
- `get_github_pull_request(owner, repo, number, max_files)` - read a public PR and changed-file summary.
- `list_github_releases(owner, repo, limit)` - list published releases of a public repository.
- `inspect_openapi(url, max_operations)` - list endpoints and declared auth in a public OpenAPI description.
- `compare_github_refs(owner, repo, base, head, max_commits, max_files)` - compare public commits and changed files.
- `compare_openapi_specs(before_url, after_url, max_changes)` - compare endpoints and declared auth schemes.
- `inspect_tls_certificate(domain)` - inspect a public HTTPS certificate's validity and names.
- `lookup_dns_records(domain, record_type, limit)` - query public A, AAAA, MX, or TXT records.
- `list_github_directory(owner, repo, path, ref, limit)` - browse one public repository directory.
- `toml_to_json(value)` - parse TOML configuration into JSON.
- `extract_json_ld(url, max_items, max_chars)` - read embedded structured data from public HTML.
- `inspect_robots_txt(site_url, max_rules)` - summarize a site's robots.txt rules and Sitemap lines.
- `read_sitemap(url, limit)` - list URLs and dates from an XML sitemap or index.
- `inspect_page_metadata(url)` - read canonical, description, Open Graph, and Twitter metadata.
- `get_pypi_package(name)` - summarize a public PyPI project's latest metadata.
- `get_npm_package(name)` - summarize a public npm package's latest-tag metadata.
- `check_package_vulnerabilities(ecosystem, name, version, limit)` - look up known OSV advisories for one package version.
- `check_dependencies_batch(packages_json, limit)` - check up to 50 exact package versions against OSV in one request.
- `list_github_workflow_runs(owner, repo, branch, limit)` - read recent public GitHub Actions run statuses.
- `query_json_advanced(value, expression)` - filter, sort, and reshape JSON using JMESPath.
- `list_github_workflow_jobs(owner, repo, run_id, limit, max_steps)` - read public workflow job and step statuses.
- `inspect_dependency_manifest(content, format, limit)` - inspect declared npm or Python dependencies offline.
- `inspect_lockfile(content, format, limit)` - inspect resolved versions in package-lock.json v2/v3 or pylock.toml offline.
- `analyze_sql(sql, dialect)` - report statement types and syntactic references without executing SQL.
- `compare_versions(first, second, scheme)` - compare exact SemVer or Python PEP 440 versions.
- `inspect_http_security_headers(url)` - summarize common security-related response headers on a public URL.
- `get_github_commit(owner, repo, ref, max_files)` - read public commit metadata and changed-file summaries.
- `compare_lockfiles(before, after, format, limit)` - compare resolved package versions in npm or Python lockfiles.
- `get_vulnerability_details(advisory_id, max_affected, max_chars)` - read OSV affected ranges, fix events, and references.
- `apply_json_patch(value, patch)` - apply JSON Patch operations to supplied JSON offline.
- `analyze_jsonl_logs(content, limit, level_field, message_field, timestamp_field)` - summarize supplied structured logs offline.
- `check_http_endpoints(endpoints_json)` - check up to five public endpoints with individual status matches, timing, and errors.
- `get_github_commit_checks(owner, repo, ref, limit)` - read public CI check runs and legacy statuses for one resolved commit SHA.
- `inspect_dockerfile(content)` - summarize supplied Dockerfile stages and declared runtime settings without building.
- `inspect_http_cache(url)` - separate browser/shared-cache response directives and report conflicting or malformed settings.

Data utility examples
---------------------

```text
csv_to_json(csv_text="name,city\nAda,London\n")
query_json(value='{"users":[{"name":"Ada"}]}', pointer="/users/0/name")
compare_json(before='{"count":1}', after='{"count":2}')
timestamp_to_datetime(timestamp=0, timezone_name="UTC")
datetime_to_timestamp(datetime_text="1970-01-01T00:00:00Z")
```

CSV conversion preserves strings instead of guessing data types. It accepts at
most 1,000 data rows and 200,000 input characters. JSON lookup and comparison
also limit each input to 200,000 characters. Comparison reports at most 100
differences; its `truncated` field indicates when more differences were found.

Research and configuration examples
-----------------------------------

```text
get_webpage_text(url="https://example.com", max_chars=2000)
validate_json_schema(value='{"count":2}', schema='{"type":"object","required":["count"]}')
yaml_to_json(value="name: Ada\nenabled: true\n")
json_to_yaml(value='{"name":"Ada","enabled":true}')
cron_next_runs(expression="*/15 * * * *", timezone_name="Asia/Kolkata", count=3)
```

Webpage extraction does not execute JavaScript. It accepts HTTP/HTTPS on ports
80/443, blocks non-public destinations including redirects, verifies TLS using
the original hostname, and caps downloads at 1 MB and returned text at 50,000
characters. It returns JSON with `url`, `title`, `text`, and `truncated` fields.

Schema validation defaults to draft 2020-12 and returns `valid`, `errors`, and
`truncated`. Local `$ref` definitions work; remote references are not downloaded.
Installed format checks are enabled, with unknown formats left unchecked. A
separate worker enforces a three-second limit, and at most 50 errors are returned.

YAML conversion accepts one document and preserves dates as strings. It uses
YAML 1.1 boolean rules, rejects unsafe tags and duplicate/non-string mapping
keys, and limits alias expansion and nesting. Input/output limits are 200,000
characters, 10,000 nodes, and 100 nested levels.

Cron previews use five fields: minute, hour, day-of-month, month, day-of-week.
The tool returns 1-20 upcoming runs strictly after the supplied start time (or
now), using the selected IANA timezone. It previews schedules only; it does not
create jobs. Each next-run search is limited to five years.

Research and analysis examples
------------------------------

```text
read_rss_feed(url="https://www.djangoproject.com/rss/weblog/", limit=5)
extract_webpage_links(url="https://example.com", same_domain_only=true)
extract_html_tables(url="https://docs.python.org/3.12/library/statistics.html", max_tables=1)
summarize_numbers(values=[1, 2, 3, 4])
diff_text(before="old\n", after="new\n")
convert_units(value=36, from_unit="kilometer/hour", to_unit="meter/second")
convert_units(value=0, from_unit="degC", to_unit="degF")
```

The three web tools reuse the same public-only, redirect-checked, 1 MB fetcher.
They do not execute JavaScript or follow extracted links. Link extraction
resolves relative URLs and HTML base tags, removes fragments, and deduplicates
URLs. `same_domain_only` means the final page's exact hostname (not subdomains).
It returns at most 500 links, with labels capped at 1,000 characters.

Feed reading supports RSS and Atom and returns entries in source order, not
necessarily newest first. It accepts 1-50 entries and returns title, URL,
publication string, and plain-text summary. Titles, dates, and summaries are
capped at 1,000, 200, and 2,000 characters. `truncated` indicates more entries
exist; `parse_warning` indicates a recoverable parser problem. Feeds are fetched
on demand, not monitored in the background. No additional API keys are needed.

Table extraction returns `caption`, `headers`, and `rows` (arrays of strings)
for each table. Positive rowspan/colspan repeat text; missing cells are padded.
Only an all-th first row becomes headers; later header rows remain data.
Nested tables are ignored. Limits are 20 tables, 1,000 data rows per table, 50
columns, 2,000 characters per cell, and 200,000 output characters. Truncation
flags mark table/row/cell limits; oversized combined output returns an error.

Number summaries accept 1-10,000 finite numbers, rejecting strings and booleans.
The result includes both population and sample standard deviation; the sample
value is null for one observation. Results outside the numeric range return an
error. Diffs accept 100,000 characters and 1,000 lines per input, preserve line
endings, and mark missing final newlines. Context is 0-10 lines and returned diff
text is capped at 100-50,000 characters, with a `truncated` flag.

Unit conversion supports physical units and compound units such as
`kilometer/hour` and `meter**2`, including offset temperatures `degC`/`degF`.
Use `delta_degC`/`delta_degF` for temperature differences. Unit names are
case-sensitive and accept `*`, `/`, and integer powers from -12 to 12, with
at most 100 characters. Incompatible or unknown units return an error. Currency
conversion, custom definitions, and conversion contexts are not supported.

Document and developer examples
-------------------------------

```text
extract_pdf_text(url="https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf", max_pages=1)
get_github_file(owner="kushalkachari993-dev", repo="mcp-server-fly", path="README.md")
get_github_issue(owner="pallets", repo="flask", number=6165)
get_github_pull_request(owner="pallets", repo="flask", number=6162, max_files=5)
list_github_releases(owner="pallets", repo="flask", limit=3)
inspect_openapi(url="https://raw.githubusercontent.com/OAI/OpenAPI-Specification/main/_archive_/schemas/v3.0/pass/petstore.yaml")
compare_github_refs(owner="kushalkachari993-dev", repo="mcp-server-fly", base="v1", head="master")
compare_openapi_specs(before_url="https://example.com/old.json", after_url="https://example.com/new.json")
inspect_tls_certificate(domain="example.com")
lookup_dns_records(domain="example.com", record_type="MX")
list_github_directory(owner="kushalkachari993-dev", repo="mcp-server-fly", path="app/tools")
toml_to_json(value='[server]\nport = 8000\n')
extract_json_ld(url="https://example.com", max_items=5)
inspect_robots_txt(site_url="https://example.com")
read_sitemap(url="https://example.com/sitemap.xml", limit=50)
inspect_page_metadata(url="https://example.com")
get_pypi_package(name="sampleproject")
```

PDF extraction accepts public PDF URLs up to 1 MB. It reads 1-10 pages per
call, returns at most 50,000 text characters, and runs in an isolated worker
with a 10-second time limit and memory/CPU limits on Linux. Encrypted PDFs and
files over 1,000 pages are rejected. `scanned_possible` signals that selected
pages yielded no text; this tool does not perform OCR. Only one PDF can be
parsed at a time to protect the 256 MB Fly.io machine.

GitHub tools read public repositories only and never accept a GitHub token.
File content is limited to 1 MB of UTF-8 and a selectable 100-50,000-character
response. Issues/PRs include at most 12,000 body characters. PRs list at most
50 changed file paths without patches; releases return at most 20 items and
4,000 characters of notes each. A `truncated` flag marks partial results.
The unauthenticated GitHub API has a shared per-IP rate limit, so callers
should use these tools sparingly and retry only after a rate limit resets.

OpenAPI inspection accepts a public JSON or YAML OpenAPI 3.x URL. It lists
title, version, servers, and up to 200 operations with methods, paths, tags,
and declared security scheme names. It does not resolve external or local
`$ref` targets, make API calls, or validate the entire specification. The
download limit is 1 MB and parsed input is limited to 200,000 characters.
These new URL-based tools reuse the public-only redirect-checked fetcher.

GitHub comparisons return up to 50 commits and 50 changed files, with separate
truncation flags; they do not return patches. OpenAPI comparison handles at most
500 operations in each spec and reports endpoint additions/removals and changes
to declared security scheme names. It does not compare schemas or OAuth scopes
and rejects path/operation `$ref` entries it cannot resolve.

Commit inspection reads one public commit by branch, tag, or SHA and returns
message, author/committer metadata, verification status, aggregate stats, and
up to 50 changed-file summaries. It does not return patches. HTTP security
header inspection uses HEAD with a GET fallback, checks common browser security
headers, and reports missing-header notes without assigning a security score.

TLS inspection verifies the certificate and hostname on port 443, reporting
expiry and up to 20 DNS names. Invalid certificates return an error. DNS lookup
uses Cloudflare DNS over HTTPS, so queried domains are sent to Cloudflare;
local/private DNS is not queried. It returns up to 50 matching records, including
CNAMEs in a chain. TLS inspection blocks non-public destinations; DNS lookup
validates domain syntax and never queries the machine's local DNS records.

`http_request` and `fetch_url` now use the same public-only transport as the
webpage tools. Each redirect is validated and connections are pinned to the
validated IP, preventing DNS rebinding between validation and connection.
Requests are limited to ports 80/443, three redirects, and 1 MB responses;
credentials are removed when a redirect changes the host or scheme.

Directory browsing lists one public GitHub directory at a time, including
names, paths, types, sizes, and SHAs. It returns at most 100 entries and marks
truncated results; it does not recurse. The GitHub response must fit the shared
1 MB fetch limit. TOML parsing accepts up to 200,000 characters and converts
dates/times to ISO strings. Non-finite numbers and oversized output are rejected.
JSON-LD extraction reads up to 20 embedded objects or arrays from a public HTML
page, reports malformed scripts, and caps returned text at 50,000 characters.
It does not run page JavaScript or retrieve external JSON-LD contexts.

Robots inspection reads only the HTTPS site's root `/robots.txt`. It lists up
to 200 allow/disallow rules and 20 Sitemap lines without deciding whether a
given URL is crawlable. A 4xx response is reported as missing; 5xx is an error.
Sitemap reading accepts UTF-8 XML `urlset` and `sitemapindex` documents, returns
at most 500 URLs with optional `lastmod` values, and never fetches child
sitemaps. DTDs, custom entity declarations, compressed sitemaps, and oversized
XML are rejected.
Both tools use the public-only transport and 1 MB download limit.

Page metadata inspection returns title, description, canonical URL, robots meta,
and bounded Open Graph/Twitter tags from HTML without executing scripts. PyPI
lookup returns the latest version, Python requirement, up to 30 dependencies,
license, and up to 10 project links. It does not return release history, and
PyPI responses above the shared 1 MB download limit return an error. These
tools require no additional API keys.

Dependency and workflow examples
--------------------------------

```text
get_npm_package(name="@types/node")
check_package_vulnerabilities(ecosystem="npm", name="lodash", version="4.17.20", limit=5)
list_github_workflow_runs(owner="pallets", repo="flask", limit=5)
query_json_advanced(value='{"users":[{"name":"Ada","active":true}]}', expression="users[?active].name")
```

npm lookup fetches only the `latest` tag's version metadata, not the full release
history. It accepts lowercase names, including `@scope/name`, and returns Node
requirements, license, repository, deprecation text, and at most 30 dependencies
and 30 peer dependencies. It never downloads packages or executes install scripts.
Descriptions, links, and dependency requirements are bounded; `truncated` also
marks shortened fields. It does not audit dependencies or resolve version ranges.

Vulnerability lookup sends the supplied ecosystem, package name, and exact version
to OSV. Supported ecosystem names are case-sensitive: `PyPI`, `npm`, `Go`, `Maven`,
`crates.io`, `NuGet`, `RubyGems`, and `Packagist`. It returns 1-20 advisory summaries
when available (default limit 10), including aliases, raw severity scores/vectors,
withdrawal dates when present, and advisory links. An empty result is not proof of
safety. It does not scan dependencies, inspect code, or suggest a guaranteed-safe
upgrade. Only the first API page is queried; `truncated` marks additional pages,
omitted advisories, or shortened fields. Responses exceeding 1 MB return an error,
not an empty vulnerability list.

Workflow run listing makes one public GitHub API request and returns up to 20
recent runs (default 10), optionally filtered by exact branch name. Each summary
includes status, conclusion, branch, commit SHA, dates, and run URL. A pending
run can have a null conclusion. The tool does not fetch logs, rerun jobs, cancel
workflows, or access private repositories. API errors, including rate limits,
are returned as errors rather than empty results. All three API tools use the
shared public-only, HTTPS host-pinned transport and 1 MB response limit. No new
API keys are required.

Advanced JSON queries use JMESPath, separate from `query_json`'s JSON Pointer
lookup. Input is limited to 200,000 characters and expressions to 1,000. Input
and result trees allow at most 10,000 nodes and 50 nested levels; the parsed
expression allows 500 nodes and 50 levels. Results are valid JSON up to 100,000
characters, including scalar values and null for missing fields. Oversized
results and non-finite numbers return errors instead of partial JSON. One worker
per server process enforces a three-second wall-time limit, plus a 128 MB address
space cap and two-second CPU cap on Linux. Queries cannot execute Python/shell
code or access files or networks. JMESPath is the only new dependency in this batch.

API and query documentation: [npm registry](https://github.com/npm/registry/blob/main/docs/REGISTRY-API.md),
[OSV query API](https://google.github.io/osv.dev/post-v1-query/),
[GitHub workflow runs](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-repository),
and [JMESPath examples](https://jmespath.org/examples.html).

Build diagnostics and dependency examples
----------------------------------------

```text
list_github_workflow_jobs(owner="pallets", repo="flask", run_id=123456789, limit=5, max_steps=20)
inspect_dependency_manifest(content='{"dependencies":{"demo":"^1.0.0"}}', format="package.json")
inspect_dependency_manifest(content='[project]\ndependencies = ["requests>=2"]\n', format="pyproject.toml")
analyze_sql(sql="SELECT u.id FROM users u JOIN orders o ON u.id = o.user_id", dialect="postgres")
compare_versions(first="1.9.0", second="1.10.0", scheme="semver")
compare_versions(first="1.0rc1", second="1.0", scheme="pep440")
```

Replace the example run ID with one returned by `list_github_workflow_runs`.
Job listing fetches the latest execution's jobs in one public GitHub request,
returning 1-20 jobs (default 10) and 1-50 steps per job (default 30), when present.
Each job and step includes status, conclusion, and dates. Pending conclusions
may be null. The result includes total job count, per-job step counts, and
truncation flags. Logs, artifacts, reruns, cancellations, and private repositories
are not accessed. The 1 MB public-only fetch limit and GitHub rate limits apply;
output above 100,000 characters returns an error requesting smaller limits.

Manifest inspection accepts supplied `package.json` or `pyproject.toml` text,
not paths or URLs. npm sections include `dependencies`, `devDependencies`,
`optionalDependencies`, and `peerDependencies`; declarations overridden by an
optional dependency are marked. Python sections include `project.dependencies`,
`project.optional-dependencies`, `build-system.requires`, and `dependency-groups`.
Python requirements are parsed with `packaging`, preserving extras, specifiers,
environment markers, and direct URLs. Markers are not evaluated and group includes
are listed without expansion or cycle checking. Dynamic dependencies, tool-specific
declarations (including Poetry), workspaces, and overrides receive scope warnings
where present. This is not a full manifest validator or dependency resolver;
declared constraints are not installed versions. No files/URLs are opened and no
packages or scripts are installed or executed.

Lockfile inspection accepts supplied `package-lock.json` v2/v3 or `pylock.toml`
text and lists resolved package versions offline. It does not support npm v1
lockfiles, unstable `uv.lock` parsing, installation, resolution, or local file
access. It accepts up to 2 MB and returns at most 500 package records. The
batch dependency audit accepts up to 50 exact package identities and sends one
OSV querybatch request; advisory summaries are bounded and no matches do not
prove that a package is safe.

Manifests allow 200,000 input characters, 10,000 nodes, 50 nesting levels, and
1,000 dependency declarations. Requirement strings are capped at 1,000 characters.
The tool returns at most 200 declarations (default 100) and 200 group includes,
with total declaration count and truncation flag. Duplicate JSON keys and invalid
dependency shapes are rejected. Output over 100,000 characters returns an error;
lower `limit` for a smaller summary. Full requirement strings are never shortened.

SQL analysis uses SQLGlot in an isolated worker. Supported dialect names are
`postgres` (default), `mysql`, `sqlite`, `bigquery`, `snowflake`, `tsql`, `duckdb`,
`redshift`, and `trino`. Supported statement families are SELECT/set operations,
INSERT, UPDATE, DELETE, MERGE, CREATE, ALTER, DROP, and TRUNCATE. Parser fallback
commands and other statement types return errors. Table references include
aliases and CTE references as written; column references do not resolve aliases,
wildcards, types, or database schemas. Successful parsing is not proof of database
validity, read-only behavior, or safety. SQL is never executed.

SQL limits are 50,000 input characters, 10 statements, 10,000 AST nodes, and 100
nested levels. Each statement reports at most 100 distinct table references,
column references, and CTE names, each capped at 500 characters with truncation
flags. Combined output is capped at 100,000 characters. One SQL worker per server
process enforces a five-second wall timeout and, on Linux, a 128 MB address-space
cap and three-second CPU cap.

Version comparison accepts two exact versions up to 200 characters and an explicit
`semver` (default) or `pep440` scheme. The result compares the first version against
the second: -1/older, 0/equal precedence, or 1/newer. SemVer requires major.minor.patch,
rejects leading `v` and incomplete versions, and ignores build metadata in ordering.
PEP 440 normalizes Python versions and handles epochs, pre/dev/post/local releases.
Ranges are not supported; ordering says nothing about compatibility or upgrade safety.
The batch adds SQLGlot and semver, and declares packaging as a direct dependency.
No new API keys are needed.

References: [GitHub workflow jobs](https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run),
[SQLGlot](https://github.com/tobymao/sqlglot),
[Python project metadata](https://packaging.python.org/en/latest/specifications/pyproject-toml/),
[SemVer](https://semver.org/), and [PEP 440 version handling](https://packaging.pypa.io/en/stable/version.html).

Release and troubleshooting examples
-----------------------------------

```text
compare_lockfiles(before='{"lockfileVersion":3,"packages":{"node_modules/demo":{"version":"1.0.0"}}}', after='{"lockfileVersion":3,"packages":{"node_modules/demo":{"version":"2.0.0"}}}', format="package-lock.json")
get_vulnerability_details(advisory_id="GHSA-jf85-cpcp-j695", max_affected=5)
apply_json_patch(value='{"enabled":false}', patch='[{"op":"replace","path":"/enabled","value":true}]')
analyze_jsonl_logs(content='{"level":"error","message":"Request failed","timestamp":"2026-01-01T12:00:00Z"}\n')
```

Lockfile comparison accepts the same formats as inspection and reads all records
before summarizing changes, including those beyond inspection's 500-record return
limit. npm identities include package paths; Python names are normalized and all
recorded versions for a name are grouped, preserving repeated versions. Changes
compare version strings, not version precedence. Sources, environment markers,
hashes, and dependency flags are ignored. Records without resolved versions are
counted under `unresolved` and set `complete` to false. `equal` describes resolved
versions only. Each input allows 2,000,000 characters; `limit` returns 1-200 changes
with full counts and up to 100 versions per change. Output is capped at 100,000
characters and `truncated` marks omitted changes or versions.

Advisory details use one public, host-pinned OSV request with the shared 1 MB
download limit. It returns publication/withdrawal metadata, severity strings,
affected packages, range events, version lists, and references. `fixed` events
retain their range type: GIT events identify commits. They are not interpreted
as compatible upgrade recommendations. References are listed without fetching.
Bounds are 1-20 affected packages, 100-20,000 detail characters, 20 aliases and
references, five severity/range entries, 20 events per range, and 50 listed
versions per package. Shortened strings/arrays set `truncated`; output above
100,000 characters returns an error requesting smaller limits.

JSON Patch uses `jsonpatch` for RFC 6902 operations and `jsonpointer` for paths.
The tool supports add/remove/replace/move/copy/test, escaped keys, array insertion
and appending, and root replacement. Tests distinguish booleans from numbers,
while integer and floating-point JSON numbers compare by value. Removing the
document root returns an error; use replacement with null if desired. Errors
include the failing operation number without a partial result. Only supplied
JSON is transformed; no files or external APIs are modified. Each input/output
allows 200,000 characters with at most 50 operations, 10,000 nodes, and 50 nesting
levels. Resource limits are checked after every operation to bound copy growth.

Log analysis reads supplied JSON object lines and reports level/error counts,
frequent exact messages, malformed-line samples, and a UTC timestamp range.
Field names are configurable top-level keys. Text levels are normalized to
lowercase; warn/err/fatal map to warning/error/critical. Numeric levels are
unknown because logging systems use different numeric scales. Only ISO datetime
strings with explicit UTC offsets enter the time range; invalid/missing times
are counted. Blank lines are counted separately. Input allows 1,000,000
characters and 5,000 lines; each entry allows 200,000 characters, 1,000 nodes,
and 20 nested levels. `limit` is 1-50 message/error/invalid samples, with totals
covering every supplied line. At most 20 level groups and 1,000 message characters
are returned; omissions set `truncated`. Output is capped at 100,000 characters.

References: [OSV advisory API](https://google.github.io/osv.dev/get-v1-vulns/),
[OSV range schema](https://ossf.github.io/osv-schema/),
[JSON Patch](https://datatracker.ietf.org/doc/html/rfc6902), and
[JSON Lines](https://jsonlines.org/).

Deployment diagnostic examples
------------------------------

```text
check_http_endpoints(endpoints_json='[{"name":"health","url":"https://mcpsever.fly.dev/health","expected_status":200},{"name":"example","url":"https://example.com"}]')
get_github_commit_checks(owner="pallets", repo="flask", ref="main", limit=10)
inspect_dockerfile(content='FROM python:3.12-slim AS app\nUSER 1000\nEXPOSE 8000\nCMD ["python", "app.py"]\n')
inspect_http_cache(url="https://example.com")
```

Endpoint checks accept a JSON array of 1-5 objects containing `url`, optional
`name` (up to 100 characters), and optional `expected_status` (default 200).
Unknown fields and malformed input are rejected before network access. Results
preserve input order and include final URL/status, full-request elapsed
milliseconds (excluding queue time), a status match, and individual errors.
There are at most two simultaneous requests per batch, each using GET with a
10-second request budget. Blocking DNS resolution cannot be interrupted by this
budget and can exceed it. The shared transport blocks non-public destinations
and redirects, limits redirects to three, and caps each download at 1 MB.
Credentials, custom headers, and request bodies are not accepted. Input is
limited to 25,000 characters and URLs to 4,096 characters on ports 80/443.

Commit checks use two public, host-pinned GitHub requests: combined legacy
statuses resolve the reference to a SHA, and latest check runs use that same
SHA. `limit` returns 1-20 rows per endpoint; full counts, separate pagination
flags, empty indicators, and pending/failure observations are included.
Observation counts cover returned rows only. The legacy `combined_state` does
not include check runs, and empty results do not indicate CI passed. Required
checks and branch protection are not evaluated. GitHub caps this check-run
endpoint at the 1,000 most recent check suites. Text shortening sets the overall
`truncated` flag. Each request retains the shared 1 MB download limit.

Dockerfile inspection uses `dockerfile-parse` in memory. It reports stages,
base-image expressions, platform expressions, references to earlier named
stages, instruction counts, global ARG declarations, and the last declared
USER, WORKDIR, CMD, and ENTRYPOINT per stage, plus declared EXPOSE tokens.
Shell/JSON exec commands and multiline instructions are distinguished. Values
are not expanded; inherited image/stage settings are not inferred. An absent
USER is reported as undeclared, not as proof of running as root. No build,
execution, image download, or file modification occurs. This is a structural
summary, not Docker build validation. BuildKit heredoc/`<<` syntax is rejected.
Bounds are 200,000 input characters, 5,000 physical lines, 1,000 instructions, 20 stages, 100 returned
ports/command arguments per stage, and 2,000 characters per returned value.
Omitted values set `truncated`.

Cache inspection uses HEAD with GET fallback on 405/501, reporting the method
and final response even for non-2xx statuses. Cache-Control parsing preserves
quoted field lists and repeated directives. Browser freshness uses `max-age`;
shared-cache freshness prefers `s-maxage`. Invalid/duplicate numeric directives
do not produce inferred lifetimes. `no-cache` validation is distinct from
`no-store` storage prohibition, with field-qualified private/no-cache directives
and the must-understand exception reported explicitly. Conflicts appear under
`issues`. Header interpretation does not guarantee actual caching behavior;
declared lifetimes are not remaining TTL, and Age/Date/Expires timing is not
calculated. Up to 16,000 Cache-Control characters and 100 directives are parsed;
selected raw response headers are returned up to 2,000 characters each, with a
truncation flag. The shared public transport and download limits apply.

All four tools cap output at 100,000 characters and need no new API keys.
This batch adds only the Dockerfile parser dependency.

References: [GitHub check runs](https://docs.github.com/en/rest/checks/runs#list-check-runs-for-a-git-reference),
[GitHub combined statuses](https://docs.github.com/en/rest/commits/statuses#get-the-combined-status-for-a-specific-reference),
[Dockerfile reference](https://docs.docker.com/reference/dockerfile/),
[dockerfile-parse](https://github.com/containerbuildsystem/dockerfile-parse), and
[HTTP caching](https://datatracker.ietf.org/doc/html/rfc9111).

Run the focused utility tests:

```powershell
uv run python -m unittest discover -s tests -v
```

After deploying, test the live MCP connection and previously deployed tools:

```powershell
uv run python scripts/test_deployed_mcp.py
```

The script reads `MCP_API_KEY` from the environment or the project's ignored
`.env` file. The local test suite uses mocked HTTP responses; the deployment
script makes an authenticated MCP connection and fetches `https://example.com`.
It also fetches the Django weblog RSS feed and the Python statistics documentation
to verify feed and table extraction, then checks the numeric, diff, and unit
tools. The live suite also verifies PDF, public GitHub, OpenAPI, npm metadata,
OSV advisories, GitHub workflow runs/jobs, JMESPath queries, dependency manifests,
SQL analysis, version comparison, lockfile comparison, advisory details,
JSON Patch, structured logs, endpoint checks, commit checks, Dockerfile inspection,
and HTTP caching, for a total of 43
authenticated tool calls. The new checks require deployment of the latest code.
The endpoint check targets the supplied base URL's public `/health` route;
loopback/private base URLs cannot pass that outbound check.

Configuration
-------------

Required environment variables for API-backed tools:

```env
OPENWEATHER_API_KEY=
TAVILY_API_KEY=
MCP_API_KEY=
```

`MCP_API_KEY` protects all MCP/tool routes. `/` and `/health` remain public so
Fly.io health checks can work. If `MCP_API_KEY` is not set, authentication is
disabled for local development.

Local run
---------

```powershell
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health check:

```text
http://localhost:8000/health
```

Fly.io deploy
-------------

```powershell
fly secrets set OPENWEATHER_API_KEY=your_openweather_key
fly secrets set TAVILY_API_KEY=your_tavily_key
fly secrets set MCP_API_KEY=your_long_random_server_key
fly deploy
```

After deployment, use the Fly.io app URL as your hosted MCP server endpoint.
Pass the key from clients with either:

```text
X-API-Key: your_long_random_server_key
```

or:

```text
Authorization: Bearer your_long_random_server_key
```
