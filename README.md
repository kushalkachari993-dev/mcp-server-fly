MCPSever
========

A reusable MCP server intended for deployment on Fly.io. It exposes utility
tools that can be connected to from other projects or production AI clients.

Available tools
---------------

The server registers 104 tools.

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
- `inspect_docker_compose(content, limit)` - summarize supplied Compose services, ports, dependency links, and health declarations offline.
- `inspect_github_actions(content, limit, max_steps)` - summarize supplied workflow triggers, permissions, runners, and action references offline.
- `inspect_redirect_chain(url)` - trace public redirect hops, loops, partial errors, and HTTPS downgrades.
- `inspect_http_cors(url, origin, requested_method, requested_headers_json)` - inspect anonymous response and preflight CORS declarations.
- `inspect_fly_config(content)` - inspect supplied fly.toml services, ports, checks, machine settings, and autostart/autostop declarations offline.
- `compare_env_keys(template, available_keys_json)` - compare dotenv template names with supplied environment key names without returning values.
- `inspect_kubernetes_manifest(content, limit)` - summarize supplied Kubernetes workloads, Services, probes, resource declarations, and secret references offline.
- `inspect_sbom(content, limit)` - inspect supplied CycloneDX JSON component inventory, declared licenses, and dependency relationships offline.
- `inspect_junit_report(content, limit)` - summarize supplied JUnit XML outcomes, failure metadata, and slowest reported tests offline.
- `inspect_sarif_report(content, limit)` - summarize supplied inline SARIF 2.1.0 results, explicit levels, locations, and suppression requests offline.
- `inspect_prometheus_metrics(content, limit)` - inspect supplied Prometheus text metric families, labels, and sample values offline.
- `analyze_access_logs(content, format, limit)` - summarize supplied Apache common/combined logs by status, method/path, errors, and reported bytes offline.
- `inspect_lcov_report(content, limit)` - inspect supplied LCOV line/function/branch observations, declarations, uncovered lines, and count mismatches offline.
- `inspect_cobertura_report(content, limit)` - inspect supplied Cobertura XML rates, direct class line/branch observations, and least-covered classes offline.
- `inspect_har(content, limit)` - inspect supplied HAR 1.2 request statuses, slow requests, query-free targets, timings, and response sizes offline.
- `inspect_k6_summary(content, limit)` - inspect supplied legacy or version 1.0.0 machine-readable k6 summaries, explicit thresholds, and individual checks offline.
- `compare_coverage_reports(before, after, format, limit)` - compare observed LCOV or Cobertura coverage, report identities, and line-number hit transitions offline.
- `compare_junit_reports(before, after, limit)` - compare matched JUnit test outcomes and durations, keeping duplicate or missing identities ambiguous.
- `compare_har_reports(before, after, limit)` - compare grouped sanitized HAR request targets, timing observations, status counts, and reported response sizes offline.
- `compare_k6_summaries(before, after, limit)` - compare compatible k6 metric values and explicit threshold results without evaluating expressions or guessing units.
- `inspect_graphql_schema(schema_sdl, limit)` - inspect valid supplied GraphQL SDL roots, types, fields, arguments, directives, and deprecation flags offline.
- `validate_graphql_operation(schema_sdl, document, limit)` - statically validate all supplied GraphQL operations/fragments without executing resolvers or coercing runtime variables.
- `compare_graphql_schemas(before_sdl, after_sdl, limit)` - report GraphQL-core breaking/dangerous schema changes and separate operation-root changes offline.
- `inspect_postman_collection(content, limit)` - inspect supplied Postman Collection v2.1 folders, requests, sanitized targets, and declared/inherited authentication types offline.
- `compare_docker_compose(before, after, limit)` - compare selected supplied Compose service, image/build, port, dependency, health-check and resource-name declarations offline.
- `compare_kubernetes_manifests(before, after, limit)` - compare selected supplied Kubernetes workload/Service declarations and secret references by explicit object identity, keeping duplicates/generated names ambiguous.
- `compare_github_actions(before, after, limit)` - compare supplied workflow triggers, explicit permissions, job runners/dependencies, action references and step sequences offline.
- `compare_fly_configs(before, after, limit)` - compare selected supplied fly.toml regions, service ports/checks, VM settings, autostart/autostop, mounts and configuration key names offline.

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

Configuration and integration examples
--------------------------------------

```text
inspect_docker_compose(content='services:\n  web:\n    image: nginx:stable\n    ports: ["8080:80"]\n')
inspect_github_actions(content='on: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n')
inspect_redirect_chain(url="https://example.com")
inspect_http_cors(url="https://example.com", origin="https://app.example", requested_method="GET", requested_headers_json='["X-Request-ID"]')
```

The configuration tools read supplied YAML only. No files, images, referenced
workflows, or network resources are accessed; no commands are executed. The safe
loader preserves `on`, `yes`, and `no` as text, recognizes only true/false as
implicit booleans, and avoids sexagesimal integers such as unquoted `22:22`.
Leading-zero decimal numbers use decimal interpretation. Dates remain strings.
Duplicate/non-string keys, unknown/unsafe tags, multiple documents, non-finite
numbers, recursive aliases, and excessive alias/merge expansion are rejected.
Normal aliases and merge keys are supported. This restricted scalar handling is
not a claim of full YAML 1.2 or vendor-schema validation. Parse errors report
locations without echoing source snippets.

Compose output includes service images/build paths, short/long port declarations,
dependency conditions, environment-variable names, health-check forms/timing,
and top-level network/volume/secret/config names. It reports dependency cycles
and unknown service references without deciding whether deployment is valid.
Environment values, build arguments, commands, and health-check command bodies
are omitted. Variables, includes, extends, profiles, and override files are not
resolved; listed settings are declarations, not effective runtime settings.

Workflow output includes event names, common branch/path/type filters, schedules,
input/secret names, declared workflow/job permissions, runner expressions,
job dependencies, matrix axis names, step counts, and action/reusable-workflow
references. Environment values, run bodies, with arguments, and secret values
are omitted. Expressions and matrices are not expanded, referenced workflows are
not fetched, and repository permission defaults are not inferred. Cycle and
unknown-dependency observations cover all declared jobs, including omitted rows.

Both YAML tools accept up to 200,000 input characters, 10,000 expanded YAML nodes
(including keys), 50 nesting levels, and 100 services/jobs. `limit` returns 1-50
services/jobs. Workflows allow 1,000 total steps, with `max_steps` returning 1-50
per job. Returned text is capped at 2,000 characters per value; shortening and
row omissions set `truncated`. Selected declaration lists allow 100 entries.

Redirect tracing uses HEAD, falling back to GET on 405/501. It follows at most
three redirects and reports up to four successfully observed URL responses.
`redirect_responses` includes an un-followed final redirect; `followed_redirects`
counts transitions with an observed next response. Loops, missing/invalid
locations, the hop limit, and network failures retain a partial trace and an
`error`. `final_url` is the last observed response, not an unrequested target.
Every requested hop uses the shared IP-pinned public transport. Private targets,
credentials in URLs, and ports other than 80/443 are blocked. URLs/locations are
limited to 4,096 characters. No cookies, authorization headers, or bodies are sent.

CORS inspection sends OPTIONS preflight metadata and an independent anonymous
GET to the same public URL, without following redirects. `requested_method`
defaults to GET and is never executed; even DELETE or POST only appears in
Access-Control-Request-Method. `requested_headers_json` holds up to 20 header
names of 100 characters each, not values; no authentication/cookies are sent.
The supplied origin is normalized from an HTTP/HTTPS origin (any valid port) or
the opaque origin `null`. Origin hosts are metadata and are never fetched.
Output separates anonymous and credentialed declarations, checks preflight
status/method/header matching, and handles wildcard/Authorization exceptions.
GET is not verification of another requested method/header combination. These
are header observations, not a browser test, authorization assessment, or proof
of safety; browser safelisted header values are not modeled. Up to 100 tokens
per response header list and 16,000 characters per selected response header are
inspected; raw returned headers are capped at 2,000 characters with truncation.

Both HTTP tools share a 25-second total request budget per call; blocking DNS
resolution can exceed it. Each response is capped at 1 MB. All four tools cap
output at 100,000 characters. This batch needs no new dependencies or API keys.

References: [Compose services](https://docs.docker.com/reference/compose-file/services/),
[GitHub workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
[PyYAML](https://pyyaml.org/wiki/PyYAMLDocumentation),
[HTTP redirects](https://datatracker.ietf.org/doc/html/rfc9110#section-15.4), and
[CORS](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS).

Deployment readiness and inventory examples
------------------------------------------

```text
inspect_fly_config(content='app = "demo"\n[http_service]\ninternal_port = 8000\nauto_stop_machines = "stop"\nauto_start_machines = true\nmin_machines_running = 0\n')
compare_env_keys(template='MCP_API_KEY=\nPORT=8000\n', available_keys_json='["MCP_API_KEY"]')
inspect_kubernetes_manifest(content='apiVersion: v1\nkind: Pod\nmetadata: {name: demo}\nspec:\n  containers: [{name: web, image: nginx:stable}]\n')
inspect_sbom(content='{"bomFormat":"CycloneDX","specVersion":"1.7","components":[{"type":"library","name":"demo","version":"1.0.0","bom-ref":"demo"}],"dependencies":[{"ref":"demo","dependsOn":[]}]}')
```

These four tools operate only on supplied text, without file/network access,
cloud credentials, command execution, or changes to deployments. Results are
declarations, not verified live state or proof that a deployment is valid.

Fly inspection accepts TOML and reports app/region, environment and process names,
selected build/deploy settings, HTTP and additional services, ports/ranges,
health-check declarations, concurrency, VM settings, and mounts. Environment,
build-argument and check-header values and command bodies are omitted. Unspecified
settings stay null or absent rather than being filled from Fly defaults. The
HTTP service's implicit ports 80/443 are identified separately. Legacy boolean
autostop declarations are preserved with a note; current documented spellings
are `off`, `stop`, and `suspend`. This does not retrieve secrets, inspect deployed
Machines, run checks, or calculate billing. Limits: 200,000 input characters,
10,000 nodes, 50 nesting levels, and 100 entries per selected collection.

Environment comparison parses a supplied dotenv template with python-dotenv's
parser, preserving duplicate key declarations. It accepts comments, export,
quoted/multiline values, and an initial BOM; values are discarded and never
interpolated. `available_keys_json` accepts names only, not a key/value object
or `NAME=value` strings. Keys are case-sensitive ASCII identifiers of at most
200 characters. It reports missing, unexpected, matched, and duplicate names.
`keys_match` compares sets, independent of duplicates. All template keys count
as expected names: optional/required semantics and actual value validity are
not inferred. The server's own environment is not read. Each input is capped at
200,000 characters, with 1,000 template declarations and 1,000 available entries.

Kubernetes inspection accepts YAML or JSON, multiple documents, and one-level
`kind: List` collections. Common inspected kinds are Pod, Deployment,
StatefulSet, DaemonSet, ReplicaSet, Job, CronJob, Service, Secret, and ConfigMap.
Other kinds receive metadata-only summaries with `inspected: false`. Workloads
report regular/init/ephemeral containers, images, declared replicas, ports,
resource requests/limits, probe actions/timings, and Secret/ConfigMap references
from environment declarations, image pull secrets, and volumes. Secret/ConfigMap
data, literal environment values, annotations, commands/arguments, and probe
header values are omitted. No defaults, API-version/schema validation, cluster
reference resolution, scheduling evaluation, Helm, or Kustomize rendering is
performed; resource quantities are returned without interpreting their units.
It reuses the restricted scalar/alias handling of the Compose/Actions loader,
but allows multiple documents. Bounds: 200,000 input characters, 100 documents
and objects, 10,000 expanded nodes across documents, 50 nesting levels, 200
total containers, and 100 entries per selected collection. `limit` returns
1-50 objects; counts and validation cover all objects, including omitted rows.

SBOM inspection accepts CycloneDX JSON versions 1.5, 1.6, and 1.7, not SPDX/XML.
Inventory includes `metadata.component` and nested component declarations;
`component_count` includes both. It reports component names, versions, package
URLs, types, scopes, and supplied license IDs/names/expressions, without checking
license validity/compliance or vulnerability status. License text, properties,
descriptions, and external references are omitted. Declared `dependsOn` edges
are distinct from component nesting; repeated targets are deduplicated. Graph
cycles and references absent from inspected components are reported, but those
references may belong to uninspected services or external BOMs and are not
necessarily invalid. No graph completeness or runtime reachability is inferred.
Bounds: 200,000 input characters, 10,000 nodes, 50 nesting levels, 1,000 components
including metadata/nesting, 1,000 dependency entries, 5,000 edges, and 50 license
choices per component. `limit` returns 1-200 components, dependency entries,
targets per entry, and unresolved references, with truncation indicators.

Selected text in Fly/Kubernetes/SBOM summaries is limited to 2,000 characters
(names often 200); oversized selected fields are rejected, not shortened.
All four tools reject combined output exceeding 100,000 characters. Parser
errors omit source snippets. No new dependencies or API keys are needed.

References: [Fly configuration](https://docs.fly.io/reference/configuration),
[python-dotenv parser](https://github.com/theskumar/python-dotenv),
[Kubernetes objects](https://kubernetes.io/docs/concepts/overview/working-with-objects/),
[Kubernetes probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/), and
[CycloneDX schema](https://github.com/CycloneDX/specification/blob/master/schema/bom-1.7.schema.json).

CI reports and observability examples
------------------------------------

```text
inspect_junit_report(content='<testsuite tests="2"><testcase name="ok" time="0.1"/><testcase name="broken"><failure message="assert failed"/></testcase></testsuite>')
inspect_sarif_report(content='{"version":"2.1.0","runs":[{"tool":{"driver":{"name":"demo"}},"results":[{"ruleId":"R1","level":"warning","message":{"text":"reported issue"}}]}]}')
inspect_prometheus_metrics(content='# TYPE requests_total counter\nrequests_total{code="200"} 3\n')
analyze_access_logs(content='192.0.2.8 - user [10/Oct/2000:13:55:36 -0700] "GET /health?token=hidden HTTP/1.1" 200 12 "-" "agent"', format='combined')
```

These tools inspect supplied text only. They do not read files, contact services,
run tests/scanners, scrape metrics, or change deployments. They summarize reported
observations, not verified findings, live health, or complete coverage. All four
accept at most 200,000 input characters and reject output exceeding 100,000
characters. `limit` defaults to 20 and accepts 1-50; totals cover all inspected
entries, including rows omitted by the limit. Returned lists/text have explicit
truncation indicators. Parser errors omit source snippets.

JUnit uses defusedxml for common `testsuite`/`testsuites` XML, including nested
suites and namespaces; DTDs and entities are forbidden. Observed outcomes count
direct testcase elements once. Suite aggregate counts/times remain separate,
and missing testcase times are not treated as measured zero. Mixed markers use
error, failure, then skipped precedence; unmarked cases are reported as passed.
Only declared durations are summed/ranked, not wall-clock CI duration. Failure
bodies, stdout/stderr, properties and file attributes are omitted. This is not
a universal JUnit schema validator and does not interpret vendor retry/flaky
extensions. Bounds: 10,000 XML elements, depth 50, 1,000 suites, 2,000 testcases,
and five diagnostics per testcase. `limit` bounds suites, attention
tests and slowest tests separately. Selected text is shortened to 1,000 characters.

SARIF accepts inline JSON version 2.1.0 with duplicate keys rejected. It reports
explicit result levels/kinds and suppression metadata without resolving rule
defaults, invocation overrides, templates, extensions or external property files.
Absent/null results are marked unavailable, distinct from an empty result array.
Suppression metadata states distinguish unknown, accepted, pending/unspecified
and not-accepted requests; all results count, including accepted suppressions.
Inline driver-rule/artifact indexes can supply IDs/URIs, but URI bases are not
expanded. Snippets, code flows, fixes, attachments, fingerprints and suppression
justifications are omitted. This is not full SARIF validation or evidence that
findings are valid. Bounds: 20,000 JSON nodes, depth 50, 20 runs, 1,000 driver rules
and artifacts per run, 2,000 total results, 20 locations/suppressions per result.
`limit` bounds runs, rule-count rows and results separately; at most five locations
per result are returned. Selected text is shortened to 1,000 characters (URIs 2,000).

Metrics uses prometheus-client's permissive Prometheus text parser, not full
format validation; OpenMetrics/protobuf are unsupported. It returns counter,
gauge, histogram, summary and untyped families. Family/counter names may be
normalized, and repeated declarations can share a parsed family block. Counts
distinguish parsed blocks, unique family names, samples and unique series;
duplicate series are identified by sample name and labels. NaN/+Inf/-Inf values
are JSON strings; timestamps are in seconds. No rates, trends, health conclusions
or histogram quantiles are inferred from a snapshot. Bounds: 5,000 lines/samples,
10,000 characters per line, 500 parsed family blocks, 20 labels per sample, and
2,000 characters per label value. `limit` bounds both families and samples per
family; help text is shortened to 1,000 characters.

Access logs uses apachelogs with fixed `common` or `combined` formats (default
`combined`), not custom format strings or JSON logs. It reports status counts,
4xx/5xx counts, known-byte totals, and UTC timestamp bounds. Missing status/byte
fields stay separately counted; the error fraction uses known statuses only.
Paths group exact method/path pairs, stripping queries/fragments/authority
without decoding percent escapes or inferring route templates. `unique_path_count`
counts these pairs, so GET and POST to one path are separate. CONNECT and
unsupported/malformed targets remain unclassified, but valid status/byte
observations still count. Client IPs/users, referrers and user agents are omitted;
invalid lines are counted without snippets. No request latency is inferred.
Bounds: 5,000 lines, 10,000 characters per line; `limit` bounds method/path/error
rows. Returned paths are shortened to 1,000 characters.

Diagnostic messages, scanner locations, metric labels/help and remaining access
paths can contain sensitive caller-supplied data. Omitted fields are not a blanket
redaction guarantee; sanitize reports before sending them to a shared server.
This batch adds defusedxml, prometheus-client and apachelogs, with no new API keys.

References: [JUnit XML in pytest](https://docs.pytest.org/en/stable/how-to/output.html#creating-junitxml-format-files),
[defusedxml](https://pypi.org/project/defusedxml/),
[SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/sarif-v2.1.0-os.html),
[Prometheus text parser](https://github.com/prometheus/client_python/blob/master/prometheus_client/parser.py), and
[apachelogs](https://apachelogs.readthedocs.io/en/stable/).

Coverage and performance examples
---------------------------------

```text
inspect_lcov_report(content='SF:app.py\nDA:1,2\nDA:2,0\nLF:2\nLH:1\nend_of_record\n')
inspect_cobertura_report(content='<coverage><packages><package name="demo"><classes><class name="App" filename="app.py"><lines><line number="1" hits="2"/><line number="2" hits="0"/></lines></class></classes></package></packages></coverage>')
inspect_har(content='{"log":{"version":"1.2","entries":[{"request":{"method":"GET","url":"https://example.com/health?token=hidden"},"response":{"status":200,"bodySize":12},"time":25,"timings":{"wait":20,"receive":5}}]}}')
inspect_k6_summary(content='{"metrics":{"http_reqs":{"type":"counter","contains":"default","values":{"count":10,"rate":2},"thresholds":{"count>5":{"ok":true}}}},"state":{"testRunDurationMs":5000}}')
```

All four work on supplied text, without opening source/report files, contacting
URLs, executing tests/load generators, or evaluating threshold expressions. These
are bounded inspectors, not full format/schema validators, and reported coverage
or performance is not proof of correctness, production capacity or complete data.
No new dependencies or API keys are needed. Inputs are capped at 200,000 characters,
outputs at 100,000. `limit` defaults to 20 and accepts 1-50 rows per returned list;
counts and selected-field checks cover omitted rows too. Large summaries return
an error asking for a smaller input/limit. Truncation is explicit, and parser
errors omit source snippets.

LCOV supports `SF`/`KF` source sections, `TN`, `DA`, legacy `FN`/`FNDA`, grouped
`FNL`/`FNA`, `BRDA`, and line/function/branch summary counts. Grouped aliases count
as one function; mixed function formats, duplicate coverpoints within a section,
misplaced records and unterminated sections are rejected. Observed counts stay
separate from declarations; mismatches are reported. Totals sum sections without
merging repeated source paths/test names, so they are not unique-file coverage.
Unreported function execution counts stay unknown. Branch `-` counts as not hit
with an unknown taken-count indicator; `U`-marked branches are returned but excluded
from coverage totals. Zero denominators/unknown function hits yield null coverage
percentages. Checksums and `VER` are not verified; uninspected record types such as
MC/DC are counted in `ignored_record_types` without returning their payloads.
Bounds: 5,000 lines, 10,000 characters per line, 200 source sections. `limit` bounds
sections and each section's uncovered lines, function/alias rows and branch rows.

Cobertura supports common coverage/package/class/line XML, including namespaces.
Root/package/class declarations remain separate from observations. Only direct
class line records are counted, not duplicate method-level copies. Classes sharing
a filename remain separate observations. Branch counts use explicit
`condition-coverage` hit/total pairs, not rounded percentages. Missing counts on
branch lines are tracked in `observed_branches.unknown` as unknown branch *lines*,
not an invented number of branches; percentages stay null if any such lines exist.
The least-covered list ranks classes with measured direct line records. External
DOCTYPE declarations are accepted without loading DTDs, but entity definitions
and external entity references are forbidden. Source-root text, method details,
XInclude and vendor extensions are not resolved. Bounds: 10,000 XML elements,
depth 50, 200 packages, 1,000 classes, 5,000 direct class line records. `limit`
bounds packages/classes, least-covered classes and uncovered lines per class.

HAR accepts JSON version 1.2. It returns individual entries, slowest/error requests,
status counts, host/MIME counts, and duration/timing-stage statistics. Only
HTTP/HTTPS targets return scheme/host/port/path; userinfo, query and fragment are
discarded, and other schemes return no target text. Cookies, headers, request and
response bodies, redirect URL values, comments, server-IP fields and page metadata
are omitted. A URL hostname can itself be an IP; it is never resolved or contacted.
Missing values and `-1` timing/body-size sentinels remain unknown, while measured
zero values stay zero. Status `0` is separate from HTTP 4xx/5xx errors. Timings are
milliseconds, with SSL reported separately but not added again to connect time.
Entry durations do not imply total page-load/wall-clock time. Body-size and
content-size totals are distinct reported fields, not total wire traffic. Bounds:
20,000 JSON nodes, depth 50, 1,000 entries, 200 pages, 10,000 characters per input
URL; returned paths are shortened to 1,000 characters. `limit` bounds each entry,
slowest/error, host and MIME list.

k6 supports flat legacy `handleSummary(data)` JSON (top-level metric map and optional
`root_group`/`state`) and machine-readable schema version `1.0.0` (metadata/config,
`results.metrics` array and optional check collections). Other versions, grouped
modern summaries, old flattened `--summary-export` metrics and raw JSONL are
rejected with a format error. Supply a supported JSON summary, not the output
filename map returned by `handleSummary`. Values, including custom percentile
keys and reported rates, are preserved without applying display-unit options or
recalculating throughput. Legacy duration milliseconds are converted to seconds;
machine v1 config duration is already seconds. Metric-level threshold `ok` statuses
are counted as passed/failed/unknown without evaluating expressions. Missing or
empty threshold metadata does not imply the test passed; machine v1 reports without
threshold information remain unknown. Individual check records are counted once;
missing pass/fail counters remain incomplete. Tagged metrics and separate check
metrics are not summed into overlapping totals; group/scenario metric aggregation
is unsupported. Setup data, script paths, IDs and options are omitted. Bounds:
20,000 JSON nodes, depth 50, 500 metrics per collection, 50 value fields and
thresholds per metric, 1,000 total thresholds/checks, 200 legacy groups. `limit`
bounds metric, threshold, failed-threshold, check and attention-check lists.

Coverage paths/names, HAR hosts/paths/MIME values and k6 metric/check/group names or
threshold expressions can still contain sensitive caller-supplied information.
Omitting selected fields is not a blanket redaction guarantee; sanitize reports
before sending them to a shared server. Selected identifiers are generally capped
at 1,000 characters; selected XML/group display text is shortened with truncation.
Numeric fields have finite/range checks (counts generally up to 1 trillion;
HAR/k6 numeric values have absolute magnitude at most 1 quadrillion).

References: [LCOV tracefile format](https://github.com/linux-test-project/lcov/blob/master/docs/man/geninfo.rst),
[Cobertura usage](https://docs.gitlab.com/ci/testing/code_coverage/cobertura/),
[HAR schema](https://github.com/ahmadnassri/har-schema),
[k6 custom summaries](https://grafana.com/docs/k6/latest/results-output/end-of-test/custom-summary/), and
[k6 machine-readable schema](https://github.com/grafana/k6-summary).

Report comparison examples
--------------------------

```text
compare_coverage_reports(before='SF:app.py\nDA:1,1\nend_of_record\n', after='SF:app.py\nDA:1,0\nend_of_record\n')
compare_coverage_reports(before='<coverage/>', after='<coverage/>', format='cobertura')
compare_junit_reports(before='<testsuite name="demo"><testcase name="test" classname="App" time="1"/></testsuite>', after='<testsuite name="demo"><testcase name="test" classname="App" time="2"><failure/></testcase></testsuite>')
compare_har_reports(before='{"log":{"version":"1.2","entries":[{"request":{"method":"GET","url":"https://example.com/health"},"response":{"status":200},"time":10}]}}', after='{"log":{"version":"1.2","entries":[{"request":{"method":"GET","url":"https://example.com/health"},"response":{"status":500},"time":20}]}}')
compare_k6_summaries(before='{"metrics":{"latency":{"type":"trend","contains":"time","values":{"p(95)":20},"thresholds":{"p(95)<30":{"ok":true}}}}}', after='{"metrics":{"latency":{"type":"trend","contains":"time","values":{"p(95)":40},"thresholds":{"p(95)<30":{"ok":false}}}}}')
```

These four tools compare supplied **before/after reports**, not filenames or URLs.
They reuse the existing inspector parsers and inspect all bounded records before
limiting output, including passing tests and records beyond the first 50 rows.
No new dependencies or API keys are required; no network requests, source-file
access, test execution, load generation or threshold evaluation is performed.
Each input is capped at 200,000 characters and retains its inspector's record,
depth and numeric limits. Combined output is capped at 100,000 characters;
`limit` defaults to 20 and accepts 1-50 rows per returned list. Large results
return an error requesting smaller reports/limits. `truncated` marks shortened
output, while counts include omitted rows. Errors omit report snippets.

`matching` reports matched, added, removed, ambiguous and unmatchable counts.
Repeated identities on either side remain ambiguous, even if absent on the other
side; they are never paired by position or silently merged. Missing or unsupported
identity fields are counted as unmatchable, not invented identities. Added/removed
means present only in one supplied report, not proof that a file, test, endpoint or
metric was really created/deleted. Ordinary numeric changes use `delta = after -
before`, with `relative_percent = delta / abs(before) * 100`. Missing/incompatible
measurements have null deltas and explicit reasons where applicable; zero
baselines or out-of-range ratios give null relative percentages. Empty reports
and missing values do not imply success, measured zero or complete coverage.

Coverage accepts two reports in the same selected `lcov` (default) or `cobertura`
format. LCOV matches exact `(file, test_name)` sections; Cobertura matches exact
`(file, package, class)` with nonempty package/class names of at most 1,000
characters without controls. Paths are not normalized or resolved. Coverage
changes use observed totals and record counts, not declared rates. Percentage
changes are **percentage points**, not relative percentages. Unknown hit/branch
counts prevent complete deltas; LCOV legacy/grouped function-format changes and
mixed-format aggregate function totals are not directly compared. Repeated sections/classes remain
separate in aggregate observations, not deduplicated unique-file coverage.
`newly_uncovered_lines` requires the same observed line number to change from
positive hits to zero in a matched record; the reverse is `newly_covered_lines`.
Added/removed lines and uncovered added lines are separate. No line-number mapping
across revisions occurs: the caller must ensure source/test comparability.

JUnit matches exact suite ancestry, classname and test name; classname may be
absent, but suite/test names must be nonempty. Identity components exceeding
1,000 characters or containing controls are unmatchable. `newly_failing_tests`
means passed to failed/error; `recovered_tests` means failed/error to passed.
Unmarked cases use the inspector's passed outcome; vendor retry/flaky extensions
are not interpreted. Skipped transitions are separate outcome changes. Mixed markers retain inspector
precedence but are marked uncertain and excluded from new failure/recovery counts.
Duration deltas are reported testcase seconds, not wall time or proof of a runtime
regression/flakiness. Failure bodies/messages, properties and stdout/stderr are
omitted. Parser aggregate declarations remain separate from observed cases.

HAR accepts version 1.2 and groups HTTP/HTTPS entries by method, scheme, parsed
lowercase host, effective port and exact full path. Omitted ports normalize to
80/443. Queries/fragments and userinfo are removed, so different queries
intentionally merge; percent-escapes are not decoded. Paths are matched before
being shortened to 1,000 characters for display. Unsupported URL schemes are
counted but not compared; repeated requests form aggregate groups rather than
one-to-one pairs. Each matched group compares available duration min/max/mean/
median in milliseconds, sample/missing counts, status counts (including distinct
status `0`), and reported body/content sizes. Missing sizes prevent complete
total-size deltas. Headers, cookies, bodies, redirect values, page metadata and
comments are omitted, but returned hosts/paths may still contain sensitive data.
Differences do not establish identical requests, comparable workloads, statistical
significance, causal regressions or total wire traffic.

k6 accepts the same flat legacy or machine-readable version `1.0.0` JSON shapes
as `inspect_k6_summary`. Metrics match exact source/name; numeric fields match
exact keys. Numeric deltas require the same summary format, metric type and known
`contains` dimension. Missing/changed dimensions, types or values and cross-format
comparisons yield unknown deltas instead of unit guesses or translated field keys.
Tagged metrics and separate check metrics remain distinct sources; statistics,
rates and percentiles are not recomputed or summed. The caller must ensure actual
units, scripts, load and environments are comparable. Thresholds match exact
source/metric/expression and compare only explicit compatible boolean results.
Missing/empty/unknown threshold information is not pass, and expressions are never
evaluated. Individual check counts remain before/after reported overviews, not
paired assertions. Setup data/options/script paths are omitted. Numeric or
threshold changes do not prove production capacity or a causal regression.

Names, coverage paths, HAR hosts/paths, metric keys and threshold expressions can
still contain sensitive caller-supplied data. Sanitize reports before sending
them to a shared server; selected-field omission is not blanket redaction.

GraphQL and Postman examples
----------------------------

```text
inspect_graphql_schema(schema_sdl='type Query { hello: String user(id: ID!): User } type User { id: ID! old: String @deprecated }')
validate_graphql_operation(schema_sdl='type Query { hello: String }', document='query Get { hello }')
compare_graphql_schemas(before_sdl='type Query { old: String }', after_sdl='type Query { hello: String }')
inspect_postman_collection(content='{"info":{"name":"demo","schema":"https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},"auth":{"type":"bearer"},"item":[{"name":"health","request":{"method":"GET","url":"https://example.com/health?token=hidden"}}]}')
```

All four accept supplied text/JSON, not filenames or live endpoints. No new API
keys are needed. GraphQL adds `graphql-core>=3.2.11,<3.3`, locked in `uv.lock`;
run `uv sync` after updating. The 3.2 series is used deliberately because its minor
versions can change APIs. No requests, resolvers, subscriptions, collection
scripts or source-file/import resolution are executed by these tools.

Each input is capped at 200,000 characters. `limit` defaults to 20 and accepts
1-50 rows per returned list; full bounded records are checked before output
limiting. Output is capped at 100,000 characters, with explicit truncation;
oversized summaries ask for smaller inputs/limits. GraphQL parsing additionally
caps schemas at 8,000 tokens, operation documents at 4,000 tokens, delimiter
nesting at 50, AST nodes at 10,000, definitions at 200, and names at 1,000
characters. Analysis runs in a five-second spawned worker with one active
GraphQL worker per server process; busy calls return a retry error. POSIX workers
also have a four-second CPU limit. Failed/timed-out workers are cleaned up.

The GraphQL inspector uses GraphQL-core SDL/schema validation and checks supplied
default literals with its value parser. It summarizes explicit/inferred query,
mutation and subscription roots, object/interface/input fields, argument types
and required/default-presence flags, unions, enums and directives. Introspection
types are excluded; referenced specified scalars/directives are identified.
Descriptions, default values, scalar URLs, directive application values and
deprecation reasons are omitted. Validity does not prove runtime behavior or auth.

Operation validation checks **every operation and fragment** using the library's
specified rules, without selecting/executing an operation. Variable definitions
and literals are statically checked; runtime variable values and custom scalar
implementations are not supplied or coerced. Diagnostics return rule IDs, node
kinds, selected identifiers and source locations instead of library messages
that could echo literal values. Syntax errors report a fixed message/location.
At most 50 validation errors plus an abort marker are collected, independently
of output `limit`; capped counts are observations, not total errors beyond the
cap. Authorization, query costs and runtime resolver behavior are outside scope.

Schema comparison uses GraphQL-core 3.2 breaking/dangerous-change categories for
fields, arguments, types, unions/enums, interfaces and directive definitions.
Root changes are separate review items; root replacement is not automatically a
breaking client contract. Added/removed type names and full change counts are
returned even if lists truncate. Argument-default change descriptions replace
actual values with a fixed message. This is not exhaustive compatibility analysis
of every addition, description, custom directive/scalar or runtime behavior.

Postman accepts v2.1 JSON exports with these official schema URL spellings:

```text
https://schema.getpostman.com/json/collection/v2.1.0/collection.json
https://schema.postman.com/json/collection/v2.1.0/collection.json
https://schema.getpostman.com/json/draft-07/collection/v2.1.0/
https://schema.postman.com/collection/json/v2.1.0/draft-07/collection.json
```

The inspector checks selected fields, not the complete Postman JSON Schema.
Bounds: 20,000 JSON nodes, depth 50, 1,000 total folder/request items, URLs at
10,000 characters. Duplicate JSON keys and nonfinite numbers are rejected.
String requests imply GET; missing object methods stay unknown and are counted
separately. Folder ancestry uses numeric indexes so unnamed/duplicate names do
not imply identical folders. Null/absent auth inherits the nearest folder or
collection declaration; `noauth` stops inheritance. The v2.1 schema's eleven auth
types are supported; missing declarations stay unknown, not proof of no runtime
authentication. Credential/helper values are omitted.

Only URL strings or object `raw` fields are inspected. HTTP/HTTPS targets omit
userinfo, queries and fragments; display paths shorten at 1,000 characters.
Components-only objects are not reconstructed or reconciled with `raw` fields.
URLs with `{{...}}` templates, unsupported schemes or missing URLs return no
target text. Variables/environment values are never resolved. Headers, bodies,
examples, scripts, descriptions, certificates and proxy settings are omitted.
Names, GraphQL identifiers/type references and HTTP hosts/paths can still contain
sensitive caller-supplied data; sanitize inputs before sharing them.

References: [GraphQL-core utilities](https://graphql-core-3.readthedocs.io/en/stable/modules/utilities.html),
[validation](https://graphql-core-3.readthedocs.io/en/stable/modules/validation.html),
[version compatibility](https://pypi.org/project/graphql-core/), and
[Postman Collection v2.1 schema](https://schema.postman.com/collection/json/v2.1.0/draft-07/collection.json).

Deployment configuration comparison examples
--------------------------------------------

```text
compare_docker_compose(before='services: {web: {image: "app:1"}}', after='services: {web: {image: "app:2"}, worker: {image: "app:2"}}')
compare_kubernetes_manifests(before='apiVersion: v1\nkind: Pod\nmetadata: {name: app}\nspec: {containers: [{name: web, image: "app:1"}]}', after='apiVersion: v1\nkind: Pod\nmetadata: {name: app}\nspec: {containers: [{name: web, image: "app:2"}]}')
compare_github_actions(before='on: push\njobs: {test: {steps: [{uses: "actions/checkout@v4"}]}}', after='on: push\njobs: {test: {steps: [{uses: "actions/checkout@v5"}]}}')
compare_fly_configs(before='app = "demo"\n[http_service]\ninternal_port = 8000\nauto_stop_machines = "stop"\n', after='app = "demo"\n[http_service]\ninternal_port = 8000\nauto_stop_machines = "off"\n')
```

These four tools reuse existing inspectors and dependencies. They accept file
contents, never filenames, and require no new API keys. Each input is capped at
200,000 characters, 10,000 parsed/expanded nodes and 50 nesting levels. Existing
format limits still apply: 100 Compose services, 100 Actions jobs/1,000 steps,
100 Kubernetes documents/objects and 200 containers, and 100 entries per Fly
collection. Empty Compose/job/object inventories are not accepted by the
existing inspectors. This is selected-field comparison, not complete schema
validation, a generic file diff, compatibility analysis or a deployment verdict.

Full bounded records, steps and selected text are compared before display
limiting. `limit` defaults to 20 and accepts 1-50 entries per returned list,
including nested before/after lists. Display strings shorten at 2,000 characters;
`truncated` marks partial display, not partial comparison. Output is capped at
100,000 characters; oversized results return an error asking for smaller
inputs/limits. A reported change can therefore have equal shortened previews.

All tools report `configuration_changes` with JSON Pointer paths, change type,
before/after selected values and presence flags. The Compose/Actions/Kubernetes
tools also report `matching` counts and added/removed identities, changed records
in `comparisons`, `changed_count` and `unchanged_count`. `change_count` counts
changed selected fields/sequences, including top-level changes; added/removed
records are counted separately. Counts cover all supplied bounded records even
when display lists shorten. Added/removed does not prove complete inventories.

`selected_fields_equal` means no change in the selected declarations, not that
the complete configurations or deployments are equivalent. It is false when a
known selected-field change or record addition/removal is found; null when there
are only unresolved/ambiguous identities. It is true otherwise, including when
only omitted values change. An ambiguous record is never called unchanged.

Compose services match by exact name and Actions jobs by exact job ID; renames
are added/removed. Kubernetes objects match by exact API group, kind, declared
namespace and metadata.name. API-version changes within one group remain matched
and are reported. Repeated identities, including two versions of the same group,
are ambiguous; generateName-only objects and malformed group/version splits
remain unmatchable. Omitted namespaces match other omitted declarations, not an
inferred `default` or cluster namespace. Unsupported kinds are metadata-only.

Dictionary field order is ignored. Lists remain whole declared sequences,
including ports, environments/key-name lists, containers, references, triggers,
steps and Fly service/VM/mount/check lists; entries are not guessed or paired by
index. Reordering these lists or changing declaration spelling can be reported
even if runtime behavior would be equivalent. Names listed from mappings retain
their declaration order. Resource quantities, ports, action refs, VM sizing and
legacy boolean/current string autostop settings are not semantically normalized.

Compose comparison covers inspector-selected images/build paths, ports,
dependencies, environment names, health-check declarations/settings and top-level
resource names. Actions covers triggers/filters, explicit permission declarations,
runners, needs, action references, step sequences, environment names and matrix
axis names/expression presence. Matrix values, conditions, concurrency and actual
token permissions are not evaluated. Kubernetes covers common workload and
Service settings, probes/resources and Secret/ConfigMap references/key names;
labels, annotations, rollout strategies and custom-kind bodies are outside scope.
Fly covers app/region, selected build/deploy fields, environment/process names,
service ports/checks/concurrency/autostart/autostop, VM declarations and mounts.

Environment/header/build-argument/Secret/ConfigMap values, script/command bodies
and Actions `with` values are omitted, including value-only changes. Names, paths,
selectors and image/action references can still contain sensitive caller data.
Sanitize supplied files before sharing results. No defaults, variable/expression
expansion, includes/extends/override merging, reusable-workflow resolution,
Helm/Kustomize rendering, file/network/cluster access, execution, deployment,
live Machine inspection or pricing/cost inference is performed.

References: [Compose services](https://docs.docker.com/reference/compose-file/services/),
[Kubernetes object identities](https://kubernetes.io/docs/concepts/overview/working-with-objects/names/),
[Actions workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax), and
[Fly app configuration](https://docs.fly.io/reference/configuration).

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
HTTP caching, Compose/Actions configuration, redirects, CORS, Fly configuration,
environment key comparison, Kubernetes manifests, CycloneDX inventory, JUnit,
SARIF, Prometheus metrics, access logs, LCOV/Cobertura coverage, HAR, k6 summaries,
coverage/JUnit/HAR/k6 report comparisons, GraphQL schema/operation analysis,
Postman collection inspection and Compose/Kubernetes/Actions/Fly configuration
comparisons, for a total of 71 authenticated tool
calls. The new checks require deployment of
the latest code.
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
