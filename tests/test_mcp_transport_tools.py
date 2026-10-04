import base64
import json
import unittest

from mcp.server.fastmcp import FastMCP

from app.tools.mcp_contract_utils import tool


def request(method="tools/call", name="lookup", request_id=1):
    return {"jsonrpc": "2.0", "id": request_id, "method": method,
            "params": {"name": name, "arguments": {"query": "PRIVATE_ARGUMENT"},
                       "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                 "io.modelcontextprotocol/clientCapabilities": {"elicitation": {}},
                                 "io.modelcontextprotocol/clientInfo": {"name": "PRIVATE_CLIENT", "version": "1"}}}}


def headers(name="lookup"):
    return {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call", "Mcp-Name": name,
            "Authorization": "Bearer PRIVATE_TOKEN"}


class McpTransportToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("mcp-transport-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        blocks = result[0] if isinstance(result, tuple) else result
        return "\n".join(block.text for block in blocks if block.type == "text")

    async def result(self, name, **arguments):
        return json.loads(await self.call(name, **arguments))

    async def test_request_metadata_valid_and_redacted(self):
        text = await self.call("validate_mcp_request_metadata", request=json.dumps(request()))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertTrue(value["client_info_present"])
        self.assertEqual(value["capability_count"], 1)

    async def test_request_metadata_required_fields_and_optional_client_info(self):
        supplied = request()
        del supplied["params"]["_meta"]["io.modelcontextprotocol/clientInfo"]
        self.assertTrue((await self.result("validate_mcp_request_metadata", request=json.dumps(supplied)))["valid"])
        del supplied["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"]
        value = await self.result("validate_mcp_request_metadata", request=json.dumps(supplied))
        self.assertFalse(value["valid"])
        self.assertIn("client_capabilities_object_required", value["issues"])
        supplied["params"]["_meta"] = None
        value = await self.result("validate_mcp_request_metadata", request=json.dumps(supplied))
        self.assertIn("request_meta_object_required", value["issues"])
        supplied["params"]["_meta"] = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                        "io.modelcontextprotocol/clientCapabilities": {},
                                        "io.modelcontextprotocol/logLevel": []}
        value = await self.result("validate_mcp_request_metadata", request=json.dumps(supplied))
        self.assertIn("log_level_invalid", value["issues"])

    async def test_http_exchange_valid_and_redacted(self):
        text = await self.call("validate_mcp_http_exchange", request=json.dumps(request()),
                               request_headers=json.dumps(headers()), response_status=200,
                               response_headers='{"Content-Type":"application/json"}')
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertTrue(value["named_method"])

    async def test_http_exchange_detects_mismatch_and_bad_response(self):
        incoming = headers("wrong")
        incoming["Mcp-Method"] = "prompts/get"
        incoming["MCP-Protocol-Version"] = "2025-11-25"
        value = await self.result("validate_mcp_http_exchange", request=json.dumps(request()),
                                  request_headers=json.dumps(incoming), response_status=200,
                                  response_headers='{"Content-Type":"text/plain"}')
        self.assertFalse(value["valid"])
        self.assertTrue({"protocol_version_header_mismatch", "method_header_mismatch",
                         "name_header_mismatch", "response_content_type_invalid"}.issubset(set(value["issues"])))

    async def test_http_exchange_encoded_name_and_error_status(self):
        supplied = request(name="cafe\u00e9")
        incoming = headers(name="=?base64?" + base64.b64encode("cafe\u00e9".encode()).decode() + "?=")
        value = await self.result("validate_mcp_http_exchange", request=json.dumps(supplied),
                                  request_headers=json.dumps(incoming), response_status=401,
                                  response_headers='{"Content-Type":"text/plain"}')
        self.assertTrue(value["valid"])
        self.assertTrue(value["response_is_error"])
        incoming["Mcp-Name"] = "=?base64?bad?="
        value = await self.result("validate_mcp_http_exchange", request=json.dumps(supplied),
                                  request_headers=json.dumps(incoming), response_status=401,
                                  response_headers="{}")
        self.assertIn("name_header_mismatch", value["issues"])

    async def test_http_exchange_rejects_invalid_header_input(self):
        for incoming in ('{"Mcp-Name":"a","mcp-name":"b"}',
                         '{"Authorization":"secret\\r\\nX-Injected: yes"}'):
            with self.subTest(incoming=incoming):
                self.assertTrue((await self.call("validate_mcp_http_exchange", request=json.dumps(request()),
                                                  request_headers=incoming, response_status=200,
                                                  response_headers="{}")).startswith("Error:"))

    async def test_input_required_roundtrip_valid_and_redacted(self):
        initial = request()
        result = {"jsonrpc": "2.0", "id": 1, "result": {"resultType": "input_required",
                  "inputRequests": {"PRIVATE_ID": {"method": "elicitation/create",
                                                   "params": {"message": "PRIVATE_PROMPT"}}},
                  "requestState": "PRIVATE_STATE"}}
        retry = request(request_id=2)
        retry["params"]["inputResponses"] = {"PRIVATE_ID": {"action": "accept", "content": "PRIVATE_REPLY"}}
        retry["params"]["requestState"] = "PRIVATE_STATE"
        text = await self.call("inspect_mcp_input_required_roundtrip",
                               initial_request=json.dumps(initial), result=json.dumps(result),
                               retry_request=json.dumps(retry))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["input_request_count"], 1)
        self.assertTrue(value["request_state_present"])

    async def test_input_required_roundtrip_detects_invalid_retry(self):
        initial = request()
        result = {"resultType": "input_required", "inputRequests": {
            "consent": {"method": "elicitation/create", "params": {}}}, "requestState": "opaque"}
        retry = request()
        retry["params"]["requestState"] = "tampered"
        retry["params"]["arguments"] = {"query": "changed"}
        value = await self.result("inspect_mcp_input_required_roundtrip",
                                  initial_request=json.dumps(initial), result=json.dumps(result),
                                  retry_request=json.dumps(retry))
        self.assertFalse(value["valid"])
        self.assertTrue({"retry_id_not_new", "retry_parameters_changed", "request_state_not_echoed",
                         "input_responses_missing"}.issubset(set(value["issues"])))

    async def test_input_required_state_only_and_unexpected_response(self):
        initial = request()
        retry = request(request_id=2)
        retry["params"]["requestState"] = "opaque"
        retry["params"]["inputResponses"] = {"extra": {}}
        value = await self.result("inspect_mcp_input_required_roundtrip",
                                  initial_request=json.dumps(initial),
                                  result='{"resultType":"input_required","requestState":"opaque"}',
                                  retry_request=json.dumps(retry))
        self.assertTrue(value["valid"])
        self.assertEqual(value["unexpected_response_count"], 1)

    async def test_auth_discovery_valid_and_redacted(self):
        challenge = ('Bearer resource_metadata="https://mcp.example/.well-known/oauth-protected-resource", '
                     'scope="PRIVATE_SCOPE"')
        resource = {"resource": "https://mcp.example/mcp",
                    "authorization_servers": ["https://auth.example"]}
        authorization = {"issuer": "https://auth.example",
                         "authorization_endpoint": "https://auth.example/authorize",
                         "token_endpoint": "https://auth.example/token"}
        text = await self.call("inspect_mcp_auth_discovery", challenge=challenge,
                               resource_metadata=json.dumps(resource),
                               authorization_metadata=json.dumps(authorization),
                               resource_url="https://mcp.example/mcp")
        self.assertNotIn("PRIVATE_SCOPE", text)
        self.assertNotIn("auth.example", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertTrue(value["scope_challenge_present"])
        authorization["issuer"] = "https://other.example"
        value = await self.result("inspect_mcp_auth_discovery", challenge=challenge,
                                  resource_metadata=json.dumps(resource),
                                  authorization_metadata=json.dumps(authorization),
                                  resource_url="https://mcp.example/mcp")
        self.assertIn("issuer_not_advertised", value["issues"])

    async def test_auth_discovery_rejects_insecure_and_malformed_input(self):
        value = await self.result("inspect_mcp_auth_discovery",
                                  challenge='Bearer resource_metadata="http://mcp.example/metadata"',
                                  resource_metadata='{"resource":"http://mcp.example/mcp","authorization_servers":[]}',
                                  authorization_metadata='{"issuer":"http://auth.example"}',
                                  resource_url="http://mcp.example/mcp")
        self.assertFalse(value["valid"])
        self.assertIn("resource_url_invalid", value["issues"])
        self.assertTrue((await self.call("inspect_mcp_auth_discovery", challenge="Basic token",
                                          resource_metadata="{}", authorization_metadata="{}",
                                          resource_url="https://mcp.example/mcp")).startswith("Error:"))
        self.assertTrue((await self.call("inspect_mcp_auth_discovery",
                                          challenge='Bearer resource_metadata="https://mcp.example/metadata"\r\nX: bad',
                                          resource_metadata="{}", authorization_metadata="{}",
                                          resource_url="https://mcp.example/mcp")).startswith("Error:"))


if __name__ == "__main__":
    unittest.main()
