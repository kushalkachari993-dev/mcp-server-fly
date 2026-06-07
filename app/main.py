import os

os.environ.setdefault("MCP_SKIP_HOST_VALIDATION", "true")

import mcp.server.sse as sse_module
import uvicorn
from app.tools.registry import register_all_tools
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, PlainTextResponse


PUBLIC_PATHS = {"/", "/health"}


def disable_mcp_host_validation() -> None:
    """Allow Fly.io proxy hosts to reach the MCP SSE app."""

    sse_module._SKIP_HOST_VALIDATION = True
    if hasattr(sse_module, "_validate_host"):
        sse_module._validate_host = lambda *args, **kwargs: None


class ApiKeyAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        api_key = os.getenv("MCP_API_KEY")
        path = scope.get("path", "")

        if not api_key or path in PUBLIC_PATHS or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        headers = {name.lower(): value for name, value in scope.get("headers", [])}
        provided_key = headers.get(b"x-api-key", b"").decode("utf-8")
        authorization = headers.get(b"authorization", b"").decode("utf-8")

        if authorization.lower().startswith("bearer "):
            provided_key = authorization[7:].strip()

        if provided_key != api_key:
            response = PlainTextResponse("Unauthorized", status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


async def root_endpoint(request):
    auth_enabled = bool(os.getenv("MCP_API_KEY"))
    return JSONResponse(
        {
            "status": "ok",
            "mcp": "ready",
            "auth_enabled": auth_enabled,
        }
    )


async def health_check(request):
    return JSONResponse({"status": "healthy"})


def create_app():
    disable_mcp_host_validation()

    allowed_hosts = [
        host.strip()
        for host in os.getenv(
            "MCP_ALLOWED_HOSTS",
            "mcpsever.fly.dev,mcpsever.fly.dev:443,localhost:*,127.0.0.1:*",
        ).split(",")
        if host.strip()
    ]
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=["https://mcpsever.fly.dev", "http://localhost:*", "http://127.0.0.1:*"],
    )

    mcp = FastMCP(
        "multi-tool-server",
        host="0.0.0.0",
        stateless_http=True,
        transport_security=transport_security,
    )
    register_all_tools(mcp)

    base_app = mcp.sse_app()
    base_app.add_route("/", root_endpoint)
    base_app.add_route("/health", health_check)
    base_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return ApiKeyAuthMiddleware(base_app)


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
