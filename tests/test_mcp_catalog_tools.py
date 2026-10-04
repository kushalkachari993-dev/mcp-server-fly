import json
import unittest

from mcp.server.fastmcp import FastMCP

from app.tools.mcp_contract_utils import tool


def resources():
    return {"resources": [{"uri": "https://user:PRIVATE_PASSWORD@example.test/docs/a?token=PRIVATE_QUERY#section",
                           "name": "guide", "description": "PRIVATE_DESCRIPTION",
                           "mimeType": "text/plain", "size": 10}]}


def templates():
    return {"resourceTemplates": [{"uriTemplate": "docs://items/{id}", "name": "item",
                                   "mimeType": "application/json"}]}


def prompts():
    return {"prompts": [{"name": "review", "description": "PRIVATE_PROMPT_DESCRIPTION",
                         "arguments": [{"name": "code", "required": True,
                                        "description": "PRIVATE_ARGUMENT_DESCRIPTION"},
                                       {"name": "language", "required": False}]}]}


class McpCatalogToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("mcp-catalog-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        blocks = result[0] if isinstance(result, tuple) else result
        return "\n".join(block.text for block in blocks if block.type == "text")

    async def result(self, name, **arguments):
        return json.loads(await self.call(name, **arguments))

    async def test_resource_inspection_sanitizes_uri_and_omits_descriptions(self):
        text = await self.call("inspect_mcp_resource_manifest", resources=json.dumps(resources()),
                               templates=json.dumps(templates()))
        for secret in ("PRIVATE_PASSWORD", "PRIVATE_QUERY", "PRIVATE_DESCRIPTION"):
            self.assertNotIn(secret, text)
        value = json.loads(text)
        self.assertEqual(value["resource_count"], 1)
        self.assertEqual(value["template_count"], 1)
        self.assertEqual(value["resources"][0]["identity"]["display_uri"], "https://example.test/docs/a")
        self.assertEqual(value["templates"][0]["identity"]["display_uri"], "docs://items/{id}")
        self.assertEqual(value["resources"][0]["size_bytes"], 10)

    async def test_omitted_templates_are_unknown_not_empty(self):
        value = await self.result("inspect_mcp_resource_manifest", resources=json.dumps(resources()))
        self.assertFalse(value["templates_supplied"])
        self.assertIsNone(value["template_count"])
        self.assertIsNone(value["templates"])

    async def test_resource_comparison_reports_selected_changes(self):
        old_resources, new_resources = resources(), resources()
        old_templates, new_templates = templates(), templates()
        changed = new_resources["resources"][0]
        changed["name"] = "new guide"
        changed["mimeType"] = "text/markdown"
        changed["size"] = 20
        new_resources["resources"].append({"uri": "docs://new", "name": "new"})
        new_templates["resourceTemplates"][0]["mimeType"] = "text/plain"
        value = await self.result("compare_mcp_resource_manifests",
                                  before_resources=json.dumps(old_resources), after_resources=json.dumps(new_resources),
                                  before_templates=json.dumps(old_templates), after_templates=json.dumps(new_templates))
        self.assertEqual(value["selected_change_count"], 5)
        self.assertTrue(value["templates_compared"])
        self.assertEqual({row["field"] for row in value["changes"]},
                         {"name", "mime_type", "size_bytes", "presence"})
        self.assertEqual({row["kind"] for row in value["changes"]}, {"resource", "template"})

    async def test_full_uri_identity_precedes_query_free_display(self):
        old = {"resources": [{"uri": "https://example.test/item?token=one", "name": "item"}]}
        new = {"resources": [{"uri": "https://example.test/item?token=two", "name": "item"}]}
        value = await self.result("compare_mcp_resource_manifests",
                                  before_resources=json.dumps(old), after_resources=json.dumps(new))
        self.assertEqual(value["selected_change_count"], 2)
        identities = [row["identity"] for row in value["changes"]]
        self.assertEqual({row["display_uri"] for row in identities}, {"https://example.test/item"})
        self.assertEqual(len({row["sha256_prefix"] for row in identities}), 2)
        self.assertNotIn("token=", json.dumps(value))

    async def test_partial_pages_rejected_by_comparison(self):
        page = resources()
        page["nextCursor"] = "PRIVATE_CURSOR"
        inspected = await self.result("inspect_mcp_resource_manifest", resources=json.dumps(page))
        self.assertTrue(inspected["resource_list_partial"])
        self.assertNotIn("PRIVATE_CURSOR", json.dumps(inspected))
        text = await self.call("compare_mcp_resource_manifests", before_resources=json.dumps(page),
                               after_resources=json.dumps(resources()))
        self.assertIn("complete MCP resource lists", text)
        template_page = templates()
        template_page["nextCursor"] = "more"
        text = await self.call("compare_mcp_resource_manifests", before_resources=json.dumps(resources()),
                               after_resources=json.dumps(resources()), before_templates=json.dumps(template_page),
                               after_templates=json.dumps(templates()))
        self.assertIn("complete MCP resource lists", text)
        text = await self.call("compare_mcp_resource_manifests", before_resources=json.dumps(resources()),
                               after_resources=json.dumps(resources()), before_templates=json.dumps(templates()))
        self.assertIn("both template lists", text)

    async def test_prompt_inspection_omits_descriptions_and_shows_requirements(self):
        text = await self.call("inspect_mcp_prompt_manifest", manifest=json.dumps(prompts()))
        self.assertNotIn("PRIVATE_PROMPT_DESCRIPTION", text)
        self.assertNotIn("PRIVATE_ARGUMENT_DESCRIPTION", text)
        value = json.loads(text)
        self.assertEqual(value["prompt_count"], 1)
        self.assertEqual(value["prompts"][0]["required_argument_count"], 1)
        self.assertEqual(value["prompts"][0]["arguments"],
                         [{"name": "code", "required": True}, {"name": "language", "required": False}])

    async def test_prompt_comparison_required_and_presence_changes(self):
        old, new = prompts(), prompts()
        changed = new["prompts"][0]
        changed["description"] = "NEW_PRIVATE_DESCRIPTION"
        changed["arguments"][0]["required"] = False
        changed["arguments"].append({"name": "format", "required": True})
        new["prompts"].append({"name": "summarize", "arguments": []})
        text = await self.call("compare_mcp_prompt_manifests", before=json.dumps(old), after=json.dumps(new))
        self.assertNotIn("PRIVATE_PROMPT_DESCRIPTION", text)
        self.assertNotIn("NEW_PRIVATE_DESCRIPTION", text)
        value = json.loads(text)
        self.assertEqual(value["selected_change_count"], 4)
        self.assertEqual({row["field"] for row in value["changes"]},
                         {"presence", "argument_presence", "required", "description"})
        self.assertFalse(next(row for row in value["changes"] if row["field"] == "required")["after"])

    async def test_prompt_order_does_not_count_as_change(self):
        old, new = prompts(), prompts()
        new["prompts"][0]["arguments"].reverse()
        value = await self.result("compare_mcp_prompt_manifests", before=json.dumps(old), after=json.dumps(new))
        self.assertEqual(value["selected_change_count"], 0)

    async def test_prompt_full_identity_before_display_limit(self):
        prefix = "x" * 250
        old = {"prompts": [{"name": prefix + "a"}]}
        new = {"prompts": [{"name": prefix + "b"}]}
        value = await self.result("compare_mcp_prompt_manifests", before=json.dumps(old), after=json.dumps(new))
        self.assertEqual(value["selected_change_count"], 2)
        self.assertTrue(value["truncated"])

    async def test_prompt_partial_page_and_2026_wrappers(self):
        page = prompts()
        page["nextCursor"] = "PRIVATE_CURSOR"
        inspected = await self.result("inspect_mcp_prompt_manifest", manifest=json.dumps(page))
        self.assertTrue(inspected["partial_list"])
        self.assertNotIn("PRIVATE_CURSOR", json.dumps(inspected))
        text = await self.call("compare_mcp_prompt_manifests", before=json.dumps(page), after=json.dumps(prompts()))
        self.assertIn("complete prompts/list snapshots", text)
        resource_result = {"jsonrpc": "2.0", "id": 1, "result": {"resultType": "complete", **resources()}}
        prompt_result = {"jsonrpc": "2.0", "id": 2, "result": {"resultType": "complete", **prompts()}}
        self.assertEqual((await self.result("inspect_mcp_resource_manifest", resources=json.dumps(resource_result),
                                            protocol_version="2026-07-28"))["resource_count"], 1)
        self.assertEqual((await self.result("inspect_mcp_prompt_manifest", manifest=json.dumps(prompt_result),
                                            protocol_version="2026-07-28"))["prompt_count"], 1)

    async def test_duplicate_and_malformed_catalogs_rejected(self):
        resource = resources()["resources"][0]
        self.assertTrue((await self.call("inspect_mcp_resource_manifest", resources=json.dumps(
            {"resources": [resource, resource]}))).startswith("Error:"))
        prompt = prompts()["prompts"][0]
        self.assertTrue((await self.call("inspect_mcp_prompt_manifest", manifest=json.dumps(
            {"prompts": [prompt, prompt]}))).startswith("Error:"))
        prompt["arguments"][0]["required"] = "yes"
        self.assertTrue((await self.call("inspect_mcp_prompt_manifest", manifest=json.dumps(
            {"prompts": [prompt]}))).startswith("Error:"))
        self.assertTrue((await self.call("inspect_mcp_prompt_manifest", manifest='{"prompts":[],"prompts":[]}')).startswith("Error:"))
        self.assertTrue((await self.call("inspect_mcp_resource_manifest", resources=json.dumps(
            {"resources": [{"uri": "docs://\ud800", "name": "bad"}]}))).startswith("Error:"))

    async def test_input_and_output_limits(self):
        self.assertTrue((await self.call("inspect_mcp_resource_manifest", resources="x" * 200001)).startswith("Error:"))
        self.assertTrue((await self.call("inspect_mcp_prompt_manifest", manifest=json.dumps(prompts()), limit=0)).startswith("Error:"))
        self.assertTrue((await self.call("inspect_mcp_prompt_manifest", manifest=json.dumps(prompts()),
                                         protocol_version="unsupported")).startswith("Error:"))
        many = {"prompts": [{"name": f"prompt-{index}"} for index in range(52)]}
        inspected = await self.result("inspect_mcp_prompt_manifest", manifest=json.dumps(many))
        self.assertEqual(inspected["prompt_count"], 52)
        self.assertEqual(len(inspected["prompts"]), 20)
        self.assertTrue(inspected["truncated"])
