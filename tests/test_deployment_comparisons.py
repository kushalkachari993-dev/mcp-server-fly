import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.config_utils import service as configurations
from app.tools.deployment_utils import service as deployments
from app.tools.deployment_comparison import service, tool


def compose(services=None, **settings):
    return json.dumps({"services": {"web": {"image": "nginx:stable"}} if services is None else services, **settings})


def workflow(jobs=None, **settings):
    return json.dumps({"on": "push", "jobs": {"test": {"runs-on": "ubuntu-latest", "steps": [{"uses": "actions/checkout@v4"}]}}
                       if jobs is None else jobs, **settings})


def pod(name="app", namespace=None, **spec):
    return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, **({"namespace": namespace} if namespace else {})},
            "spec": {"containers": [{"name": "web", "image": "nginx:stable"}], **spec}}


def manifest(*objects):
    return json.dumps({"kind": "List", "items": objects})


FLY = 'app = "demo"\nprimary_region = "bom"\n[http_service]\ninternal_port = 8000\nauto_stop_machines = "stop"\nauto_start_machines = true\n'


class DeploymentComparisonTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("deployment-comparison-tests")
        tool.register(self.mcp)

    async def call(self, name, before, after, **arguments):
        result = await self.mcp.call_tool(name, {"before": before, "after": after, **arguments})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def compare(self, name, before, after, **arguments):
        text = await self.call(name, before, after, **arguments)
        self.assertFalse(text.startswith("Error:"), text)
        return json.loads(text)

    async def test_four_public_tools_without_internal_complete_option(self):
        tools = await self.mcp.list_tools()
        self.assertEqual({item.name for item in tools}, {
            "compare_docker_compose", "compare_kubernetes_manifests", "compare_github_actions", "compare_fly_configs"})
        for item in tools:
            self.assertEqual(set(item.inputSchema["properties"]), {"before", "after", "limit"})

    async def test_compose_images_build_ports_dependencies_and_health_settings(self):
        old = {"web": {"image": "app:1", "build": {"context": ".", "target": "old"},
                       "ports": ["8080:80"], "depends_on": {"db": {"condition": "service_started"}},
                       "healthcheck": {"test": ["CMD", "private-command"], "interval": "30s", "retries": 2}},
               "db": {"image": "db:1"}}
        new = copy.deepcopy(old)
        new["web"].update(image="app:2", ports=[{"target": 80, "published": 8081}])
        new["web"]["build"]["target"] = "runtime"
        new["web"]["depends_on"]["db"]["condition"] = "service_healthy"
        new["web"]["healthcheck"].update(interval="10s", retries=3)
        data = await self.compare("compare_docker_compose", compose(old), compose(new))
        self.assertEqual(data["matching"]["matched_count"], 2)
        self.assertEqual(data["changed_count"], 1)
        self.assertEqual(data["unchanged_count"], 1)
        self.assertEqual({row["path"] for row in data["comparisons"][0]["changes"]},
                         {"/image", "/build/target", "/ports", "/dependencies", "/healthcheck/interval", "/healthcheck/retries"})
        self.assertFalse(data["selected_fields_equal"])
        self.assertNotIn("private-command", json.dumps(data))

    async def test_compose_exact_service_names_added_removed_and_reordering(self):
        old = compose({"web": {"image": "same"}, "db": {"image": "same"}})
        new = compose({"cache": {"image": "same"}, "web": {"image": "same"}})
        data = await self.compare("compare_docker_compose", old, new)
        self.assertEqual(data["matching"]["added"], [{"name": "cache"}])
        self.assertEqual(data["matching"]["removed"], [{"name": "db"}])
        self.assertEqual(data["matching"]["matched_count"], 1)
        self.assertEqual(data["change_count"], 0)
        self.assertFalse(data["selected_fields_equal"])
        reversed_services = compose({"db": {"image": "same"}, "web": {"image": "same"}})
        self.assertTrue((await self.compare("compare_docker_compose", old, reversed_services))["selected_fields_equal"])

    async def test_compose_top_level_resource_names_and_include_presence(self):
        old = compose(name="demo", secrets={"token": {"file": "private-file"}})
        new = compose(name="renamed", secrets={"other": {"environment": "private-environment"}}, include=["private-include"])
        data = await self.compare("compare_docker_compose", old, new)
        self.assertEqual({row["path"] for row in data["configuration_changes"]},
                         {"/name", "/declarations/secrets", "/include_declared"})
        for value in ("private-file", "private-environment", "private-include"):
            self.assertNotIn(value, json.dumps(data))

    async def test_compose_environment_build_command_and_test_values_omitted(self):
        old = {"web": {"environment": {"TOKEN": "private-old"}, "command": "private-command-old",
                       "build": {"context": ".", "args": {"TOKEN": "private-arg-old"}},
                       "healthcheck": {"test": "private-test-old"}}}
        new = {"web": {"environment": {"TOKEN": "private-new"}, "command": "private-command-new",
                       "build": {"context": ".", "args": {"TOKEN": "private-arg-new"}},
                       "healthcheck": {"test": "private-test-new"}}}
        data = await self.compare("compare_docker_compose", compose(old), compose(new))
        self.assertTrue(data["selected_fields_equal"])
        self.assertNotIn("private-", json.dumps(data))

    async def test_compose_literal_lists_not_runtime_equivalence_or_defaults(self):
        old = compose({"web": {"ports": ["8080:80"]}})
        new = compose({"web": {"ports": [{"target": 80, "published": "8080", "protocol": "tcp"}]}})
        data = await self.compare("compare_docker_compose", old, new)
        self.assertEqual(data["comparisons"][0]["changes"][0]["path"], "/ports")
        old = compose({"web": {"image": "same", "environment": {"A": "x", "B": "y"}}})
        new = compose({"web": {"image": "same", "environment": {"B": "y", "A": "x"}}})
        self.assertFalse((await self.compare("compare_docker_compose", old, new))["selected_fields_equal"])

    async def test_compose_all_services_after_public_inspector_limit(self):
        old = {f"s{index}": {"image": "app:1"} for index in range(100)}
        new = copy.deepcopy(old)
        new["s99"]["image"] = "app:2"
        self.assertEqual(len(configurations.inspect_compose(compose(old), 50)["services"]), 50)
        data = await self.compare("compare_docker_compose", compose(old), compose(new), limit=1)
        self.assertEqual(data["matching"]["matched_count"], 100)
        self.assertEqual(data["comparisons"][0]["identity"], {"name": "s99"})
        self.assertEqual(data["unchanged_count"], 99)

    async def test_compose_full_environment_names_and_full_strings_before_display(self):
        old = {"web": {"environment": {f"K{index}": "private" for index in range(101)}}}
        new = copy.deepcopy(old)
        new["web"]["environment"]["LAST"] = "private"
        data = await self.compare("compare_docker_compose", compose(old), compose(new), limit=1)
        self.assertFalse(data["selected_fields_equal"])
        self.assertTrue(data["truncated"])
        prefix = "x" * 2000
        data = await self.compare("compare_docker_compose", compose({"web": {"image": prefix + "old"}}),
                                  compose({"web": {"image": prefix + "new"}}))
        row = data["comparisons"][0]["changes"][0]
        self.assertEqual(row["before"], row["after"])
        self.assertEqual(data["change_count"], 1)
        self.assertTrue(data["truncated"])

    async def test_actions_permissions_runners_needs_action_refs_and_triggers(self):
        old = workflow({"build": {}, "test": {"needs": "build", "runs-on": "ubuntu-latest",
                                               "permissions": {"contents": "read"},
                                               "steps": [{"uses": "actions/checkout@v4"}]}}, permissions="read-all")
        new = workflow({"build": {}, "test": {"runs-on": ["self-hosted", "linux"],
                                               "permissions": {"contents": "write"},
                                               "steps": [{"uses": "actions/checkout@v5"}]}}, permissions="write-all",
                       **{"on": {"push": {"branches": ["main"]}, "schedule": [{"cron": "0 * * * *"}]}})
        data = await self.compare("compare_github_actions", old, new)
        self.assertEqual(data["matching"]["matched_count"], 2)
        self.assertEqual(data["changed_count"], 1)
        self.assertEqual({row["path"] for row in data["comparisons"][0]["changes"]},
                         {"/needs", "/runs_on", "/permissions/scopes/contents", "/steps"})
        self.assertEqual({row["path"] for row in data["configuration_changes"]}, {"/events", "/permissions/mode"})

    async def test_actions_added_removed_job_ids_and_null_permissions(self):
        data = await self.compare("compare_github_actions", workflow({"old": {}, "same": {}}),
                                  workflow({"same": {"permissions": {}}, "new": {}}))
        self.assertEqual(data["matching"]["added"], [{"id": "new"}])
        self.assertEqual(data["matching"]["removed"], [{"id": "old"}])
        change = data["comparisons"][0]["changes"][0]
        self.assertEqual(change["path"], "/permissions")
        self.assertIsNone(change["before"])
        self.assertEqual(change["after"], {"mode": "explicit", "scopes": {}})

    async def test_actions_secret_run_with_and_matrix_values_not_compared(self):
        def content(value):
            return workflow({"test": {"env": {"TOKEN": value}, "strategy": {"matrix": {"python": [value]}},
                                      "steps": [{"run": value, "env": {"TOKEN": value}},
                                                {"uses": "same@ref", "with": {"token": value}}]}},
                            env={"TOKEN": value}, **{"on": {"workflow_dispatch": {"inputs": {"token": {"default": value}}}}})
        data = await self.compare("compare_github_actions", content("private-old"), content("private-new"))
        self.assertTrue(data["selected_fields_equal"])
        self.assertNotIn("private-", json.dumps(data))

    async def test_actions_all_jobs_and_steps_beyond_public_samples(self):
        jobs = {f"job{index}": {} for index in range(60)}
        jobs["job59"] = {"steps": [{"uses": "demo/action@v1"} for _ in range(60)]}
        old = workflow(jobs)
        jobs["job59"]["steps"][59]["uses"] = "demo/action@v2"
        new = workflow(jobs)
        public = configurations.inspect_actions(new, 50, 50)
        self.assertEqual(len(public["jobs"]), 50)
        data = await self.compare("compare_github_actions", old, new, limit=1)
        self.assertEqual(data["matching"]["matched_count"], 60)
        self.assertEqual(data["comparisons"][0]["identity"], {"id": "job59"})
        self.assertEqual(data["comparisons"][0]["changes"][0]["path"], "/steps")
        self.assertTrue(data["truncated"])

    async def test_actions_steps_are_whole_sequences_not_duplicate_id_guesses(self):
        first = {"id": "duplicate", "uses": "demo/one@v1"}
        second = {"id": "duplicate", "uses": "demo/two@v1"}
        data = await self.compare("compare_github_actions", workflow({"test": {"steps": [first, second]}}),
                                  workflow({"test": {"steps": [second, first]}}))
        self.assertEqual(data["comparisons"][0]["change_count"], 1)
        change = data["comparisons"][0]["changes"][0]
        self.assertEqual(change["path"], "/steps")
        self.assertEqual(change["before"][0]["uses"], "demo/one@v1")
        self.assertEqual(change["after"][0]["uses"], "demo/two@v1")

    async def test_actions_long_reference_and_trigger_tail_compared_before_truncation(self):
        prefix = "x" * 2000
        data = await self.compare("compare_github_actions", workflow({"test": {"uses": prefix + "old"}}),
                                  workflow({"test": {"uses": prefix + "new"}}))
        self.assertEqual(data["change_count"], 1)
        self.assertTrue(data["truncated"])
        old = workflow(**{"on": {"push": {"branches": ["same"]}, "schedule": [{"cron": "0 * * * *"}]}})
        new = workflow(**{"on": {"push": {"branches": ["same"]}, "schedule": [{"cron": "1 * * * *"}]}})
        data = await self.compare("compare_github_actions", old, new, limit=1)
        self.assertFalse(data["selected_fields_equal"])
        self.assertTrue(data["truncated"])

    async def test_kubernetes_workload_images_replicas_resources_probes_and_references(self):
        old = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "app", "namespace": "prod"},
               "spec": {"replicas": 1, "template": {"spec": pod()["spec"]}}}
        new = copy.deepcopy(old)
        new["spec"]["replicas"] = 3
        new["spec"]["template"]["spec"]["containers"][0].update(
            image="app:2", resources={"requests": {"cpu": "100m", "memory": "64Mi"}},
            readinessProbe={"httpGet": {"path": "/ready", "port": 8080}, "periodSeconds": 5},
            env=[{"name": "TOKEN", "valueFrom": {"secretKeyRef": {"name": "credentials", "key": "token"}}}])
        data = await self.compare("compare_kubernetes_manifests", manifest(old), manifest(new))
        self.assertEqual(data["comparisons"][0]["identity"],
                         {"api_group": "apps", "kind": "Deployment", "namespace": "prod", "name": "app"})
        changes = {row["path"]: row for row in data["comparisons"][0]["changes"]}
        self.assertEqual(set(changes), {"/replicas", "/pod/containers", "/pod/references"})
        self.assertEqual(changes["/pod/containers"]["after"][0]["image"], "app:2")
        self.assertEqual(changes["/pod/references"]["after"][0]["name"], "credentials")

    async def test_kubernetes_service_settings_and_multidocument_yaml(self):
        old = 'apiVersion: v1\nkind: Service\nmetadata: {name: web}\nspec: {type: ClusterIP, ports: [{port: 80, targetPort: 8000}]}\n---\n' + json.dumps(pod())
        new = old.replace("ClusterIP", "NodePort").replace("targetPort: 8000", "targetPort: 8080")
        data = await self.compare("compare_kubernetes_manifests", old, new)
        self.assertEqual(data["matching"]["matched_count"], 2)
        self.assertEqual({row["path"] for row in data["comparisons"][0]["changes"]}, {"/service_type", "/ports"})

    async def test_kubernetes_api_version_changes_within_group_match(self):
        old = {"apiVersion": "custom.example/v1alpha1", "kind": "Widget", "metadata": {"name": "app"}}
        new = {**old, "apiVersion": "custom.example/v1"}
        data = await self.compare("compare_kubernetes_manifests", manifest(old), manifest(new))
        self.assertEqual(data["matching"]["matched_count"], 1)
        self.assertEqual(data["comparisons"][0]["changes"][0]["path"], "/api_version")
        self.assertEqual(data["before"]["metadata_only_count"], 1)

    async def test_kubernetes_group_kind_namespace_and_name_define_identity(self):
        old = {"apiVersion": "one/v1", "kind": "Widget", "metadata": {"name": "app", "namespace": "prod"}}
        alternatives = [{**old, "apiVersion": "two/v1"}, {**old, "kind": "Other"},
                        {**old, "metadata": {"name": "app", "namespace": "staging"}},
                        {**old, "metadata": {"name": "renamed", "namespace": "prod"}}]
        for new in alternatives:
            data = await self.compare("compare_kubernetes_manifests", manifest(old), manifest(new))
            self.assertEqual(data["matching"]["matched_count"], 0)
            self.assertEqual(data["matching"]["added_count"], 1)
            self.assertEqual(data["matching"]["removed_count"], 1)

    async def test_kubernetes_omitted_namespace_is_not_default(self):
        data = await self.compare("compare_kubernetes_manifests", manifest(pod()), manifest(pod(namespace="default")))
        self.assertEqual(data["matching"]["matched_count"], 0)
        self.assertIsNone(data["matching"]["removed"][0]["namespace"])
        self.assertEqual(data["matching"]["added"][0]["namespace"], "default")

    async def test_kubernetes_duplicate_identities_across_versions_are_ambiguous(self):
        obj = {"apiVersion": "custom/v1", "kind": "Widget", "metadata": {"name": "app"}}
        duplicate = {**obj, "apiVersion": "custom/v2"}
        for before, after in ((manifest(obj, duplicate), manifest(obj)), (manifest(obj), manifest(obj, duplicate)),
                              (manifest(obj, duplicate), manifest(obj, duplicate))):
            data = await self.compare("compare_kubernetes_manifests", before, after)
            self.assertEqual(data["matching"]["ambiguous_count"], 1)
            self.assertEqual(data["matching"]["matched_count"], 0)
            self.assertEqual(data["matching"]["added_count"], 0)
            self.assertIsNone(data["selected_fields_equal"])

    async def test_kubernetes_generated_names_and_malformed_group_are_unmatchable(self):
        obj = {"apiVersion": "custom/v1", "kind": "Widget", "metadata": {"generateName": "app-"}}
        bad_version = {"apiVersion": "custom/v1/extra", "kind": "Widget", "metadata": {"name": "app"}}
        content = manifest(obj, bad_version)
        data = await self.compare("compare_kubernetes_manifests", content, content)
        self.assertEqual(data["matching"]["unmatchable_before_count"], 2)
        self.assertEqual(data["matching"]["unmatchable_after_count"], 2)
        self.assertIsNone(data["selected_fields_equal"])

    async def test_kubernetes_known_change_with_ambiguous_records_still_false(self):
        old, new = pod(), pod()
        new["spec"]["containers"][0]["image"] = "changed"
        data = await self.compare("compare_kubernetes_manifests", manifest(old, pod("duplicate"), pod("duplicate")),
                                  manifest(new, pod("duplicate"), pod("duplicate")))
        self.assertFalse(data["selected_fields_equal"])
        self.assertEqual(data["matching"]["ambiguous_count"], 1)
        self.assertEqual(data["changed_count"], 1)

    async def test_kubernetes_unknown_kind_and_secret_values_excluded(self):
        def objects(value):
            return manifest({"apiVersion": "custom/v1", "kind": "Widget", "metadata": {"name": "app"}, "spec": {"token": value}},
                            {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "credentials"}, "data": {"token": value}},
                            {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "settings"}, "data": {"mode": value}})
        data = await self.compare("compare_kubernetes_manifests", objects("private-old"), objects("private-new"))
        self.assertTrue(data["selected_fields_equal"])
        self.assertEqual(data["before"]["metadata_only_count"], 1)
        self.assertNotIn("private-", json.dumps(data))

    async def test_kubernetes_secret_key_changes_not_secret_values(self):
        old = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "credentials"}, "data": {"token": "private-old"}}
        new = {**old, "data": {"password": "private-new"}}
        data = await self.compare("compare_kubernetes_manifests", manifest(old), manifest(new))
        self.assertEqual(data["comparisons"][0]["changes"][0]["path"], "/data_keys/data")
        self.assertNotIn("private-", json.dumps(data))

    async def test_kubernetes_command_env_annotation_and_probe_header_values_omitted(self):
        def objects(value, image):
            obj = pod()
            obj["metadata"]["annotations"] = {"token": value}
            obj["spec"]["containers"][0].update(image=image, command=[value], args=[value], env=[{"name": "TOKEN", "value": value}],
                readinessProbe={"httpGet": {"port": 80, "httpHeaders": [{"name": "Authorization", "value": value}]}},
                livenessProbe={"exec": {"command": [value]}})
            return manifest(obj)
        data = await self.compare("compare_kubernetes_manifests", objects("private-old", "app:1"), objects("private-new", "app:2"))
        self.assertEqual(data["changed_count"], 1)
        self.assertNotIn("private-", json.dumps(data))

    async def test_kubernetes_full_object_set_not_public_sample_or_document_order(self):
        objects = [pod(f"app{index}") for index in range(100)]
        old = manifest(*objects)
        objects[99]["spec"]["containers"][0]["image"] = "changed"
        new = manifest(*reversed(objects))
        data = await self.compare("compare_kubernetes_manifests", old, new, limit=1)
        self.assertEqual(data["matching"]["matched_count"], 100)
        self.assertEqual(data["changed_count"], 1)
        self.assertEqual(data["comparisons"][0]["identity"]["name"], "app99")

    async def test_kubernetes_container_order_and_resource_spelling_retained(self):
        old = pod(containers=[{"name": "one", "image": "app", "resources": {"limits": {"cpu": "1000m"}}},
                              {"name": "two", "image": "app"}])
        new = copy.deepcopy(old)
        new["spec"]["containers"].reverse()
        new["spec"]["containers"][1]["resources"]["limits"]["cpu"] = "1"
        data = await self.compare("compare_kubernetes_manifests", manifest(old), manifest(new))
        self.assertEqual(data["change_count"], 1)
        self.assertEqual(data["comparisons"][0]["changes"][0]["path"], "/pod/containers")

    async def test_fly_regions_services_checks_vm_mounts_build_and_deploy(self):
        old = FLY + '[[vm]]\nmemory = "256mb"\n[[mounts]]\nsource = "data"\ndestination = "/data"\n[build]\ndockerfile = "Dockerfile"\n[deploy]\nstrategy = "rolling"\n'
        new = old.replace('"bom"', '"sin"').replace('"stop"', '"off"').replace("8000", "8080").replace("256mb", "512mb").replace('"/data"', '"/storage"').replace('"Dockerfile"', '"Dockerfile.prod"').replace('"rolling"', '"canary"')
        data = await self.compare("compare_fly_configs", old, new)
        self.assertEqual(data["format"], "fly")
        self.assertEqual({row["path"] for row in data["configuration_changes"]},
                         {"/primary_region", "/services", "/machines", "/mounts", "/build/dockerfile", "/deploy/strategy"})
        self.assertFalse(data["selected_fields_equal"])
        self.assertNotIn("matching", data)

    async def test_fly_explicit_boolean_autostop_and_omitted_defaults_not_equivalent(self):
        for new in (FLY.replace('"stop"', "true"), FLY.replace('auto_stop_machines = "stop"\n', ""),
                    FLY.replace("auto_start_machines = true", "auto_start_machines = false")):
            data = await self.compare("compare_fly_configs", FLY, new)
            self.assertEqual(data["configuration_changes"][0]["path"], "/services")
            self.assertFalse(data["selected_fields_equal"])

    async def test_fly_secret_and_command_value_only_changes_omitted(self):
        def config(value):
            return FLY + f'[env]\nTOKEN = "{value}"\n[processes]\napp = "{value}"\n[build.args]\nTOKEN = "{value}"\n[deploy]\nrelease_command = "{value}"\n[checks.ready]\nport = 8000\n[checks.ready.headers]\nAuthorization = "{value}"\n'
        data = await self.compare("compare_fly_configs", config("private-old"), config("private-new"))
        self.assertTrue(data["selected_fields_equal"])
        self.assertNotIn("private-", json.dumps(data))

    async def test_fly_environment_process_and_build_argument_key_changes(self):
        old = FLY + '[env]\nTOKEN = "private-old"\n[processes]\napp = "private-command"\n[build.args]\nTOKEN = "private-old"\n'
        new = old.replace("TOKEN", "OTHER").replace('app = "private-command"', 'worker = "private-command"')
        data = await self.compare("compare_fly_configs", old, new)
        self.assertEqual({row["path"] for row in data["configuration_changes"]},
                         {"/environment_names", "/process_names", "/build/argument_names"})
        self.assertNotIn("private-", json.dumps(data))

    async def test_fly_actual_project_configuration_compares_without_live_lookup(self):
        content = (Path(__file__).resolve().parents[1] / "fly.toml").read_text(encoding="utf-8")
        data = await self.compare("compare_fly_configs", content, content)
        self.assertTrue(data["selected_fields_equal"])
        self.assertEqual(data["change_count"], 0)

    async def test_all_change_counts_are_computed_before_output_limit(self):
        old = {f"service{index}": {"image": "old"} for index in range(60)}
        new = {f"service{index}": {"image": "new"} for index in range(60)}
        data = await self.compare("compare_docker_compose", compose(old), compose(new), limit=1)
        self.assertEqual(data["changed_count"], 60)
        self.assertEqual(data["change_count"], 60)
        self.assertEqual(len(data["comparisons"]), 1)
        self.assertTrue(data["truncated"])
        old = {f"s{index}": {} for index in range(60)}
        new = {f"n{index}": {} for index in range(60)}
        data = await self.compare("compare_docker_compose", compose(old), compose(new), limit=1)
        self.assertEqual(data["matching"]["added_count"], 60)
        self.assertEqual(data["matching"]["removed_count"], 60)
        self.assertEqual(len(data["matching"]["added"]), 1)

    async def test_json_pointer_escaping_type_and_presence_distinctions(self):
        data = await self.compare("compare_github_actions", workflow(permissions={"a/b~c": "read"}),
                                  workflow(permissions={"a/b~c": "write"}))
        self.assertEqual(data["configuration_changes"][0]["path"], "/permissions/scopes/a~1b~0c")
        changes = service._differences({"missing": None, "types": [True]}, {"new": None, "types": [1]})
        self.assertEqual([row["type"] for row in changes], ["removed", "added", "changed"])
        self.assertFalse(changes[0]["after_present"])
        self.assertTrue(changes[1]["after_present"])

    async def test_late_invalid_records_still_rejected_with_limit_one(self):
        samples = (("compare_docker_compose", compose(), compose({"web": {}, "last": {"healthcheck": {"disable": "invalid"}}})),
                   ("compare_github_actions", workflow(), workflow({"test": {}, "last": {"permissions": {"contents": "admin"}}})),
                   ("compare_kubernetes_manifests", manifest(pod()), manifest(pod(), pod("last", containers=[{"name": "web", "ports": [{"containerPort": 0}]}]))),
                   ("compare_fly_configs", FLY, FLY + '[[vm]]\ncpus = 1\n[[vm]]\ncpus = 0\n'))
        for name, before, after in samples:
            for old, new in ((before, after), (after, before)):
                self.assertTrue((await self.call(name, old, new, limit=1)).startswith("Error:"), name)

    async def test_forbidden_duplicate_recursive_and_nonfinite_yaml_is_sanitized(self):
        invalid = ('PRIVATE_SOURCE: [', 'x: .nan', 'x: .inf', 'x: 1\nx: PRIVATE_SOURCE',
                   'x: &x [*x]', '!!python/object/apply:os.system [PRIVATE_SOURCE]', '1: PRIVATE_SOURCE',
                   'x: !!binary UFJJVkFURV9TT1VSQ0U=')
        for name in ("compare_docker_compose", "compare_github_actions", "compare_kubernetes_manifests"):
            for content in invalid:
                text = await self.call(name, content, content)
                self.assertTrue(text.startswith("Error:"), name)
                self.assertNotIn("PRIVATE_SOURCE", text)
        for content in ('app = "PRIVATE_SOURCE', 'app = "demo"\napp = "PRIVATE_SOURCE"', 'ignored = nan'):
            text = await self.call("compare_fly_configs", content, content)
            self.assertTrue(text.startswith("Error:"))
            self.assertNotIn("PRIVATE_SOURCE", text)

    async def test_yaml_expansion_depth_nodes_and_record_limits(self):
        bomb = 'a: &a [' + ','.join('x' for _ in range(50)) + ']\nb: &b [' + ','.join('*a' for _ in range(50)) + ']\nc: [' + ','.join('*b' for _ in range(50)) + ']'
        for content in (bomb, 'ignored: ' + '[' * 52 + '0' + ']' * 52,
                        'ignored: [' + ','.join('x' for _ in range(10001)) + ']'):
            for name in ("compare_docker_compose", "compare_github_actions", "compare_kubernetes_manifests"):
                self.assertTrue((await self.call(name, content, content)).startswith("Error:"))
        samples = (("compare_docker_compose", compose({f"s{index}": {} for index in range(101)})),
                   ("compare_github_actions", workflow({f"j{index}": {} for index in range(101)})),
                   ("compare_github_actions", workflow({"test": {"steps": [{"run": "echo"}] * 1001}})),
                   ("compare_kubernetes_manifests", manifest(*(pod(f"app{index}") for index in range(101)))),
                   ("compare_kubernetes_manifests", manifest(*(pod(f"app{index}", containers=[{"name": "a"}, {"name": "b"}, {"name": "c"}]) for index in range(67)))),
                   ("compare_fly_configs", FLY + '[[vm]]\ncpus = 1\n' * 101),
                   ("compare_fly_configs", FLY + 'ignored = ' + '[' * 52 + '0' + ']' * 52))
        for name, content in samples:
            self.assertTrue((await self.call(name, content, content, limit=1)).startswith("Error:"), name)

    async def test_input_type_size_and_limit_checked_before_parsing(self):
        samples = ((service.compare_compose, compose()), (service.compare_actions, workflow()),
                   (service.compare_kubernetes, manifest(pod())), (service.compare_fly, FLY))
        with patch.object(configurations, "inspect_compose", side_effect=AssertionError("parse")), \
                patch.object(configurations, "inspect_actions", side_effect=AssertionError("parse")), \
                patch.object(deployments, "inspect_kubernetes", side_effect=AssertionError("parse")), \
                patch.object(deployments, "inspect_fly", side_effect=AssertionError("parse")):
            for function, content in samples:
                for limit in (True, 0, 51, 1.5, "1", None):
                    with self.assertRaises(ValueError):
                        function(content, content, limit)
                for value in (None, {}, "x" * 200001):
                    for before, after in ((value, content), (content, value)):
                        with self.assertRaises(ValueError):
                            function(before, after, 1)

    async def test_no_file_network_dns_commands_or_expression_evaluation(self):
        samples = ((service.compare_compose, compose({"web": {"build": "C:/private-path", "extends": "private-file", "command": "unsafe"}}, include=["https://127.0.0.1/file"])),
                   (service.compare_actions, workflow({"test": {"runs-on": "${{ unsafe }}", "uses": "private/workflow@ref", "steps": [{"run": "unsafe"}]}})),
                   (service.compare_kubernetes, manifest(pod(containers=[{"name": "web", "image": "https://127.0.0.1/image", "command": ["unsafe"]}]))),
                   (service.compare_fly, FLY + '[build]\nimage = "https://127.0.0.1/image"\n[deploy]\nrelease_command = "unsafe"\n'))
        with patch("builtins.open", side_effect=AssertionError("file")), patch("socket.getaddrinfo", side_effect=AssertionError("DNS")), \
                patch("requests.get", side_effect=AssertionError("network")), patch("httpx.AsyncClient", side_effect=AssertionError("network")), \
                patch("subprocess.run", side_effect=AssertionError("process")), patch("os.system", side_effect=AssertionError("command")), \
                patch("builtins.eval", side_effect=AssertionError("expression")):
            for function, content in samples:
                self.assertTrue(function(content, content, 1)["selected_fields_equal"])

    async def test_complete_views_do_not_change_existing_public_inspector_responses(self):
        image = "x" * 2100
        compose_text = compose({"one": {"image": image}, "two": {}})
        workflow_text = workflow({"one": {"steps": [{"uses": "one"}, {"uses": "two"}]}, "two": {}})
        kubernetes_text = manifest(pod("one"), pod("two"))
        functions = ((configurations.inspect_compose, (compose_text, 1), "services"),
                     (configurations.inspect_actions, (workflow_text, 1, 1), "jobs"),
                     (deployments.inspect_kubernetes, (kubernetes_text, 1), "objects"))
        for function, arguments, field in functions:
            public = function(*arguments)
            full = function(*arguments, _complete=True)
            self.assertEqual(len(public[field]), 1)
            self.assertEqual(len(full[field]), 2)
            self.assertEqual(function(*arguments), public)
        self.assertEqual(configurations.inspect_compose(compose_text, 1)["services"][0]["image"], image[:2000])
        self.assertEqual(configurations.inspect_actions(workflow_text, 1, 1)["jobs"][0]["step_count"], 2)
        self.assertTrue(configurations.inspect_actions(workflow_text, 1, 1)["jobs"][0]["steps_truncated"])

    async def test_real_output_caps_and_smaller_limit_recovery(self):
        old_image, new_image = "a" * 1800, "b" * 1800
        old_pods, new_pods = [], []
        for index in range(45):
            old_pods.append(pod(f"app{index}", containers=[{"name": "web", "image": old_image}]))
            new_pods.append(pod(f"app{index}", containers=[{"name": "web", "image": new_image}]))
        samples = (("compare_docker_compose", compose({f"s{index}": {"image": old_image} for index in range(45)}),
                    compose({f"s{index}": {"image": new_image} for index in range(45)})),
                   ("compare_github_actions", workflow({f"j{index}": {"uses": old_image} for index in range(45)}),
                    workflow({f"j{index}": {"uses": new_image} for index in range(45)})),
                   ("compare_kubernetes_manifests", manifest(*old_pods), manifest(*new_pods)),
                   ("compare_fly_configs", FLY + ''.join(f'[checks.c{index}]\npath = "/{old_image}"\n' for index in range(45)),
                    FLY + ''.join(f'[checks.c{index}]\npath = "/{new_image}"\n' for index in range(45))))
        for name, before, after in samples:
            self.assertLess(len(before), 200000)
            self.assertLess(len(after), 200000)
            text = await self.call(name, before, after, limit=50)
            self.assertTrue(text.startswith("Error: Deployment summary exceeds 100000"), (name, text[:100]))
            data = await self.compare(name, before, after, limit=1)
            self.assertTrue(data["truncated"])
            self.assertFalse(data["selected_fields_equal"])


if __name__ == "__main__":
    unittest.main()
