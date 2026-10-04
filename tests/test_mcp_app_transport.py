import os
import unittest
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from app.main import create_app


_INITIALIZE = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                          "clientInfo": {"name": "test-client", "version": "1"}}}
_HEADERS = {"Accept": "application/json, text/event-stream",
            "Content-Type": "application/json", "X-API-Key": "test-secret"}


class McpAppTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_streamable_http_auth_health_and_legacy_routes(self):
        with patch.dict(os.environ, {"MCP_API_KEY": "test-secret"}):
            app = create_app()
            routes = {route.path for route in app.app.router.routes}
            self.assertTrue({"/mcp", "/sse", "/messages", "/", "/health"}.issubset(routes))
            async with app.app.router.lifespan_context(app.app):
                async with AsyncClient(transport=ASGITransport(app=app),
                                       base_url="http://localhost:8000") as client:
                    self.assertEqual((await client.get("/health")).json(), {"status": "healthy"})
                    denied = await client.post("/mcp", json=_INITIALIZE)
                    self.assertEqual(denied.status_code, 401)
                    self.assertEqual((await client.get("/sse")).status_code, 401)
                    connected = await client.post("/mcp", json=_INITIALIZE, headers=_HEADERS)
                    self.assertEqual(connected.status_code, 200)
                    self.assertEqual(connected.json()["result"]["protocolVersion"], "2025-11-25")
                    listed = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 2,
                                                                "method": "tools/list", "params": {}},
                                               headers=_HEADERS)
                    self.assertEqual(listed.status_code, 200)
                    self.assertEqual(len(listed.json()["result"]["tools"]), 153)
                    called = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 3,
                                                               "method": "tools/call",
                                                               "params": {"name": "calculate",
                                                                          "arguments": {"expression": "1 + 1"}}},
                                               headers=_HEADERS)
                    self.assertEqual(called.status_code, 200)
                    self.assertEqual(called.json()["result"]["content"][0]["text"], "1 + 1 = 2")

    async def test_host_origin_and_cors_are_restricted(self):
        with patch.dict(os.environ, {"MCP_API_KEY": "test-secret",
                                          "MCP_SKIP_HOST_VALIDATION": "true"}):
            app = create_app()
            async with app.app.router.lifespan_context(app.app):
                async with AsyncClient(transport=ASGITransport(app=app),
                                       base_url="http://localhost:8000") as client:
                    invalid_host = await client.post("/mcp", json=_INITIALIZE,
                                                     headers={**_HEADERS, "Host": "evil.example"})
                    self.assertEqual(invalid_host.status_code, 421)
                    invalid_origin = await client.post("/mcp", json=_INITIALIZE,
                                                       headers={**_HEADERS, "Origin": "https://evil.example"})
                    self.assertEqual(invalid_origin.status_code, 403)
                    valid_origin = await client.post("/mcp", json=_INITIALIZE,
                                                     headers={**_HEADERS, "Origin": "https://mcpsever.fly.dev"})
                    self.assertEqual(valid_origin.status_code, 200)
                    self.assertEqual(valid_origin.headers.get("access-control-allow-origin"),
                                     "https://mcpsever.fly.dev")
                    preflight = await client.options("/mcp", headers={
                        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
                    self.assertEqual(preflight.status_code, 400)


if __name__ == "__main__":
    unittest.main()
