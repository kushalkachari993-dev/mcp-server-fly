import json
import unittest

from mcp.server.fastmcp import FastMCP

from app.tools.event_contract_utils import tool


def asyncapi():
    return {"asyncapi": "3.0.0", "info": {"title": "Orders", "version": "1"},
            "defaultContentType": "application/json",
            "channels": {"orders": {"address": "orders.{id}", "messages": {
                "created": {"$ref": "#/components/messages/Created"}}}},
            "operations": {"publish": {"action": "send", "channel": {"$ref": "#/channels/orders"},
                                       "messages": [{"$ref": "#/channels/orders/messages/created"}]}},
            "components": {"messages": {"Created": {"payload": {"type": "object", "required": ["orderId"],
                        "properties": {"orderId": {"$ref": "#/components/schemas/Id"}}},
                        "examples": [{"payload": {"orderId": "EXAMPLE_SECRET"}}]}},
                           "schemas": {"Id": {"type": "integer"}}}}


def cloudevent(**changes):
    return {"specversion": "1.0", "id": "PRIVATE_ID", "source": "/orders", "type": "com.example.created",
            "data": {"secret": "PAYLOAD_SECRET"}, **changes}


class EventContractToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("event-contract-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        blocks = result[0] if isinstance(result, tuple) else result
        return "\n".join(block.text for block in blocks if block.type == "text")

    async def result(self, name, **arguments):
        return json.loads(await self.call(name, **arguments))

    async def test_inspect_selected_channels_messages_operations_without_examples(self):
        text = await self.call("inspect_asyncapi_document", content=json.dumps(asyncapi()))
        self.assertNotIn("EXAMPLE_SECRET", text)
        value = json.loads(text)
        self.assertEqual(value["channel_count"], 1)
        self.assertEqual(value["operation_count"], 1)
        self.assertEqual(value["message_count"], 1)
        self.assertEqual(value["channels"][0]["messages"][0]["payload"]["type"], "object")
        self.assertEqual(value["operations"][0]["message_ids"], ["created"])
        self.assertEqual(value["reference_status"]["resolved_local"], 4)

    async def test_yaml_input_and_duplicate_key_rejected(self):
        content = """asyncapi: 3.0.0
info: {title: Orders, version: '1'}
channels:
  orders:
    address: orders
    messages:
      created:
        payload: {type: object}
operations:
  publish:
    action: send
    channel: {$ref: '#/channels/orders'}
"""
        result = await self.result("inspect_asyncapi_document", content=content)
        self.assertEqual(result["channels"][0]["messages"][0]["payload"]["type"], "object")
        bad = content.replace("    address: orders", "    address: orders\n    address: duplicate")
        self.assertTrue((await self.call("inspect_asyncapi_document", content=bad)).startswith("Error:"))

    async def test_compare_address_action_content_type_and_payload_shape(self):
        old = asyncapi()
        new = asyncapi()
        new["channels"]["orders"]["address"] = "orders.v2"
        new["operations"]["publish"]["action"] = "receive"
        new["components"]["messages"]["Created"]["contentType"] = "application/problem+json"
        new["components"]["messages"]["Created"]["payload"]["required"].append("status")
        result = await self.result("compare_asyncapi_contracts", before=json.dumps(old), after=json.dumps(new))
        self.assertTrue({"address", "action", "content_type", "payload_shape"} <=
                        {change["field"] for change in result["changes"]})
        self.assertEqual(next(change for change in result["changes"] if change["field"] == "payload_shape")
                         ["details"]["required_added"], ["status"])
        self.assertTrue(result["selected_reference_coverage_complete"])

    async def test_compare_full_identity_before_display_truncation(self):
        old = asyncapi()
        new = asyncapi()
        prefix = "x" * 1000
        old["channels"] = {prefix + "A": {"messages": {}}}
        new["channels"] = {prefix + "B": {"messages": {}}}
        old["operations"] = new["operations"] = {}
        result = await self.result("compare_asyncapi_contracts", before=json.dumps(old), after=json.dumps(new))
        self.assertEqual(result["selected_change_count"], 2)
        self.assertTrue(result["truncated"])

    async def test_unresolved_references_remain_uncertain(self):
        old = asyncapi()
        new = asyncapi()
        old["channels"]["orders"]["messages"]["created"] = {"$ref": "https://example.com/message"}
        result = await self.result("compare_asyncapi_contracts", before=json.dumps(old), after=json.dumps(new))
        self.assertFalse(result["selected_reference_coverage_complete"])
        self.assertGreater(result["uncertain_selected_record_count"], 0)
        self.assertEqual(result["reference_status"]["before"]["external_or_invalid"], 1)

    async def test_unsupported_added_payload_keeps_coverage_uncertain(self):
        old = asyncapi()
        new = asyncapi()
        new["channels"]["extra"] = {"messages": {"binary": {"contentType": "application/json",
            "payload": {"schemaFormat": "application/vnd.apache.avro+json;version=1.9.0", "schema": {"type": "record"}}}}}
        result = await self.result("compare_asyncapi_contracts", before=json.dumps(old), after=json.dumps(new))
        self.assertFalse(result["selected_reference_coverage_complete"])
        self.assertEqual(result["uncertain_selected_record_count"], 1)

    async def test_known_to_unsupported_payload_change_is_uncertain(self):
        old = asyncapi()
        new = asyncapi()
        new["components"]["messages"]["Created"]["payload"] = {
            "schemaFormat": "application/vnd.apache.avro+json;version=1.9.0", "schema": {"type": "record"}}
        result = await self.result("compare_asyncapi_contracts", before=json.dumps(old), after=json.dumps(new))
        change = next(row for row in result["changes"] if row["field"] == "payload_shape")
        self.assertEqual(change["certainty"], "uncertain")

    async def test_operation_message_ref_reordering_is_ignored(self):
        old = asyncapi()
        new = asyncapi()
        for doc in (old, new):
            doc["channels"]["orders"]["messages"]["updated"] = {"payload": {"type": "object"}}
        first = {"$ref": "#/channels/orders/messages/created"}
        second = {"$ref": "#/channels/orders/messages/updated"}
        old["operations"]["publish"]["messages"] = [first, second]
        new["operations"]["publish"]["messages"] = [second, first]
        result = await self.result("compare_asyncapi_contracts", before=json.dumps(old), after=json.dumps(new))
        self.assertEqual(result["selected_change_count"], 0)

    async def test_validate_default_asyncapi_schema_and_local_component_ref(self):
        spec = json.dumps(asyncapi())
        args = {"spec": spec, "channel_id": "orders", "message_id": "created"}
        self.assertTrue((await self.result("validate_asyncapi_json_message", payload='{"orderId": 1}', **args))["valid"])
        text = await self.call("validate_asyncapi_json_message", payload='{"orderId": "BODY_SECRET"}', **args)
        self.assertNotIn("BODY_SECRET", text)
        value = json.loads(text)
        self.assertFalse(value["valid"])
        self.assertEqual(value["errors"][0]["path"], "/orderId")

    async def test_validate_explicit_draft7_and_reject_avro(self):
        doc = asyncapi()
        payload = doc["components"]["messages"]["Created"]["payload"]
        doc["components"]["messages"]["Created"]["payload"] = {
            "schemaFormat": "application/schema+json;version=draft-07", "schema": payload}
        doc["components"]["schemas"]["Id"] = {
            "schemaFormat": "application/schema+json;version=draft-07", "schema": {"type": "integer"}}
        args = {"spec": json.dumps(doc), "channel_id": "orders", "message_id": "created", "payload": '{"orderId": 2}'}
        result = await self.result("validate_asyncapi_json_message", **args)
        self.assertTrue(result["valid"])
        self.assertEqual(result["schema_format"], "json_schema_draft7")
        doc["components"]["messages"]["Created"]["payload"]["schemaFormat"] = "application/vnd.apache.avro+json;version=1.9.0"
        args["spec"] = json.dumps(doc)
        self.assertTrue((await self.call("validate_asyncapi_json_message", **args)).startswith("Error:"))

    async def test_multiformat_wrapper_without_schema_format_uses_asyncapi_default(self):
        doc = asyncapi()
        wrapped = doc["components"]["messages"]["Created"]["payload"]
        doc["components"]["messages"]["Created"]["payload"] = {"schema": wrapped}
        args = {"spec": json.dumps(doc), "channel_id": "orders", "message_id": "created"}
        result = await self.result("validate_asyncapi_json_message", payload='{"orderId": 7}', **args)
        self.assertTrue(result["valid"])
        self.assertEqual(result["schema_format"], "asyncapi_schema")
        self.assertFalse((await self.result("validate_asyncapi_json_message", payload='{}', **args))["valid"])

    async def test_validation_rejects_external_ref_missing_json_type_and_duplicates(self):
        doc = asyncapi()
        args = {"channel_id": "orders", "message_id": "created", "payload": '{"orderId": 1}'}
        doc["components"]["schemas"]["Id"] = {"$ref": "https://example.com/id"}
        self.assertIn("Only resolvable local", await self.call("validate_asyncapi_json_message", spec=json.dumps(doc), **args))
        doc = asyncapi()
        doc["defaultContentType"] = "application/xml"
        self.assertIn("JSON contentType", await self.call("validate_asyncapi_json_message", spec=json.dumps(doc), **args))
        doc = asyncapi()
        args["payload"] = '{"orderId":1,"orderId":2}'
        self.assertTrue((await self.call("validate_asyncapi_json_message", spec=json.dumps(doc), **args)).startswith("Error:"))

    async def test_cloudevent_valid_envelope_omits_values(self):
        event = cloudevent(time="2025-01-02T03:04:05Z", subject=None, traceid="PRIVATE_TRACE")
        text = await self.call("validate_cloudevents_json", content=json.dumps(event))
        for secret in ("PRIVATE_ID", "PAYLOAD_SECRET", "PRIVATE_TRACE"):
            self.assertNotIn(secret, text)
        result = json.loads(text)
        self.assertTrue(result["valid"])
        self.assertEqual(result["payload_kind"], "json")
        self.assertEqual(result["extension_attribute_count"], 1)

    async def test_cloudevent_base64_and_conflict(self):
        event = cloudevent(data_base64="YWJj", datacontenttype="application/octet-stream")
        event.pop("data")
        self.assertTrue((await self.result("validate_cloudevents_json", content=json.dumps(event)))["valid"])
        event["data"] = "duplicate"
        result = await self.result("validate_cloudevents_json", content=json.dumps(event))
        self.assertIn("data_and_data_base64_conflict", {row["code"] for row in result["issues"]})
        event.pop("data")
        event["data_base64"] = "!not-base64!"
        result = await self.result("validate_cloudevents_json", content=json.dumps(event))
        self.assertIn("invalid_base64", {row["code"] for row in result["issues"]})

    async def test_cloudevent_required_optional_and_extension_errors(self):
        event = cloudevent(specversion="2.0", source="not a URI", time="yesterday", datacontenttype="bad",
                           BadExtension={"secret": "NEVER_ECHO"})
        event.pop("id")
        text = await self.call("validate_cloudevents_json", content=json.dumps(event))
        self.assertNotIn("NEVER_ECHO", text)
        result = json.loads(text)
        self.assertFalse(result["valid"])
        codes = {row["code"] for row in result["issues"]}
        self.assertTrue({"missing_or_invalid_required_attribute", "unsupported_version", "invalid_uri_reference",
                         "invalid_timestamp", "invalid_media_type", "invalid_attribute_name", "invalid_attribute_type"} <= codes)

    async def test_cloudevent_non_json_data_and_integer_range(self):
        event = cloudevent(datacontenttype="application/xml", extensioncount=2147483648)
        result = await self.result("validate_cloudevents_json", content=json.dumps(event))
        self.assertTrue({"non_json_content_requires_string", "integer_out_of_range"} <=
                        {row["code"] for row in result["issues"]})

    async def test_limits_versions_and_batches(self):
        doc = asyncapi()
        doc["asyncapi"] = "2.6.0"
        self.assertTrue((await self.call("inspect_asyncapi_document", content=json.dumps(doc))).startswith("Error:"))
        self.assertTrue((await self.call("validate_cloudevents_json", content="[]")).startswith("Error:"))
        self.assertTrue((await self.call("inspect_asyncapi_document", content="x" * 200001)).startswith("Error:"))
        self.assertTrue((await self.call("validate_cloudevents_json", content=json.dumps(cloudevent()), limit=0)).startswith("Error:"))
