import json
import unittest

from mcp.server.fastmcp import FastMCP

from app.tools.api_contract_utils import tool


POSTMAN_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"


def spec(version="3.1.0", *, required=False, method="post", path="/widgets"):
    return {"openapi": version, "info": {"title": "Widget API", "version": "1"},
            "paths": {path: {method: {
                "parameters": [{"name": "trace", "in": "header", "required": required,
                                "schema": {"type": "string"}}],
                "requestBody": {"required": required, "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/Widget"}}}},
                "responses": {"200": {"description": "ok", "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/Widget"}}}}},
                "security": [{"bearerAuth": []}]
            }}}, "components": {"schemas": {"Widget": {"type": "object", "required": ["id"],
                                                        "properties": {"id": {"type": "integer"}}}}}}


def collection(items, **extra):
    return json.dumps({"info": {"name": "demo", "schema": POSTMAN_SCHEMA}, "item": items, **extra})


def request(name="lookup", method="GET", url="https://example.com/widgets?token=SECRET", **extra):
    return {"name": name, "request": {"method": method, "url": url, **extra}}


class ContractToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("contract-tools-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        blocks = result[0] if isinstance(result, tuple) else result
        return "\n".join(block.text for block in blocks if block.type == "text")

    async def result(self, name, **arguments):
        return json.loads(await self.call(name, **arguments))

    async def test_inspect_json_selected_contract_and_refs(self):
        value = await self.result("inspect_openapi_document", content=json.dumps(spec()))
        self.assertEqual(value["operation_count"], 1)
        self.assertEqual(value["reference_status"]["resolved_local"], 2)
        operation = value["operations"][0]
        self.assertEqual(operation["path"], "/widgets")
        self.assertEqual(operation["parameters"][0]["name"], "trace")
        self.assertEqual(operation["request_body"]["media"][0]["schema"]["type"], "object")
        self.assertEqual(operation["responses"][0]["status"], "200")
        self.assertEqual(operation["security"][0]["schemes"][0]["name"], "bearerAuth")

    async def test_yaml_unquoted_response_status_and_duplicate_rejected(self):
        yaml_spec = """openapi: 3.1.0
info:
  title: Widgets
  version: '1'
paths:
  /widgets:
    get:
      responses:
        200:
          description: ok
"""
        value = await self.result("inspect_openapi_document", content=yaml_spec)
        self.assertEqual(value["operations"][0]["responses"][0]["status"], "200")
        bad = yaml_spec.replace("          description: ok", "          description: ok\n          description: nope")
        self.assertTrue((await self.call("inspect_openapi_document", content=bad)).startswith("Error:"))

    async def test_comparison_required_media_response_and_security(self):
        before = spec()
        after = spec(required=True)
        after["paths"]["/widgets"]["post"]["responses"]["201"] = {"description": "created"}
        after["paths"]["/widgets"]["post"]["security"] = [{"oauth": ["write"]}]
        value = await self.result("compare_openapi_contracts", before=json.dumps(before), after=json.dumps(after))
        fields = {row["field"] for row in value["changes"]}
        self.assertTrue({"parameter_required", "request_body_required", "response_status", "security_requirements"} <= fields)
        self.assertTrue(value["comparison_complete"])
        security = next(row for row in value["changes"] if row["field"] == "security_requirements")
        self.assertEqual(security["before"][0]["schemes"][0]["name"], "bearerAuth")
        self.assertEqual(security["after"][0]["schemes"][0]["name"], "oauth")

    async def test_schema_shape_change_reports_selected_detail(self):
        before = spec()
        after = spec()
        after["components"]["schemas"]["Widget"]["properties"]["id"]["type"] = "string"
        value = await self.result("compare_openapi_contracts", before=json.dumps(before), after=json.dumps(after))
        shape = next(row for row in value["changes"] if row["field"] == "request_schema_shape")
        self.assertEqual(shape["details"]["property_type_changes"][0]["name"], "id")
        self.assertEqual(shape["details"]["property_type_changes"][0]["before_type"], "integer")
        self.assertEqual(shape["details"]["property_type_changes"][0]["after_type"], "string")

    async def test_cross_dialect_comparison_has_no_complete_coverage(self):
        before = spec(version="3.0.3")
        after = spec(version="3.1.0")
        value = await self.result("compare_openapi_contracts", before=json.dumps(before), after=json.dumps(after))
        self.assertFalse(value["schema_dialect_comparable"])
        self.assertFalse(value["comparison_complete"])

    async def test_comparison_full_path_identity_before_output_truncation(self):
        prefix = "/" + "a" * 1000
        before = spec(path=prefix + "x")
        after = spec(path=prefix + "y")
        value = await self.result("compare_openapi_contracts", before=json.dumps(before), after=json.dumps(after))
        self.assertEqual(value["selected_change_count"], 2)
        self.assertTrue(value["truncated"])

    async def test_unresolved_reference_keeps_comparison_uncertain(self):
        before = spec()
        before["paths"]["/mystery"] = {"$ref": "https://example.com/path-item"}
        after = spec()
        value = await self.result("compare_openapi_contracts", before=json.dumps(before), after=json.dumps(after))
        self.assertFalse(value["comparison_complete"])
        self.assertEqual(value["unknown_path_counts"]["before"], 1)
        self.assertEqual(value["reference_status"]["before"]["external_or_invalid"], 1)

    async def test_postman_method_auth_and_sanitized_target(self):
        before = collection([{"name": "API", "item": [request(auth={"type": "bearer"})]}])
        after = collection([{"name": "API", "item": [request(method="POST", url="https://example.com/new?token=OTHER_SECRET", auth={"type": "noauth"})]}])
        text = await self.call("compare_postman_collections", before=before, after=after)
        for secret in ("SECRET", "OTHER_SECRET"):
            self.assertNotIn(secret, text)
        value = json.loads(text)
        self.assertEqual(value["matching"]["requests"]["matched"], 1)
        self.assertTrue({"method", "declared_auth_type", "effective_auth_type", "sanitized_target"} <=
                        {row["field"] for row in value["changes"]})

    async def test_postman_duplicate_names_are_ambiguous(self):
        value = await self.result("compare_postman_collections",
                                  before=collection([request(), request()]), after=collection([request()]))
        self.assertEqual(value["matching"]["requests"]["ambiguous"], 1)
        self.assertEqual(value["matching"]["requests"]["matched"], 0)

    async def test_postman_unresolved_templates_not_returned(self):
        before = collection([request(url="{{SECRET_BASE}}/widgets?SECRET_TOKEN")])
        after = collection([request(url="{{OTHER_SECRET_BASE}}/widgets")])
        text = await self.call("compare_postman_collections", before=before, after=after)
        self.assertNotIn("SECRET_BASE", text)
        self.assertNotIn("SECRET_TOKEN", text)
        self.assertEqual(json.loads(text)["uncertain_target_counts"], {"before": 1, "after": 1})

    async def test_postman_full_target_path_compared_before_shortening(self):
        prefix = "https://example.com/" + "a" * 1000
        before = collection([request(url=prefix + "x?secret=HIDDEN")])
        after = collection([request(url=prefix + "y?secret=HIDDEN")])
        value = await self.result("compare_postman_collections", before=before, after=after)
        self.assertEqual(value["selected_change_count"], 1)
        self.assertEqual(value["changes"][0]["field"], "sanitized_target")
        self.assertTrue(value["truncated"])

    async def test_validate_request_and_response_json_body(self):
        document = json.dumps(spec())
        for direction in ("request", "response"):
            valid = await self.result("validate_openapi_json_body", spec=document, path="/widgets", method="POST",
                                      direction=direction, body='{"id": 3}')
            self.assertTrue(valid["valid"])
            invalid = await self.result("validate_openapi_json_body", spec=document, path="/widgets", method="POST",
                                        direction=direction, body='{"id": "BODY_SECRET"}')
            self.assertFalse(invalid["valid"])
            self.assertNotIn("BODY_SECRET", json.dumps(invalid))
            self.assertEqual(invalid["errors"][0]["path"], "/id")

    async def test_validation_rejects_30_external_refs_and_unsupported_dialect(self):
        document = spec(version="3.0.3")
        args = {"path": "/widgets", "method": "POST", "direction": "request", "body": '{"id": 3}'}
        self.assertIn("3.1", await self.call("validate_openapi_json_body", spec=json.dumps(document), **args))
        document = spec()
        document["components"]["schemas"]["Widget"]["properties"]["id"] = {"$ref": "https://example.com/secret-schema"}
        self.assertIn("Only resolvable local", await self.call("validate_openapi_json_body", spec=json.dumps(document), **args))
        document = spec()
        document["jsonSchemaDialect"] = "https://example.com/custom"
        self.assertIn("Custom", await self.call("validate_openapi_json_body", spec=json.dumps(document), **args))

    async def test_validation_rejects_duplicate_body_keys_and_missing_media(self):
        document = json.dumps(spec())
        args = {"spec": document, "path": "/widgets", "method": "POST", "direction": "request"}
        self.assertTrue((await self.call("validate_openapi_json_body", body='{"id":1,"id":2}', **args)).startswith("Error:"))
        self.assertIn("not declared", await self.call("validate_openapi_json_body", body='{}', media_type="application/problem+json", **args))

    async def test_validation_selects_response_range_before_default(self):
        document = spec()
        responses = document["paths"]["/widgets"]["post"]["responses"]
        responses.pop("200")
        responses["2XX"] = {"content": {"application/json": {"schema": {"type": "integer"}}}}
        responses["default"] = {"content": {"application/json": {"schema": {"type": "string"}}}}
        args = {"spec": json.dumps(document), "path": "/widgets", "method": "POST", "direction": "response",
                "body": "3", "status": "201"}
        self.assertTrue((await self.result("validate_openapi_json_body", **args))["valid"])
        args["status"] = "404"
        self.assertFalse((await self.result("validate_openapi_json_body", **args))["valid"])

    async def test_property_named_readonly_and_example_ref_are_not_keywords(self):
        document = spec()
        schema = document["components"]["schemas"]["Widget"]
        schema["properties"]["readOnly"] = {"type": "string", "example": {"$ref": "not-a-schema-ref"}}
        args = {"spec": json.dumps(document), "path": "/widgets", "method": "POST", "direction": "request",
                "body": '{"id": 1, "readOnly": "ok"}'}
        self.assertTrue((await self.result("validate_openapi_json_body", **args))["valid"])
        schema["readOnly"] = True
        args["spec"] = json.dumps(document)
        self.assertIn("unsupported", await self.call("validate_openapi_json_body", **args))

    async def test_invalid_limit_and_oversized_inputs(self):
        document = json.dumps(spec())
        self.assertTrue((await self.call("inspect_openapi_document", content=document, limit=0)).startswith("Error:"))
        self.assertTrue((await self.call("compare_openapi_contracts", before=document, after="x" * 200001)).startswith("Error:"))
