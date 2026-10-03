import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.config_utils import service, tool
from app.tools.yaml_utils import tool as yaml_tool


class ConfigurationInspectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("configuration-tests")
        tool.register(self.mcp)
        yaml_tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_compose_services_ports_dependencies_and_health(self):
        content = '''name: demo
services:
  web:
    build: {context: ., dockerfile: Dockerfile, target: app, args: {TOKEN: private-build-token}}
    ports: ["8000:80", {target: 443, published: "8443", protocol: tcp}]
    depends_on: {db: {condition: service_healthy, required: true, restart: false}}
    environment: {TOKEN: private-env-token, MODE: production}
    healthcheck: {test: [CMD-SHELL, "echo private-health-token"], interval: 10s, retries: 3}
  db:
    image: postgres:18
    healthcheck: {disable: true}
volumes: {data: {}}
networks: {internal: {}}
secrets: {token: {file: /not/read}}
'''
        output = await self.call("inspect_docker_compose", content=content)
        data = json.loads(output)
        self.assertEqual(data["service_count"], 2)
        self.assertEqual(data["services"][0]["build"]["target"], "app")
        self.assertEqual(data["services"][0]["ports"][1]["published"], "8443")
        self.assertEqual(data["services"][0]["dependencies"][0]["condition"], "service_healthy")
        self.assertEqual(data["services"][0]["healthcheck"]["test_form"], "CMD-SHELL")
        self.assertTrue(data["services"][1]["healthcheck"]["disabled"])
        self.assertEqual(data["services"][0]["environment_names"], ["TOKEN", "MODE"])
        self.assertEqual(data["declarations"]["secrets"], ["token"])
        self.assertEqual(data["dependencies"]["order"], ["db", "web"])
        for secret in ("private-build-token", "private-env-token", "private-health-token", "/not/read"):
            self.assertNotIn(secret, output)

    async def test_compose_aliases_merges_and_short_forms(self):
        content = '''x-base: &base
  image: base:${TAG}
  environment: [A=hidden, B, A=other-hidden]
services:
  yes:
    <<: *base
    ports: [22:22, 8000]
    depends_on: [no]
  no:
    image: db
    healthcheck: {test: [NONE]}
'''
        data = json.loads(await self.call("inspect_docker_compose", content=content))
        self.assertEqual(data["services"][0]["name"], "yes")
        self.assertEqual(data["services"][0]["image"], "base:${TAG}")
        self.assertEqual(data["services"][0]["ports"], ["22:22", 8000])
        self.assertEqual(data["services"][0]["environment_names"], ["A", "B"])
        self.assertTrue(data["services"][1]["healthcheck"]["disabled"])

    async def test_compose_cycles_missing_services_and_unresolved_includes(self):
        content = '''include: /never/read.yml
services:
  a: {image: base, depends_on: [b, missing], extends: {file: other.yml, service: a}}
  b: {image: base, depends_on: [a]}
'''
        data = json.loads(await self.call("inspect_docker_compose", content=content))
        self.assertTrue(data["include_declared"])
        self.assertTrue(data["services"][0]["extends_declared"])
        self.assertTrue(data["dependencies"]["has_cycle"])
        self.assertIsNone(data["dependencies"]["order"])
        self.assertEqual(data["dependencies"]["unknown_dependency_count"], 1)

    async def test_compose_malformed_shapes_do_not_echo_values(self):
        for content in ("services: []", "services: {}", "services: {a: null}", "services: {a: {ports: false}}",
                        "services: {a: {ports: [false]}}", "services: {a: {ports: [{target: []}]}}",
                        "services: {a: {depends_on: {b: {required: yes}}}}", "services: {a: {healthcheck: {disable: yes}}}",
                        "services: {a: {healthcheck: {retries: true}}}", "services: {a: {environment: [123]}}",
                        "services: {a: {build: true}}", "services: {a: {image: false}}"):
            with self.subTest(content=content):
                self.assertTrue((await self.call("inspect_docker_compose", content=content)).startswith("Error:"))
        output = await self.call("inspect_docker_compose", content="services: {a: {environment: {TOKEN: secret-parse-token\n")
        self.assertTrue(output.startswith("Error:"))
        self.assertNotIn("secret-parse-token", output)

    async def test_actions_events_permissions_runners_and_dependencies(self):
        content = '''name: CI
on:
  push: {branches: [main], paths: ["app/**"]}
  workflow_dispatch: {inputs: {target: {default: private-input-token}}}
  schedule: [{cron: "0 0 * * *"}]
permissions: {contents: read}
env: {TOKEN: private-root-token}
jobs:
  test:
    runs-on: {group: linux, labels: [self-hosted, x64]}
    strategy: {matrix: {python: ["3.12", "3.13"]}}
    env: {PASSWORD: private-job-token}
    steps:
      - uses: actions/checkout@v4
        with: {token: private-with-token}
      - name: test
        run: echo private-run-token
        env: {LOCAL: private-step-token}
  deploy:
    needs: test
    uses: owner/repo/.github/workflows/deploy.yml@main
    permissions: {}
    secrets: {token: private-secret-token}
'''
        output = await self.call("inspect_github_actions", content=content)
        data = json.loads(output)
        self.assertEqual([event["name"] for event in data["events"]], ["push", "workflow_dispatch", "schedule"])
        self.assertEqual(data["events"][2]["schedules"], ["0 0 * * *"])
        self.assertEqual(data["permissions"]["scopes"], {"contents": "read"})
        self.assertEqual(data["jobs"][0]["runs_on"]["labels"], ["self-hosted", "x64"])
        self.assertEqual(data["jobs"][0]["matrix_axes"], ["python"])
        self.assertEqual(data["jobs"][0]["steps"][0]["uses"], "actions/checkout@v4")
        self.assertTrue(data["jobs"][0]["steps"][1]["run_declared"])
        self.assertEqual(data["jobs"][1]["permissions"]["scopes"], {})
        self.assertIsNone(data["jobs"][1]["runs_on"])
        self.assertEqual(data["dependencies"]["order"], ["test", "deploy"])
        for secret in ("private-input-token", "private-root-token", "private-job-token", "private-with-token",
                       "private-run-token", "private-step-token", "private-secret-token"):
            self.assertNotIn(secret, output)

    async def test_actions_on_string_list_null_events_and_expressions(self):
        for trigger, names in (("push", ["push"]), ("[push, pull_request]", ["push", "pull_request"]),
                               ("{workflow_dispatch: null}", ["workflow_dispatch"])):
            content = f'on: {trigger}\npermissions: read-all\njobs:\n  yes:\n    runs-on: "${{{{ matrix.os }}}}"\n    strategy:\n      matrix: "${{{{ fromJSON(inputs.matrix) }}}}"\n'
            data = json.loads(await self.call("inspect_github_actions", content=content))
            self.assertEqual([event["name"] for event in data["events"]], names)
            self.assertEqual(data["jobs"][0]["id"], "yes")
            self.assertTrue(data["jobs"][0]["matrix_expression"])
            self.assertEqual(data["permissions"]["mode"], "read-all")

    async def test_actions_bounds_and_truncation(self):
        content = "on: push\njobs:\n  a:\n    name: " + "x" * 2001 + "\n    steps:\n      - run: a\n      - run: b\n  b: {needs: a}\n"
        data = json.loads(await self.call("inspect_github_actions", content=content, limit=1, max_steps=1))
        self.assertEqual(data["job_count"], 2)
        self.assertEqual(data["step_count"], 2)
        self.assertEqual(len(data["jobs"]), 1)
        self.assertEqual(len(data["jobs"][0]["steps"]), 1)
        self.assertTrue(data["jobs"][0]["steps_truncated"])
        self.assertTrue(data["truncated"])
        self.assertEqual(len(data["jobs"][0]["name"]), 2000)
        for arguments in ({"limit": 0}, {"limit": 51}, {"max_steps": 0}, {"max_steps": 51}):
            self.assertTrue((await self.call("inspect_github_actions", content=content, **arguments)).startswith("Error:"))

    async def test_actions_invalid_shapes_cycles_and_unknown_dependencies(self):
        for content in ("on: false\njobs: {}", "on: push\njobs: []", "on: push\njobs: {a: null}",
                        "on: push\njobs: {a: {needs: [true]}}", "on: push\njobs: {a: {steps: {}}}",
                        "on: push\njobs: {a: {steps: [{run: [a]}]}}", "on: push\npermissions: {contents: admin}\njobs: {a: {}}",
                        "on: {push: {branches: main}}\njobs: {a: {}}"):
            with self.subTest(content=content):
                self.assertTrue((await self.call("inspect_github_actions", content=content)).startswith("Error:"))
        data = json.loads(await self.call("inspect_github_actions", content="on: push\njobs: {a: {needs: [b, missing]}, b: {needs: a}}"))
        self.assertTrue(data["dependencies"]["has_cycle"])
        self.assertEqual(data["dependencies"]["unknown_dependencies"], [{"name": "a", "dependency": "missing"}])

    async def test_yaml_safety_limits_apply_to_both_tools(self):
        invalid = ["", "[]", "1: value", "!!python/object/apply:builtins.str [unsafe]",
                   "x: .nan", "x: .inf", "a: 1\na: 2", "a: &a [*a]", "a: 1\n---\nb: 2",
                   "x: " + "[" * 51 + "0" + "]" * 51, "x" * 200001,
                   "a: [" + ",".join("x" for _ in range(10001)) + "]"]
        bomb = 'a: &a [' + ','.join('x' for _ in range(50)) + ']\nb: &b [' + ','.join('*a' for _ in range(50)) + ']\nc: [' + ','.join('*b' for _ in range(50)) + ']'
        invalid.append(bomb)
        for name in ("inspect_docker_compose", "inspect_github_actions"):
            for content in invalid:
                with self.subTest(name=name, content=content[:80]):
                    self.assertTrue((await self.call(name, content=content)).startswith("Error:"))

    async def test_new_loader_does_not_change_existing_yaml_boolean_rules(self):
        await self.call("inspect_github_actions", content="on: push\njobs: {yes: {}}")
        data = json.loads(await self.call("yaml_to_json", value="value: yes\n"))
        self.assertEqual(data, {"value": True})
        self.assertEqual(service._load("value: 001\nfloat: 1e3\n"), {"value": 1, "float": 1000.0})

    async def test_yaml_merge_expansion_is_bounded_before_construction(self):
        def merges(alias):
            return "[" + ",".join("*" + alias for _ in range(30)) + "]"

        content = "a: &a {k: v}\nb: &b {<<: " + merges("a") + "}\nc: &c {<<: " + merges("b") + "}\nservices: {web: {<<: " + merges("c") + "}}"
        output = await self.call("inspect_docker_compose", content=content)
        self.assertIn("Expanded configuration exceeds", output)

    async def test_compose_row_limit_and_workflow_total_step_limit(self):
        data = json.loads(await self.call("inspect_docker_compose", content="services: {a: {}, b: {depends_on: [a]}}", limit=1))
        self.assertEqual(data["service_count"], 2)
        self.assertEqual(len(data["services"]), 1)
        self.assertEqual(data["dependencies"]["order"], ["a", "b"])
        self.assertTrue(data["truncated"])
        content = "on: push\njobs:\n  a:\n    steps:\n" + "      - run: echo\n" * 1001
        self.assertIn("1000 total steps", await self.call("inspect_github_actions", content=content))

    async def test_configuration_service_and_job_counts_and_output_caps(self):
        compose = "services: {" + ", ".join(f"s{i}: {{}}" for i in range(101)) + "}"
        workflow = "on: push\njobs: {" + ", ".join(f"j{i}: {{}}" for i in range(101)) + "}"
        self.assertTrue((await self.call("inspect_docker_compose", content=compose)).startswith("Error:"))
        self.assertTrue((await self.call("inspect_github_actions", content=workflow)).startswith("Error:"))
        for name, target in (("inspect_docker_compose", "inspect_compose"), ("inspect_github_actions", "inspect_actions")):
            with patch.object(service, target, return_value={"large": "x" * 100001}):
                self.assertIn("output exceeds", await self.call(name, content="supplied"))


if __name__ == "__main__":
    unittest.main()
