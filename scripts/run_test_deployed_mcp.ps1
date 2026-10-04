param(
    [string]$ApiKey = $env:MCP_API_KEY,
    [string]$BaseUrl = "https://mcpsever.fly.dev",
    [ValidateSet("sse", "streamable-http")][string]$Transport = "sse"
)

$ErrorActionPreference = "Stop"

if (-not $ApiKey) {
    Write-Error "Missing API key. Set MCP_API_KEY or pass -ApiKey your_key."
}

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$sitePackages = Join-Path $projectRoot ".venv\Lib\site-packages"
$win32 = Join-Path $sitePackages "win32"
$win32Lib = Join-Path $win32 "lib"
$python = "C:\Users\kusha\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Bundled Python not found at $python"
}

$env:PYTHONPATH = "$sitePackages;$win32;$win32Lib"
$env:MCP_API_KEY = $ApiKey

& $python (Join-Path $projectRoot "scripts\test_deployed_mcp.py") --base-url $BaseUrl --transport $Transport
