MCPSever
========

A reusable MCP server intended for deployment on Fly.io. It exposes utility
tools that can be connected to from other projects or production AI clients.

Available tools
---------------

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
tools. The live suite also verifies PDF, public GitHub, and OpenAPI tools, for
a total of 27 authenticated tool calls.

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
