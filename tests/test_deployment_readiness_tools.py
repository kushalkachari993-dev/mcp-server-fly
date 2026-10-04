import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.deployment_utils import service, tool


def pod(name="app", **spec):
    return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name},
            "spec": {"containers": [{"name": "web", "image": "nginx:stable"}], **spec}}


class DeploymentReadinessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("deployment-readiness-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_fly_http_service_checks_and_machine_settings(self):
        content = '''app = "demo"
primary_region = "bom"
[env]
TOKEN = "hidden-environment"
[processes]
app = "echo hidden-process-command"
[build]
dockerfile = "Dockerfile"
build-target = "runtime"
[build.args]
TOKEN = "hidden-build-argument"
[deploy]
strategy = "rolling"
release_command = "echo hidden-release-command"
[http_service]
internal_port = 8000
force_https = true
auto_stop_machines = "stop"
auto_start_machines = true
min_machines_running = 0
processes = ["app"]
[[http_service.checks]]
method = "GET"
path = "/health"
interval = "30s"
timeout = "5s"
[http_service.checks.headers]
Authorization = "hidden-header-value"
[[vm]]
size = "shared-cpu-1x"
memory = "256mb"
[[mounts]]
source = "data"
destination = "/data"
'''
        output = await self.call("inspect_fly_config", content=content)
        data = json.loads(output)
        self.assertEqual(data["app"], "demo")
        self.assertEqual(data["environment_names"], ["TOKEN"])
        self.assertEqual(data["process_names"], ["app"])
        self.assertEqual(data["services"][0]["internal_port"], 8000)
        self.assertEqual(data["services"][0]["implicit_http_ports"], [80, 443])
        self.assertEqual(data["services"][0]["checks"][0]["path"], "/health")
        self.assertEqual(data["services"][0]["checks"][0]["header_names"], ["Authorization"])
        self.assertEqual(data["machines"][0]["memory"], "256mb")
        self.assertEqual(data["build"]["build-target"], "runtime")
        self.assertEqual(data["build"]["argument_names"], ["TOKEN"])
        self.assertTrue(data["deploy"]["release_command_declared"])
        self.assertEqual(data["mounts"][0]["destination"], "/data")
        for hidden in ("hidden-environment", "hidden-process-command", "hidden-build-argument", "hidden-release-command", "hidden-header-value"):
            self.assertNotIn(hidden, output)

    async def test_fly_additional_services_port_ranges_and_named_checks(self):
        content = '''app = "demo"
[[services]]
internal_port = 9000
protocol = "tcp"
[[services.ports]]
start_port = 9000
end_port = 9005
handlers = ["tls"]
[[services.http_checks]]
path = "/health"
interval = 10000
[[services.tcp_checks]]
timeout = 2000
[checks.alive]
type = "http"
port = 9000
path = "/"
'''
        data = json.loads(await self.call("inspect_fly_config", content=content))
        self.assertEqual(data["services"][0]["ports"][0]["end_port"], 9005)
        self.assertEqual(data["services"][0]["checks"][0]["interval"], 10000)
        self.assertEqual(data["checks"][0]["name"], "alive")
        self.assertEqual(data["checks"][0]["port"], 9000)
        self.assertIsNone(data["services"][0]["auto_stop_machines"])
        self.assertIsNone(data["services"][0]["auto_start_machines"])

    async def test_fly_legacy_autostop_warnings_and_no_defaults(self):
        data = json.loads(await self.call("inspect_fly_config", content='app = "demo"\n[http_service]\nauto_stop_machines = true\nauto_start_machines = false'))
        self.assertEqual(len(data["warnings"]), 2)
        self.assertIs(data["services"][0]["auto_stop_machines"], True)
        minimal = json.loads(await self.call("inspect_fly_config", content='app = "demo"'))
        self.assertEqual(minimal["services"], [])
        self.assertEqual(minimal["machines"], [])
        self.assertIsNone(minimal["deploy"]["strategy"])
        self.assertIsNone(minimal["primary_region"])

    async def test_fly_reserved_names_process_and_concurrency_warnings(self):
        content = '''[env]
FLY_TEST = "hidden"
[processes]
app = "hidden"
[http_service]
auto_stop_machines = "off"
processes = ["missing"]
[http_service.concurrency]
soft_limit = 50
hard_limit = 10
'''
        data = json.loads(await self.call("inspect_fly_config", content=content))
        self.assertEqual(len(data["warnings"]), 4)

    async def test_fly_malformed_inputs_and_redacted_errors(self):
        for content in ("", '[env]\nTOKEN = "private-parse-marker', 'app="a"\napp="private-duplicate-marker"',
                        '[env]\nTOKEN=123', '[http_service]\ninternal_port=true', '[http_service]\ninternal_port=0',
                        '[http_service]\nauto_start_machines="true"', '[http_service]\nauto_stop_machines=[]',
                        '[http_service]\nmin_machines_running=-1', '[[vm]]\ncpus=true', '[[services.ports]]\nport=false',
                        '[[services.ports]]\nstart_port=9\nend_port=2', '[[services.ports]]\nstart_port=9',
                        '[[services.ports]]\nhandlers=["http"]', '[processes]\na=123', '[env]\nX=nan',
                        '[[http_service.checks]]\nheaders=[]'):
            with self.subTest(content=content):
                output = await self.call("inspect_fly_config", content=content)
                self.assertTrue(output.startswith("Error:"), output)
                self.assertNotIn("private-parse-marker", output)
                self.assertNotIn("private-duplicate-marker", output)

    async def test_fly_input_structure_and_collection_bounds(self):
        for content in ('app="' + "x" * 200001 + '"', 'app="' + "x" * 2001 + '"',
                        'env={' + ','.join(f'A{i}="x"' for i in range(101)) + '}',
                        'ignored=[' + ','.join('0' for _ in range(10001)) + ']',
                        'ignored=' + '[' * 52 + '0' + ']' * 52):
            self.assertTrue((await self.call("inspect_fly_config", content=content)).startswith("Error:"))

    async def test_fly_repository_config_offline(self):
        content = (Path(__file__).resolve().parents[1] / "fly.toml").read_text()
        data = json.loads(await self.call("inspect_fly_config", content=content))
        self.assertEqual(data["app"], "mcpsever")
        self.assertEqual(data["services"][0]["internal_port"], 8000)
        self.assertNotIn("MCP_SKIP_HOST_VALIDATION", data["environment_names"])

    async def test_env_comparison_missing_unexpected_and_duplicates(self):
        template = 'TOKEN=hidden-token\nPORT=8000\nTOKEN=another-hidden-token\nOPTIONAL\n'
        output = await self.call("compare_env_keys", template=template, available_keys_json='["TOKEN","EXTRA","TOKEN"]')
        data = json.loads(output)
        self.assertEqual(data["template_key_count"], 3)
        self.assertEqual(data["available_key_count"], 2)
        self.assertFalse(data["keys_match"])
        self.assertEqual(data["missing"], ["OPTIONAL", "PORT"])
        self.assertEqual(data["unexpected"], ["EXTRA"])
        self.assertEqual(data["matched"], ["TOKEN"])
        self.assertEqual(data["template_duplicates"], [{"key": "TOKEN", "count": 2}])
        self.assertEqual(data["available_duplicates"], [{"key": "TOKEN", "count": 2}])
        self.assertNotIn("hidden-token", output)

    async def test_env_export_bom_multiline_quotes_comments_and_case(self):
        template = '\ufeff# example\r\nexport TOKEN="one\ntwo"\n\'PORT\'=8000 # comment\nEMPTY=\nName=${PRIVATE_ENV}\n'
        with patch.dict(os.environ, {"PRIVATE_ENV": "must-not-interpolate"}):
            output = await self.call("compare_env_keys", template=template, available_keys_json='["TOKEN","PORT","EMPTY","name"]')
        data = json.loads(output)
        self.assertEqual(data["missing"], ["Name"])
        self.assertEqual(data["unexpected"], ["name"])
        self.assertNotIn("PRIVATE_ENV", output)
        self.assertNotIn("must-not-interpolate", output)
        self.assertNotIn("one", output)

    async def test_env_empty_inputs_and_exact_match(self):
        for template, names in (("# no keys", "[]"), ("A=secret\nB\n", '["B","A"]')):
            data = json.loads(await self.call("compare_env_keys", template=template, available_keys_json=names))
            self.assertTrue(data["keys_match"])
            self.assertEqual(data["missing"], [])
            self.assertEqual(data["unexpected"], [])

    async def test_env_invalid_templates_and_names_do_not_echo_values(self):
        for template in ('TOKEN="secret-marker', '1KEY=secret-marker', 'A-B=secret-marker', "=secret-marker"):
            output = await self.call("compare_env_keys", template=template, available_keys_json="[]")
            self.assertTrue(output.startswith("Error:"))
            self.assertNotIn("secret-marker", output)
        for names in ('{"TOKEN":"secret-marker"}', '["TOKEN=secret-marker"]', '["A-B"]', '[1]', '[true]', '[null]', '"TOKEN"', '{'):
            output = await self.call("compare_env_keys", template="TOKEN=", available_keys_json=names)
            self.assertTrue(output.startswith("Error:"))
            self.assertNotIn("secret-marker", output)

    async def test_env_input_and_key_bounds(self):
        cases = (("#" * 200001, "[]"), ("A=\n" * 1001, "[]"), ("A" * 201 + "=", "[]"),
                 ("", json.dumps(["A"] * 1001)), ("", " " * 200001), ("", json.dumps(["A" * 201])))
        for template, names in cases:
            self.assertTrue((await self.call("compare_env_keys", template=template, available_keys_json=names)).startswith("Error:"))

    async def test_kubernetes_workload_probes_resources_and_secret_omission(self):
        content = '''apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: demo
  annotations: {password: hidden-annotation}
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: web
          image: nginx:stable
          command: [echo, hidden-command]
          args: [hidden-args]
          ports: [{name: http, containerPort: 8080}]
          env:
            - {name: TOKEN, value: hidden-env}
            - name: PASSWORD
              valueFrom: {secretKeyRef: {name: credentials, key: password, optional: false}}
            - name: MODE
              valueFrom: {configMapKeyRef: {name: settings, key: mode}}
          envFrom: [{prefix: CFG_, configMapRef: {name: settings}}]
          resources:
            requests: {cpu: 100m, memory: 64Mi}
            limits: {cpu: 1, memory: 128Mi}
          readinessProbe:
            httpGet:
              path: /health
              port: http
              httpHeaders: [{name: Authorization, value: hidden-header}]
            periodSeconds: 5
          livenessProbe: {exec: {command: [echo, hidden-probe-command]}}
          startupProbe: {tcpSocket: {port: 8080}}
      initContainers:
        - {name: init, image: busybox, restartPolicy: Always}
      imagePullSecrets: [{name: registry}]
      volumes:
        - name: credentials
          secret: {secretName: credentials}
        - name: projected
          projected: {sources: [{secret: {name: another}}, {configMap: {name: settings}}]}
'''
        output = await self.call("inspect_kubernetes_manifest", content=content)
        data = json.loads(output)
        row = data["objects"][0]
        self.assertEqual(row["replicas"], 2)
        self.assertEqual(row["namespace"], "demo")
        self.assertEqual(data["container_count"], 2)
        container = row["pod"]["containers"][0]
        self.assertEqual(container["resources"]["requests"]["cpu"], "100m")
        self.assertEqual(container["probes"]["readinessProbe"]["port"], "http")
        self.assertEqual(container["probes"]["livenessProbe"]["action"], "exec")
        self.assertTrue(container["probes"]["livenessProbe"]["command_declared"])
        self.assertEqual(row["pod"]["containers"][1]["role"], "init")
        self.assertEqual(row["pod"]["containers"][1]["restart_policy"], "Always")
        self.assertEqual({ref["name"] for ref in row["pod"]["references"]}, {"credentials", "settings", "registry", "another"})
        self.assertEqual(row["pod"]["references"][0]["key"], "password")
        for hidden in ("hidden-annotation", "hidden-command", "hidden-args", "hidden-env", "hidden-header", "hidden-probe-command"):
            self.assertNotIn(hidden, output)

    async def test_kubernetes_multi_documents_services_and_data_key_names(self):
        content = '''---
apiVersion: v1
kind: Service
metadata: {name: web}
spec:
  type: NodePort
  selector: {app: web}
  ports: [{port: 80, targetPort: http, nodePort: 30080}]
---
apiVersion: v1
kind: Secret
metadata: {name: creds}
data: {token: hidden-secret-data}
stringData: {password: hidden-secret-string}
---
apiVersion: v1
kind: ConfigMap
metadata: {name: settings}
data: {mode: hidden-config-value}
binaryData: {blob: hidden-binary-value}
---
'''
        output = await self.call("inspect_kubernetes_manifest", content=content)
        data = json.loads(output)
        self.assertEqual(data["object_count"], 3)
        self.assertEqual(data["objects"][0]["ports"][0]["node_port"], 30080)
        self.assertEqual(data["objects"][1]["data_keys"], {"data": ["token"], "stringData": ["password"]})
        self.assertEqual(data["objects"][2]["data_keys"]["binaryData"], ["blob"])
        self.assertIsNone(data["objects"][0]["namespace"])
        for value in ("hidden-secret-data", "hidden-secret-string", "hidden-config-value", "hidden-binary-value"):
            self.assertNotIn(value, output)

    async def test_kubernetes_workload_template_locations(self):
        for kind in ("Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "CronJob"):
            spec = {"template": {"spec": pod()["spec"]}}
            if kind == "CronJob":
                spec = {"schedule": "*/5 * * * *", "jobTemplate": {"spec": spec}}
            data = {"apiVersion": "batch/v1" if kind in {"Job", "CronJob"} else "apps/v1",
                    "kind": kind, "metadata": {"name": "demo"}, "spec": spec}
            with self.subTest(kind=kind):
                result = json.loads(await self.call("inspect_kubernetes_manifest", content=json.dumps(data)))
                self.assertEqual(result["objects"][0]["pod"]["containers"][0]["name"], "web")
                if kind in {"Deployment", "StatefulSet", "ReplicaSet"}:
                    self.assertIsNone(result["objects"][0]["replicas"])

    async def test_kubernetes_list_unknown_kinds_and_generated_names(self):
        custom = {"apiVersion": "custom/v1", "kind": "Widget", "metadata": {"generateName": "widget-"}, "spec": {"token": "hidden-custom-value"}}
        output = await self.call("inspect_kubernetes_manifest", content=json.dumps({"kind": "List", "items": [pod(), custom]}))
        data = json.loads(output)
        self.assertEqual(data["object_count"], 2)
        self.assertTrue(data["objects"][0]["inspected"])
        self.assertFalse(data["objects"][1]["inspected"])
        self.assertEqual(data["objects"][1]["generate_name"], "widget-")
        self.assertNotIn("hidden-custom-value", output)

    async def test_kubernetes_aliases_scalars_and_ephemeral_containers(self):
        content = '''apiVersion: v1
kind: Pod
metadata: {name: yes}
spec:
  containers: [{name: web, image: no, resources: {limits: {cpu: 0.5}}}]
  ephemeralContainers: [{name: debugger, image: busybox}]
  volumes:
    - &base {name: cfg, configMap: {name: settings}}
    - {<<: *base, name: second}
'''
        data = json.loads(await self.call("inspect_kubernetes_manifest", content=content))
        self.assertEqual(data["objects"][0]["name"], "yes")
        self.assertEqual(data["objects"][0]["pod"]["containers"][0]["image"], "no")
        self.assertEqual(data["objects"][0]["pod"]["containers"][1]["role"], "ephemeral")
        self.assertEqual(len(data["objects"][0]["pod"]["references"]), 2)

    async def test_kubernetes_yaml_safety_and_sanitized_errors(self):
        invalid = ("", "[]", "1: hidden-marker", "metadata: {TOKEN: hidden-marker", "kind: Pod\nkind: hidden-marker",
                   "!!python/object/apply:os.system [hidden-marker]", "value: &a [*a]", "value: .nan", "value: !!binary aGVsbG8=",
                   "value: !!bool hidden-marker", 'value: !!float ""',
                   "ignored: " + "[" * 52 + "0" + "]" * 52)
        for content in invalid:
            with self.subTest(content=content[:60]):
                output = await self.call("inspect_kubernetes_manifest", content=content)
                self.assertTrue(output.startswith("Error:"))
                self.assertNotIn("hidden-marker", output)

    async def test_kubernetes_malformed_shapes_and_declared_types(self):
        invalid = [pod(containers=[]), pod(containers=[None]), pod(containers=[{"name": "web", "ports": [{"containerPort": True}]}]),
                   pod(containers=[{"name": "web", "resources": {"requests": {"cpu": True}}}]),
                   pod(containers=[{"name": "web", "readinessProbe": {"grpc": {"port": "named"}}}]),
                   pod(containers=[{"name": "web", "readinessProbe": {"exec": {}, "httpGet": {"port": 80}}}]),
                   pod(containers=[{"name": "web", "readinessProbe": {"tcpSocket": {"port": 80}, "periodSeconds": 0}}]),
                   pod(containers=[{"name": "web", "env": [{"name": "TOKEN", "valueFrom": {"secretKeyRef": {"key": "token"}}}]}]),
                   pod(containers=[{"name": "web", "env": [{"name": "A", "value": "hidden", "valueFrom": {"fieldRef": {}}}]}]),
                   {"kind": "List", "items": [{"kind": "List", "items": []}]}, {"kind": "List", "items": []},
                   {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "creds"}, "data": []},
                   {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "web"}, "spec": {"ports": [{"port": False}]}},
                   {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "web"}, "spec": {"replicas": True, "template": {"spec": pod()["spec"]}}}]
        for obj in invalid:
            with self.subTest(obj=obj):
                self.assertTrue((await self.call("inspect_kubernetes_manifest", content=json.dumps(obj))).startswith("Error:"))

    async def test_kubernetes_truncation_validates_all_objects(self):
        content = json.dumps({"kind": "List", "items": [pod("a"), pod("b")]})
        data = json.loads(await self.call("inspect_kubernetes_manifest", content=content, limit=1))
        self.assertEqual(data["object_count"], 2)
        self.assertEqual(data["container_count"], 2)
        self.assertEqual(len(data["objects"]), 1)
        self.assertTrue(data["truncated"])
        invalid = json.dumps({"kind": "List", "items": [pod(), pod("b", containers=[])]})
        self.assertTrue((await self.call("inspect_kubernetes_manifest", content=invalid, limit=1)).startswith("Error:"))
        for limit in (0, 51):
            self.assertTrue((await self.call("inspect_kubernetes_manifest", content=content, limit=limit)).startswith("Error:"))

    async def test_kubernetes_document_object_node_and_container_bounds(self):
        many_containers = {"kind": "List", "items": [pod(str(index), containers=[{"name": str(i)} for i in range(100)]) for index in range(3)]}
        cases = ("#" * 200001, "---\n" * 101, json.dumps({"kind": "List", "items": [pod(str(i)) for i in range(101)]}),
                 "ignored: [" + ",".join("0" for _ in range(10001)) + "]", json.dumps(many_containers))
        for content in cases:
            self.assertTrue((await self.call("inspect_kubernetes_manifest", content=content)).startswith("Error:"))
        # Each document is individually small, but expanded aliases exceed the stream budget.
        document = 'apiVersion: v1\nkind: Widget\nmetadata: {name: demo}\na: &a [' + ','.join('x' for _ in range(100)) + ']\nb: [*a, *a, *a, *a, *a, *a]\n'
        self.assertTrue((await self.call("inspect_kubernetes_manifest", content=(document + "---\n") * 20)).startswith("Error:"))

    async def test_output_caps_and_direct_boolean_limit_rejection(self):
        for name, function, arguments in (
            ("inspect_fly_config", "inspect_fly", {"content": 'app="demo"'}),
            ("compare_env_keys", "compare_environment", {"template": "A=", "available_keys_json": "[]"}),
            ("inspect_kubernetes_manifest", "inspect_kubernetes", {"content": json.dumps(pod())}),
        ):
            with patch.object(service, function, return_value={"data": "x" * 100001}):
                self.assertIn("100000", await self.call(name, **arguments))
        with self.assertRaises(ValueError):
            service.inspect_kubernetes(json.dumps(pod()), True)

    async def test_services_do_not_access_files_network_or_execute_commands(self):
        with patch("builtins.open", side_effect=AssertionError("Unexpected file access")), \
                patch("socket.create_connection", side_effect=AssertionError("Unexpected network access")), \
                patch("subprocess.run", side_effect=AssertionError("Unexpected command execution")):
            fly = service.inspect_fly('app="demo"\n[build]\ndockerfile="/never/read"\n[deploy]\nrelease_command="never-run"')
            environment = service.compare_environment("A=${SHOULD_NOT_READ}\n", '["A"]')
            kubernetes = service.inspect_kubernetes(json.dumps(pod()), 20)
        self.assertEqual(fly["app"], "demo")
        self.assertTrue(environment["keys_match"])
        self.assertEqual(kubernetes["object_count"], 1)


if __name__ == "__main__":
    unittest.main()
