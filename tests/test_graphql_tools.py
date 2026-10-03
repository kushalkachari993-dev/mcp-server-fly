import json
import unittest
from unittest.mock import MagicMock, patch

from graphql import GraphQLError
from graphql.language import NameNode
from mcp.server.fastmcp import FastMCP

from app.tools.graphql_utils import service, tool


SCHEMA = '''
schema { query: Root mutation: Mutation subscription: Subscription }
directive @tag(label: String = "DIRECTIVE_SECRET") repeatable on FIELD_DEFINITION | OBJECT
scalar Date @specifiedBy(url: "https://PRIVATE_URL")
interface Node { id: ID! }
type User implements Node { id: ID! old: String @deprecated(reason: "DEPRECATION_SECRET") }
union Result = User
enum Status { ACTIVE OLD @deprecated(reason: "ENUM_SECRET") }
input Filter { term: String = "DEFAULT_SECRET" old: String @deprecated }
"DESCRIPTION_SECRET"
type Root { user(id: ID!, filter: Filter, legacy: String @deprecated): User result: Result date: Date status: Status size: Int }
type Mutation { update(id: ID!): Boolean! }
type Subscription { changed: User }
'''


class GraphQLTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("graphql-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_mcp_inspector_roots_fields_arguments_and_deprecations(self):
        text = await self.call("inspect_graphql_schema", schema_sdl=SCHEMA)
        result = json.loads(text)
        self.assertEqual(result["operation_roots"], {"query": "Root", "mutation": "Mutation", "subscription": "Subscription"})
        types = {row["name"]: row for row in result["types"]}
        self.assertEqual(types["Root"]["fields"][0]["arguments"][0],
                         {"name": "id", "type": "ID!", "required": True, "deprecated": False, "has_default": False})
        self.assertEqual(types["User"]["interfaces"], ["Node"])
        self.assertEqual(types["Result"]["members"], ["User"])
        self.assertTrue(types["Filter"]["fields"][0]["has_default"])
        self.assertEqual(result["deprecated_counts"], {"fields": 1, "arguments": 1, "input_fields": 1, "enum_values": 1})
        for secret in ("DIRECTIVE_SECRET", "PRIVATE_URL", "DEPRECATION_SECRET", "ENUM_SECRET", "DEFAULT_SECRET", "DESCRIPTION_SECRET"):
            self.assertNotIn(secret, text)
        self.assertFalse(any(name.startswith("__") for name in types))

    async def test_mcp_operation_document_validated_without_execution(self):
        document = 'query Get($id: ID!) { user(id: $id) { ...UserFields } } fragment UserFields on User { id }'
        result = json.loads(await self.call("validate_graphql_operation", schema_sdl=SCHEMA, document=document))
        self.assertTrue(result["valid"])
        self.assertEqual(result["operation_count"], 1)
        self.assertEqual(result["fragment_count"], 1)
        self.assertEqual(result["operations"][0]["variables"], [{"name": "id", "has_default": False}])
        self.assertEqual(result["errors"], [])

    async def test_mcp_schema_comparison_breaking_and_dangerous_changes(self):
        before = 'enum E { A } type Query { old: String f(x: Int): E }'
        after = 'enum E { A B } type Query { f(x: Int, required: ID!): E }'
        result = json.loads(await self.call("compare_graphql_schemas", before_sdl=before, after_sdl=after))
        self.assertEqual({row["kind"] for row in result["breaking_changes"]}, {"FIELD_REMOVED", "REQUIRED_ARG_ADDED"})
        self.assertEqual({row["kind"] for row in result["dangerous_changes"]}, {"VALUE_ADDED_TO_ENUM"})
        self.assertEqual(result["breaking_change_count"], 2)

    async def test_library_validation_rules_cover_field_args_variables_and_fragments(self):
        examples = {
            '{ nope }': "FieldsOnCorrectTypeRule", '{ user { id } }': "ProvidedRequiredArgumentsRule",
            'query X($id: Int) { user(id: $id) { id } }': "VariablesInAllowedPositionRule",
            '{ user(id: "x", invalid: 1) { id } }': "KnownArgumentNamesRule",
            '{ user(id: "x") { ...Missing } }': "KnownFragmentNamesRule",
            'query X($unused: String) { date }': "NoUnusedVariablesRule",
        }
        for document, rule in examples.items():
            result = service._validate(SCHEMA, document, 50)
            self.assertFalse(result["valid"])
            self.assertIn(rule, {row["rule"] for row in result["errors"]})

    async def test_mutations_subscriptions_and_all_operations_checked(self):
        result = service._validate(SCHEMA, 'mutation Change { update(id: "x") } subscription Watch { changed { id } }', 1)
        self.assertTrue(result["valid"])
        self.assertEqual(result["operation_count"], 2)
        self.assertEqual(result["operations"][0]["operation"], "mutation")
        self.assertTrue(result["truncated"])
        result = service._validate(SCHEMA, 'query Good { date } query Bad { nope }', 1)
        self.assertFalse(result["valid"])

    async def test_literal_default_and_syntax_diagnostics_do_not_echo_values(self):
        schema = 'type Query { f(x: Int): Int }'
        result = service._validate(schema, '{ f(x: "LITERAL_SECRET") }', 50)
        self.assertFalse(result["valid"])
        self.assertIn("ValuesOfCorrectTypeRule", {row["rule"] for row in result["errors"]})
        self.assertNotIn("LITERAL_SECRET", json.dumps(result))
        result = service._validate(schema, 'query Q($x: Int = "DEFAULT_SECRET") { f(x: $x) }', 50)
        self.assertFalse(result["valid"])
        self.assertNotIn("DEFAULT_SECRET", json.dumps(result))
        result = service._validate(schema, '{ f(x: "SYNTAX_SECRET)', 50)
        self.assertEqual(result["phase"], "syntax")
        self.assertEqual(result["errors"][0]["rule"], "SyntaxError")
        self.assertNotIn("SYNTAX_SECRET", json.dumps(result))

    async def test_validation_reports_locations_but_not_entire_source(self):
        result = service._validate('type Query { hello: String }', '{\n nope\n}', 20)
        self.assertEqual(result["errors"][0]["locations"], [{"line": 2, "column": 2}])
        self.assertEqual(result["errors"][0]["identifiers"], ["nope"])
        self.assertEqual(result["errors"][0]["node_kinds"], ["field"])

    async def test_fragment_cycles_and_field_conflicts_are_library_errors(self):
        for document, rule in (('query Q { ...F } fragment F on Query { ...F }', "NoFragmentCyclesRule"),
                               ('{ x: hello x: other }', "OverlappingFieldsCanBeMergedRule")):
            result = service._validate('type Query { hello: String other: Int }', document, 50)
            self.assertIn(rule, {row["rule"] for row in result["errors"]})

    async def test_fragment_only_and_type_definitions_are_not_valid_operations(self):
        for document in ('fragment F on Query { hello }', 'type Other { value: String }'):
            result = service._validate('type Query { hello: String }', document, 50)
            self.assertFalse(result["valid"])
            self.assertIn("ExecutableOperationRequired", {row["rule"] for row in result["errors"]})

    async def test_errors_are_capped_independently_of_output_limit(self):
        result = service._validate('type Query { hello: String }', '{ ' + ' '.join(f"bad{number}" for number in range(100)) + ' }', 1)
        self.assertEqual(result["error_count"], 51)
        self.assertTrue(result["errors_capped"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertTrue(result["truncated"])

    async def test_inspection_limits_apply_to_nested_fields_arguments_and_directives(self):
        result = service._inspect('type Query { f(a: Int, b: Int): String other: String }', 1)
        self.assertEqual(result["field_count"], 2)
        self.assertEqual(result["field_argument_count"], 2)
        self.assertEqual(len(result["types"]), 1)
        self.assertEqual(len(result["types"][0]["fields"]), 1)
        self.assertEqual(len(result["types"][0]["fields"][0]["arguments"]), 1)
        self.assertTrue(result["truncated"])

    async def test_specified_and_custom_scalars_directives_are_identified(self):
        result = service._inspect('directive @custom on FIELD scalar Any type Query { f: Any s: String }', 50)
        types = {row["name"]: row for row in result["types"]}
        self.assertFalse(types["Any"]["specified_scalar"])
        self.assertTrue(types["String"]["specified_scalar"])
        directives = {row["name"]: row for row in result["directives"]}
        self.assertFalse(directives["custom"]["specified"])
        self.assertTrue(directives["include"]["specified"])

    async def test_schema_extensions_are_merged_not_skipped(self):
        result = service._inspect('type Query { a: String } extend type Query { b: Int }', 50)
        self.assertEqual(result["field_count"], 2)

    async def test_invalid_schemas_and_defaults_have_fixed_errors(self):
        schemas = ('type Query { x: Missing }', 'type Query { x: String x: Int }', 'type User { x: String }',
                   'type Query { x(a: Int = "DEFAULT_SECRET"): String }',
                   'input I { x: Int! = null } type Query { x(i: I): String }',
                   'type Query { x: String @unknown }', 'type Query { x: String } PRIVATE_SECRET')
        for schema in schemas:
            with self.assertRaisesRegex(ValueError, "Invalid GraphQL schema SDL") as error:
                service._build(schema)
            self.assertNotIn("SECRET", str(error.exception))

    async def test_default_change_descriptions_are_redacted(self):
        result = service._compare('type Query { f(x: String = "OLD_SECRET"): String }',
                                  'type Query { f(x: String = "NEW_SECRET"): String }', 50)
        self.assertEqual(result["dangerous_changes"][0]["kind"], "ARG_DEFAULT_VALUE_CHANGE")
        self.assertNotIn("OLD_SECRET", json.dumps(result))
        self.assertNotIn("NEW_SECRET", json.dumps(result))

    async def test_removed_required_input_fields_enum_and_type_changes(self):
        before = 'enum E { A B } input I { x: Int } type Query { f(i: I): E }'
        after = 'enum E { A } input I { x: String required: Int! } type Query { f(i: I): E }'
        result = service._compare(before, after, 50)
        self.assertEqual({row["kind"] for row in result["breaking_changes"]},
                         {"VALUE_REMOVED_FROM_ENUM", "FIELD_CHANGED_KIND", "REQUIRED_INPUT_FIELD_ADDED"})

    async def test_root_changes_are_separate_review_items(self):
        before = 'schema { query: A } type A { x: String } type B { x: String }'
        after = 'schema { query: B mutation: M } type A { x: String } type B { x: String } type M { x: String }'
        result = service._compare(before, after, 50)
        self.assertEqual(result["root_change_count"], 2)
        self.assertEqual(result["root_changes"][0]["kind"], "root_replaced")
        self.assertEqual(result["root_changes"][1]["kind"], "root_added")
        self.assertEqual(result["breaking_change_count"], 0)
        self.assertEqual(result["added_types"], ["M"])

    async def test_comparison_counts_cover_changes_beyond_limit(self):
        before = 'type Query { ' + ' '.join(f"old{number}: String" for number in range(60)) + ' }'
        result = service._compare(before, 'type Query { replacement: String }', 1)
        self.assertEqual(result["breaking_change_count"], 60)
        self.assertEqual(len(result["breaking_changes"]), 1)
        self.assertTrue(result["truncated"])
        self.assertEqual(service._compare(before, before, 50)["breaking_change_count"], 0)

    async def test_depth_token_definition_node_and_name_guards(self):
        values = (('{ f(x: ' + '[' * 51 + '1' + ']' * 51 + ') }', 4000, "nesting"),
                  ('{ ' + ' '.join('f' for _ in range(4001)) + ' }', 4000, "tokens"),
                  (' '.join(f'scalar S{number}' for number in range(201)), 8000, "definitions"),
                  ('type Query { ' + 'x' * 1001 + ': String }', 8000, "names"))
        for content, tokens, reason in values:
            with self.assertRaisesRegex(ValueError, reason):
                service._parse(content, tokens)
        huge_ast = MagicMock(definitions=(), keys=("children",), children=tuple(NameNode(value="x") for _ in range(10001)))
        with patch.object(service, "parse", return_value=huge_ast):
            with self.assertRaisesRegex(ValueError, "AST nodes"):
                service._parse('{ f }', 4000)

    async def test_input_and_limit_bounds_before_worker_start(self):
        calls = ((service.inspect_schema, ('type Query { x: String }',)),
                 (service.validate_operation, ('type Query { x: String }', '{ x }')),
                 (service.compare_schemas, ('type Query { x: String }',) * 2))
        with patch.object(service, "_run_worker", side_effect=AssertionError("worker")):
            for function, arguments in calls:
                for limit in (True, 0, 51, 1.5, "1"):
                    with self.assertRaises(ValueError):
                        function(*arguments, limit)
                for position in range(len(arguments)):
                    for content in (None, {}, "x" * 200001):
                        invalid = list(arguments)
                        invalid[position] = content
                        with self.assertRaises(ValueError):
                            function(*invalid, 1)

    async def test_no_resolver_network_file_or_command_access_in_core(self):
        with patch("builtins.open", side_effect=AssertionError("file")), patch("requests.get", side_effect=AssertionError("network")), \
                patch("socket.getaddrinfo", side_effect=AssertionError("DNS")), patch("subprocess.run", side_effect=AssertionError("command")), \
                patch("graphql.execute", side_effect=AssertionError("resolver")), patch("graphql.graphql_sync", side_effect=AssertionError("execute")):
            self.assertTrue(service._inspect(SCHEMA, 20)["valid_schema"])
            self.assertTrue(service._validate(SCHEMA, '{ date }', 20)["valid"])
            self.assertEqual(service._compare(SCHEMA, SCHEMA, 20)["breaking_change_count"], 0)

    async def test_worker_busy_rejects_and_releases_slot_after_context_failure(self):
        service._WORKER_SLOT.acquire()
        try:
            with self.assertRaisesRegex(ValueError, "busy"):
                service.inspect_schema('type Query { x: String }', 1)
        finally:
            service._WORKER_SLOT.release()
        with patch.object(service.multiprocessing, "get_context", side_effect=OSError("PRIVATE_SECRET")):
            with self.assertRaisesRegex(ValueError, "could not start") as error:
                service.inspect_schema('type Query { x: String }', 1)
        self.assertNotIn("PRIVATE_SECRET", str(error.exception))
        self.assertTrue(service._WORKER_SLOT.acquire(blocking=False))
        service._WORKER_SLOT.release()

    async def test_worker_timeout_terminates_and_cleans_up(self):
        receiver, sender, process, context = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        receiver.poll.return_value = False
        process.pid = 1
        process.is_alive.side_effect = [True, False]
        context.Pipe.return_value = (receiver, sender)
        context.Process.return_value = process
        with patch.object(service.multiprocessing, "get_context", return_value=context):
            with self.assertRaisesRegex(ValueError, "five-second"):
                service.inspect_schema('type Query { x: String }', 1)
        process.terminate.assert_called_once()
        receiver.close.assert_called_once()
        process.close.assert_called_once()
        self.assertTrue(service._WORKER_SLOT.acquire(blocking=False))
        service._WORKER_SLOT.release()

    async def test_worker_eof_and_start_failures_are_sanitized(self):
        for phase in ("start", "recv"):
            receiver, sender, process, context = MagicMock(), MagicMock(), MagicMock(), MagicMock()
            context.Pipe.return_value = receiver, sender
            context.Process.return_value = process
            process.pid = None
            if phase == "start":
                process.start.side_effect = OSError("START_SECRET")
            else:
                receiver.recv.side_effect = EOFError("EOF_SECRET")
            with patch.object(service.multiprocessing, "get_context", return_value=context):
                with self.assertRaisesRegex(ValueError, "worker exited") as error:
                    service.inspect_schema('type Query { x: String }', 1)
            self.assertNotIn("SECRET", str(error.exception))
            process.close.assert_called_once()

    async def test_unexpected_library_errors_do_not_echo_literal_values(self):
        sender = MagicMock()
        with patch.object(service, "_resource_limits"), patch.object(service, "_inspect", side_effect=ValueError("PRIVATE_LITERAL")):
            service._worker(sender, "inspect", ('type Query { x: String }', 1))
        self.assertNotIn("PRIVATE_LITERAL", json.dumps(sender.send.call_args.args[0]))
        self.assertIn("error", sender.send.call_args.args[0])

    async def test_worker_and_outer_output_caps(self):
        sender = MagicMock()
        with patch.object(service, "_resource_limits"), patch.object(service, "_inspect", return_value={"data": "x" * 100001}):
            service._worker(sender, "inspect", ('type Query { x: String }', 1))
        self.assertIn("100000", sender.send.call_args.args[0]["error"])
        fields = ' '.join(f'field{number}' + 'x' * 900 + '(arg' + 'y' * 900 + ': String): String' for number in range(60))
        result = await self.call("inspect_graphql_schema", schema_sdl='type Query { ' + fields + ' }', limit=50)
        self.assertTrue(result.startswith("Error:"))
        self.assertTrue(json.loads(await self.call("inspect_graphql_schema", schema_sdl='type Query { ' + fields + ' }', limit=1))["truncated"])


if __name__ == "__main__":
    unittest.main()
