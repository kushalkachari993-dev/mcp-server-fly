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
