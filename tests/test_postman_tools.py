import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.postman_utils import service, tool


SCHEMA_URL = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"


def collection(items=(), **fields):
    return json.dumps({"info": {"name": "demo", "schema": SCHEMA_URL}, "item": list(items), **fields})


def request(name="health", method="GET", url="https://example.com/health?QUERY_SECRET", **fields):
    return {"name": name, "request": {"method": method, "url": url, **fields}}


class PostmanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("postman-tests")
        tool.register(self.mcp)

    async def call(self, content, **arguments):
        result = await self.mcp.call_tool("inspect_postman_collection", {"content": content, **arguments})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def inspect(self, content, **arguments):
        return json.loads(await self.call(content, **arguments))

    async def test_folder_structure_requests_methods_and_auth_inheritance(self):
        data = collection([request(), {"name": "folder", "auth": {"type": "basic"}, "item": [
            request("post", "POST"), request("anon", auth={"type": "noauth"}),
            {"name": "child", "item": [request("inherited", auth=None)]}]}], auth={"type": "bearer"})
        result = await self.inspect(data)
        self.assertEqual(result["item_count"], 6)
        self.assertEqual(result["folder_count"], 2)
        self.assertEqual(result["request_count"], 4)
        self.assertEqual(result["method_counts"], {"GET": 3, "POST": 1})
        self.assertEqual(result["effective_declared_auth_counts"], {"basic": 2, "bearer": 1, "noauth": 1})
        self.assertEqual(result["requests"][3]["folder_path"], [0, 1])
        self.assertEqual(result["requests"][3]["auth_source"], "folder")
        self.assertEqual(result["folders"][1]["parent_folder_index"], 0)

    async def test_noauth_stops_folder_inheritance_and_null_inherits(self):
        data = collection([{"name": "folder", "auth": {"type": "noauth"}, "item": [request(auth=None)]}], auth={"type": "basic"})
        result = await self.inspect(data)
        self.assertEqual(result["requests"][0]["declared_auth_type"], None)
        self.assertEqual(result["requests"][0]["inherited_auth_type"], "noauth")
        self.assertEqual(result["requests"][0]["effective_declared_auth_type"], "noauth")
        self.assertEqual(result["requests"][0]["auth_source"], "folder")

    async def test_missing_auth_is_unknown_not_noauth(self):
        result = await self.inspect(collection([request()]))
        self.assertIsNone(result["collection_auth_type"])
        self.assertIsNone(result["requests"][0]["effective_declared_auth_type"])
        self.assertEqual(result["effective_declared_auth_counts"], {"unknown": 1})

    async def test_credential_headers_bodies_variables_and_scripts_omitted(self):
        item = request(url="https://user:PASSWORD_SECRET@example.com:8443/path?QUERY_SECRET#FRAGMENT_SECRET",
                       auth={"type": "apikey", "apikey": [{"key": "value", "value": "AUTH_SECRET"}]},
                       header="HEADER_SECRET", body={"raw": "BODY_SECRET"},
                       proxy="PROXY_SECRET", certificate="CERT_SECRET", description="DESCRIPTION_SECRET")
        item.update(event=[{"listen": "test", "script": {"exec": ["SCRIPT_SECRET"]}}],
                    variable=[{"key": "VARIABLE_KEY_SECRET", "value": "VARIABLE_SECRET"}],
                    response=[{"body": "EXAMPLE_SECRET", "originalRequest": "ORIGINAL_REQUEST_SECRET"}])
        text = await self.call(collection([item], variable=[{"key": "COLLECTION_KEY_SECRET", "value": "COLLECTION_SECRET"}],
                                          event=[{"listen": "prerequest", "script": {"exec": ["COLLECTION_SCRIPT_SECRET"]}}]))
        for secret in ("PASSWORD_SECRET", "QUERY_SECRET", "FRAGMENT_SECRET", "AUTH_SECRET", "HEADER_SECRET", "BODY_SECRET",
                       "PROXY_SECRET", "CERT_SECRET", "DESCRIPTION_SECRET", "SCRIPT_SECRET", "VARIABLE_KEY_SECRET", "VARIABLE_SECRET",
                       "EXAMPLE_SECRET", "ORIGINAL_REQUEST_SECRET", "COLLECTION_KEY_SECRET", "COLLECTION_SECRET", "COLLECTION_SCRIPT_SECRET"):
            self.assertNotIn(secret, text)
        target = json.loads(text)["requests"][0]["target"]
        self.assertEqual(target, {"status": "http", "source": "string", "scheme": "https", "host": "example.com", "port": 8443, "path": "/path"})

    async def test_string_requests_use_get_and_object_methods_stay_missing(self):
        result = await self.inspect(collection([{"request": "https://example.com/path"}, {"request": {}}, request(method="unknown")]))
        self.assertEqual(result["method_counts"], {"GET": 1, "unknown": 1})
        self.assertEqual(result["missing_method_count"], 1)
        self.assertIsNone(result["requests"][1]["method"])
        self.assertEqual(result["requests"][1]["target"]["status"], "missing")

    async def test_url_object_raw_used_without_reconstructing_components(self):
        result = await self.inspect(collection([request(url={"raw": "https://example.com/path?RAW_SECRET", "host": ["COMPONENT_SECRET"], "path": ["OTHER_SECRET"]})]))
        self.assertEqual(result["requests"][0]["target"]["source"], "raw")
        self.assertEqual(result["requests"][0]["target"]["path"], "/path")
        self.assertNotIn("COMPONENT_SECRET", json.dumps(result))
        self.assertNotIn("OTHER_SECRET", json.dumps(result))

    async def test_unresolved_templates_and_components_only_have_no_target_text(self):
        result = await self.inspect(collection([request(url="{{BASE_SECRET}}/path?KEY_SECRET"),
                                                request(url={"host": ["COMPONENT_SECRET"], "path": ["PATH_SECRET"]}),
                                                request(url="https://example.com/path?token={{VARIABLE_SECRET}}")]))
        self.assertEqual(result["target_status_counts"], {"components_only": 1, "unresolved_template": 2})
        text = json.dumps(result)
        for secret in ("BASE_SECRET", "KEY_SECRET", "COMPONENT_SECRET", "PATH_SECRET", "VARIABLE_SECRET"):
            self.assertNotIn(secret, text)
        self.assertIsNone(result["requests"][0]["target"]["host"])

    async def test_relative_file_data_and_other_urls_omitted(self):
        for url in ("/PRIVATE_PATH", "file:///PRIVATE_PATH", "data:PRIVATE_PAYLOAD", "ftp://PRIVATE_HOST/path"):
            text = await self.call(collection([request(url=url)]))
            self.assertEqual(json.loads(text)["requests"][0]["target"]["status"], "unsupported")
            self.assertNotIn("PRIVATE", text)

    async def test_supported_schema_urls_and_all_auth_types(self):
        for schema in service._SCHEMAS:
            data = json.loads(collection())
            data["info"]["schema"] = schema
            self.assertEqual(service.inspect_collection(json.dumps(data), 1)["version"], "2.1.0")
        result = await self.inspect(collection([request(auth={"type": kind}) for kind in sorted(service._AUTH_TYPES)]))
        self.assertEqual(set(result["effective_declared_auth_counts"]), service._AUTH_TYPES)

    async def test_http_targets_are_offline_even_for_private_hosts(self):
        result = await self.inspect(collection([request(url="https://127.0.0.1/path"), request(url="http://localhost/path")]))
        self.assertEqual(result["target_status_counts"], {"http": 2})
        self.assertEqual(result["requests"][1]["target"]["host"], "localhost")

    async def test_paths_and_names_truncate_output_not_counts(self):
        result = await self.inspect(collection([request(name="N" * 1001, url="https://example.com/" + "p" * 1001)]))
        self.assertEqual(len(result["requests"][0]["name"]), 1000)
        self.assertEqual(len(result["requests"][0]["target"]["path"]), 1000)
        self.assertTrue(result["truncated"])

    async def test_limits_still_validate_all_later_records(self):
        result = await self.inspect(collection([request(str(number)) for number in range(60)]), limit=1)
        self.assertEqual(result["request_count"], 60)
        self.assertEqual(result["method_counts"], {"GET": 60})
        self.assertEqual(len(result["requests"]), 1)
        self.assertTrue(result["truncated"])
        text = await self.call(collection([request(), request(auth={"type": "UNKNOWN_SECRET"})]), limit=1)
        self.assertTrue(text.startswith("Error:"))
        self.assertNotIn("UNKNOWN_SECRET", text)

    async def test_empty_and_unnamed_folders_and_requests_are_preserved(self):
        result = await self.inspect(collection([{"item": []}, {"request": "https://example.com"}]))
        self.assertEqual(result["folder_count"], 1)
        self.assertIsNone(result["folders"][0]["name"])
        self.assertIsNone(result["requests"][0]["name"])
        self.assertFalse((await self.inspect(collection()))["truncated"])

    async def test_schema_wrapper_versions_and_required_info_rejected(self):
        for content in ('{}', '{"collection":{}}', '{"info":{},"item":[]}',
                        json.dumps({"info": {"name": "x", "schema": SCHEMA_URL.replace("2.1.0", "2.0.0")}, "item": []}),
                        json.dumps({"info": {"name": 1, "schema": SCHEMA_URL}, "item": []})):
            self.assertTrue((await self.call(content)).startswith("Error:"))

    async def test_ambiguous_items_bad_methods_urls_and_auth_rejected(self):
        for item in ({"request": {}, "item": []}, {}, {"request": None}, {"request": 1}, {"item": {}},
                     request(method="GET\nPRIVATE_SECRET"), request(method=True), request(url={"raw": None}),
                     request(url="https://example.com:bad/path"), request(url="https://example.com/\nPRIVATE_SECRET"),
                     request(auth={"type": "jwt"}), request(auth="AUTH_SECRET")):
            text = await self.call(collection([item]))
            self.assertTrue(text.startswith("Error:"), str(item))
            self.assertNotIn("PRIVATE_SECRET", text)
            self.assertNotIn("AUTH_SECRET", text)

    async def test_json_duplicates_nonfinite_depth_nodes_and_total_item_bounds(self):
        for content in ('{"info":{},"info":"PRIVATE_SECRET"}', collection([], extra=float("nan")),
                        collection([request(url="x" * 10001)]), collection([request() for _ in range(1001)]),
                        collection([], extra=[0] * 20001)):
            text = await self.call(content)
            self.assertTrue(text.startswith("Error:"))
            self.assertNotIn("PRIVATE_SECRET", text)
        nested = {"request": {}}
        for _ in range(30):
            nested = {"item": [nested]}
        self.assertTrue((await self.call(collection([nested]))).startswith("Error:"))
        folders = [{"item": [request() for _ in range(500)]} for _ in range(2)]
        self.assertTrue((await self.call(collection(folders))).startswith("Error:"))

    async def test_direct_input_and_limit_bounds(self):
        for content in (None, {}, "x" * 200001):
            with self.assertRaises(ValueError):
                service.inspect_collection(content, 1)
        for limit in (True, 0, 51, 1.5, "1"):
            with self.assertRaises(ValueError):
                service.inspect_collection(collection(), limit)

    async def test_no_network_file_dns_commands_or_eval(self):
        with patch("builtins.open", side_effect=AssertionError("file")), patch("requests.get", side_effect=AssertionError("network")), \
                patch("socket.getaddrinfo", side_effect=AssertionError("DNS")), patch("subprocess.run", side_effect=AssertionError("command")), \
                patch("builtins.eval", side_effect=AssertionError("script")):
            self.assertEqual(service.inspect_collection(collection([request()]), 1)["request_count"], 1)

    async def test_output_cap_and_smaller_limit_recovery(self):
        long = "x" * 900
        content = collection([request(name=f"{long}{number}", url=f"https://example.com/{long}{number}") for number in range(60)])
        self.assertTrue((await self.call(content, limit=50)).startswith("Error: Report summary exceeds 100000"))
        self.assertTrue((await self.inspect(content, limit=1))["truncated"])


if __name__ == "__main__":
    unittest.main()
