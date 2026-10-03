import json
import unittest
from unittest.mock import Mock, patch

from mcp.server.fastmcp import FastMCP
from sqlglot import exp
from sqlglot.errors import UnsupportedError

from app.tools.sql_utils import development as dev, service, tool


class SqlSchemaTests(unittest.TestCase):
    def inspect(self, ddl, dialect="postgres", limit=20):
        return dev._inspect(ddl, dialect, limit)

    def compare(self, before, after, dialect="postgres", limit=20):
        return dev._compare(before, after, dialect, limit)

    def test_inline_keys_nullability_and_scalar_types(self):
        result = self.inspect('CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(100) NOT NULL UNIQUE, '
                              'team_id INT REFERENCES teams(id), amount NUMERIC(10,2) NULL)')
        row = result["tables"][0]
        self.assertEqual(row["primary_key"]["columns"], ["id"])
        self.assertEqual(row["unique_keys"][0]["columns"], ["name"])
        self.assertEqual(row["foreign_keys"][0]["referenced_table"]["identity"], ["teams"])
        self.assertEqual(row["foreign_keys"][0]["referenced_columns"], ["id"])
        self.assertEqual([column["declared_nullable"] for column in row["columns"]], [None, False, None, True])
        self.assertEqual(row["columns"][3]["type"], "DECIMAL(10, 2)")
        self.assertEqual(result["column_count"], 4)

    def test_named_composite_keys_and_foreign_key_actions(self):
        row = self.inspect('CREATE TABLE public.items (a INT, b INT, '
                           'CONSTRAINT pk PRIMARY KEY(a,b), CONSTRAINT uq UNIQUE(b,a), '
                           'CONSTRAINT fk FOREIGN KEY(a,b) REFERENCES other.items(x,y) ON DELETE CASCADE DEFERRABLE)')["tables"][0]
        self.assertEqual(row["identity"], ["public", "items"])
        self.assertEqual(row["primary_key"], {"name": "pk", "columns": ["a", "b"]})
        self.assertEqual(row["unique_keys"][0]["columns"], ["b", "a"])
        fk = row["foreign_keys"][0]
        self.assertEqual(fk["name"], "fk")
        self.assertEqual(fk["referenced_table"]["identity"], ["other", "items"])
        self.assertEqual(fk["options"], ["DEFERRABLE", "ON DELETE CASCADE"])

    def test_implicit_referenced_key_stays_unspecified(self):
        fk = self.inspect('CREATE TABLE t (id INT REFERENCES external_table)')["tables"][0]["foreign_keys"][0]
        self.assertEqual(fk["referenced_columns"], [])

    def test_default_check_and_comments_omit_values(self):
        result = self.inspect("CREATE TABLE t (id INT DEFAULT 42 CHECK(id>123), token TEXT DEFAULT 'private-marker', "
                              "CHECK(token <> 'hidden-marker')) -- comment-marker")
        text = dev._dump(result)
        for marker in ("private-marker", "hidden-marker", "comment-marker", "123", "42"):
            self.assertNotIn(marker, text)
        self.assertEqual(result["tables"][0]["columns"][0]["check_count"], 1)
        self.assertEqual(result["tables"][0]["columns"][1]["default_count"], 1)
        self.assertEqual(result["tables"][0]["table_check_count"], 1)

    def test_basic_schema_in_all_supported_dialects(self):
        for dialect in sorted(service._DIALECTS):
            with self.subTest(dialect=dialect):
                self.assertEqual(self.inspect('CREATE TABLE users (id INT, name VARCHAR(50))', dialect)["table_count"], 1)

    def test_quoted_names_and_dialect_normalization(self):
        result = self.inspect('CREATE TABLE Foo (Bar INT); CREATE TABLE "Foo" ("Bar" INT)')
        self.assertEqual([row["identity"] for row in result["tables"]], [["foo"], ["Foo"]])
        self.assertEqual(self.inspect('CREATE TABLE Foo (Bar INT)', "snowflake")["tables"][0]["identity"], ["FOO"])
        self.assertEqual(self.inspect('CREATE TABLE `Order Details` (`Order ID` INT)', "mysql")["tables"][0]["columns"][0]["name"], "Order ID")

    def test_qualified_identity_does_not_split_quoted_dots(self):
        result = self.inspect('CREATE TABLE "a.b" (id INT); CREATE TABLE a.b (id INT)')
        self.assertEqual([row["identity"] for row in result["tables"]], [["a.b"], ["a", "b"]])

    def test_schema_rejects_non_snapshot_statements_and_modifiers(self):
        for ddl in ('SELECT 1', 'ALTER TABLE x ADD a INT', 'CREATE VIEW x AS SELECT 1',
                    'CREATE TABLE x AS SELECT 1', 'CREATE TABLE IF NOT EXISTS x(id INT)',
                    'CREATE TEMP TABLE x(id INT)', 'CREATE TABLE x(id INT); DROP TABLE x',
                    'CREATE TABLE x (id INT) PARTITION BY RANGE(id)', 'CREATE TABLE x(id INT GENERATED ALWAYS AS IDENTITY)',
                    'CREATE TABLE x (id INT COLLATE "C")', 'CREATE TABLE x(id INT); CREATE INDEX i ON x(id)'):
            with self.subTest(ddl=ddl), self.assertRaises(ValueError):
                self.inspect(ddl)

    def test_schema_rejects_complex_literal_types_and_no_columns(self):
        for ddl, dialect in (('CREATE TABLE x (v ENUM(\'private-marker\'))', 'mysql'),
                             ('CREATE TABLE x (v STRUCT<a INT>)', 'bigquery'), ('CREATE TABLE x()', 'postgres')):
            with self.subTest(ddl=ddl), self.assertRaises(ValueError):
                self.inspect(ddl, dialect)

    def test_duplicate_table_column_and_constraint_identities_fail(self):
        for ddl in ('CREATE TABLE Foo(id INT); CREATE TABLE foo(id INT)',
                    'CREATE TABLE x(Id INT, id INT)', 'CREATE TABLE x(id INT PRIMARY KEY, PRIMARY KEY(id))',
                    'CREATE TABLE x(id INT, CONSTRAINT same UNIQUE(id), CONSTRAINT same CHECK(id>0))',
                    'CREATE TABLE x(id INT NOT NULL NULL)'):
            with self.subTest(ddl=ddl), self.assertRaises(ValueError):
                self.inspect(ddl)

    def test_invalid_local_keys_and_reference_arity_fail(self):
        for ddl in ('CREATE TABLE x(id INT, PRIMARY KEY(missing))',
                    'CREATE TABLE x(id INT, UNIQUE(id,id))',
                    'CREATE TABLE x(id INT, FOREIGN KEY(missing) REFERENCES t(id))',
                    'CREATE TABLE x(id INT REFERENCES t(a,b))'):
            with self.subTest(ddl=ddl), self.assertRaises(ValueError):
                self.inspect(ddl)

    def test_schema_table_and_column_limits(self):
        for ddl in (';'.join(f'CREATE TABLE t{i}(id INT)' for i in range(51)),
                    'CREATE TABLE t(' + ','.join(f'c{i} INT' for i in range(101)) + ')',
                    ';'.join('CREATE TABLE t' + str(i) + '(' + ','.join(f'c{j} INT' for j in range(100)) + ')' for i in range(11))):
            with self.assertRaises(ValueError):
                self.inspect(ddl)

    def test_display_limit_preserves_complete_schema_counts(self):
        ddl = ';'.join('CREATE TABLE t' + str(i) + '(a INT,b INT,c INT)' for i in range(3))
        result = self.inspect(ddl, limit=1)
        self.assertEqual(result["table_count"], 3)
        self.assertEqual(result["column_count"], 9)
        self.assertEqual(len(result["tables"]), 1)
        self.assertEqual(result["tables"][0]["column_count"], 3)
        self.assertEqual(len(result["tables"][0]["columns"]), 1)
        self.assertTrue(result["truncated"])

    def test_semicolons_in_default_strings_and_trailing_comments(self):
        result = self.inspect("CREATE TABLE x(v TEXT DEFAULT ';'); -- comment\nCREATE TABLE y(id INT); -- trailing")
        self.assertEqual(result["table_count"], 2)

    def test_compare_types_nullability_added_and_removed_columns(self):
        result = self.compare('CREATE TABLE x(id INT, old TEXT)', 'CREATE TABLE x(id BIGINT NOT NULL, new TEXT)')
        self.assertEqual(result["counts"]["changed_columns"], 1)
        self.assertEqual(result["counts"]["added_columns"], 1)
        self.assertEqual(result["counts"]["removed_columns"], 1)
        self.assertFalse(result["selected_fields_equal"])
        self.assertEqual(result["comparisons"][0]["column_changes"][0]["after"]["declared_nullable"], False)

    def test_compare_table_identity_and_no_rename_guess(self):
        result = self.compare('CREATE TABLE "a.b"(id INT)', 'CREATE TABLE a.b(id INT)')
        self.assertEqual(result["matched_table_count"], 0)
        self.assertEqual(result["counts"]["added_tables"], 1)
        self.assertEqual(result["counts"]["removed_tables"], 1)
        self.assertEqual(result["added_tables"][0]["identity"], ["a", "b"])

    def test_compare_ignores_declaration_order_and_omitted_expressions(self):
        before = "CREATE TABLE x(a INT DEFAULT 1,b INT,UNIQUE(a),UNIQUE(b),CHECK(a>0));CREATE TABLE y(id INT)"
        after = "CREATE TABLE y(id INT);CREATE TABLE X(b INT,a INT DEFAULT 999,UNIQUE(b),UNIQUE(a),CHECK(a>999))"
        result = self.compare(before, after)
        self.assertTrue(result["selected_fields_equal"])
        self.assertEqual(result["comparisons"], [])

    def test_compare_selected_constraint_groups(self):
        before = 'CREATE TABLE x(id INT, team INT, PRIMARY KEY(id), UNIQUE(team), FOREIGN KEY(team) REFERENCES a(id))'
        after = 'CREATE TABLE x(id INT, team INT, PRIMARY KEY(team), UNIQUE(id), FOREIGN KEY(team) REFERENCES b(id))'
        result = self.compare(before, after)
        self.assertEqual(result["counts"]["changed_constraint_groups"], 3)
        self.assertEqual(result["counts"]["changed_columns"], 0)

    def test_compare_default_check_presence_and_nulls_policy(self):
        result = self.compare('CREATE TABLE x(id INT, UNIQUE(id))',
                              'CREATE TABLE x(id INT DEFAULT 1, UNIQUE NULLS NOT DISTINCT(id), CHECK(id>0))')
        self.assertEqual(result["counts"]["changed_columns"], 1)
        self.assertEqual(result["counts"]["changed_constraint_groups"], 2)

    def test_compare_changes_beyond_display_limits(self):
        before = ';'.join(f'CREATE TABLE t{i}(a INT,b INT,c INT)' for i in range(3))
        after = ';'.join(f'CREATE TABLE t{i}(a INT,b BIGINT,c BIGINT)' for i in range(3))
        result = self.compare(before, after, limit=1)
        self.assertEqual(result["counts"]["changed_tables"], 3)
        self.assertEqual(result["counts"]["changed_columns"], 6)
        self.assertEqual(len(result["comparisons"]), 1)
        self.assertEqual(len(result["comparisons"][0]["column_changes"]), 1)
        self.assertTrue(result["truncated"])

    def test_compare_added_removed_counts_before_limits(self):
        result = self.compare('CREATE TABLE a(id INT);CREATE TABLE b(id INT)',
                              'CREATE TABLE c(id INT);CREATE TABLE d(id INT)', limit=1)
        self.assertEqual(result["counts"]["added_tables"], 2)
        self.assertEqual(result["counts"]["removed_tables"], 2)
        self.assertEqual(len(result["added_tables"]), 1)
        self.assertTrue(result["truncated"])

    def test_compare_empty_snapshots(self):
        self.assertTrue(self.compare('', ' ')['selected_fields_equal'])
        added = self.compare('', 'CREATE TABLE t(id INT)')
        removed = self.compare('CREATE TABLE t(id INT)', '')
        self.assertEqual(added['counts']['added_tables'], 1)
        self.assertEqual(removed['counts']['removed_tables'], 1)

    def test_key_modifiers_fail_closed(self):
        for ddl, dialect in (('CREATE TABLE x(id INT PRIMARY KEY DESC)', 'sqlite'),
                             ('CREATE TABLE x(id INT, PRIMARY KEY(id) INCLUDE(id))', 'postgres')):
            with self.subTest(ddl=ddl), self.assertRaises(ValueError):
                self.inspect(ddl, dialect)


class SqlTranslationTests(unittest.TestCase):
    def test_translate_tsql_top_and_quotes_to_postgres(self):
        result = dev._transpile('SELECT TOP 2 [id] FROM [users]', 'tsql', 'postgres')
        self.assertEqual(result["statement_count"], 1)
        self.assertIn('"users"', result["statements"][0])
        self.assertIn('LIMIT 2', result["statements"][0])
        self.assertFalse(result["truncated"])

    def test_multiple_statements_preserve_literals_and_omit_comments(self):
        result = dev._transpile("SELECT ';private-marker' AS v; -- comment-marker\nSELECT 2", 'postgres', 'duckdb')
        self.assertEqual(result["statement_count"], 2)
        self.assertIn("';private-marker'", result["statements"][0])
        self.assertNotIn('comment-marker', dev._dump(result))

    def test_translate_scalar_cast_and_ddl(self):
        result = dev._transpile('CREATE TABLE t(id INT); SELECT CAST(id AS TEXT) FROM t', 'postgres', 'sqlite')
        self.assertEqual(result["statement_count"], 2)
        self.assertIn('CREATE TABLE', result["statements"][0])

    def test_known_unsupported_translation_raises(self):
        for sql, source, target in (('SELECT ARRAY[1,2]', 'postgres', 'mysql'),
                                    ('SELECT BIT_AND(id) FROM t', 'postgres', 'sqlite')):
            with self.subTest(sql=sql), self.assertRaises(UnsupportedError):
                dev._transpile(sql, source, target)

    def test_translation_rejects_fallback_and_statement_limits(self):
        for sql in ('VACUUM x', 'nonsense xyz', 'SELECT 1;' * 11, '-- comment only'):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                dev._transpile(sql, 'postgres', 'mysql')

    def test_all_target_dialects(self):
        for dialect in sorted(service._DIALECTS):
            with self.subTest(dialect=dialect):
                self.assertEqual(dev._transpile('SELECT id FROM users', 'postgres', dialect)["statement_count"], 1)


class SqlLineageTests(unittest.TestCase):
    def lineage(self, sql, column="id", schema=None, dialect="postgres", limit=20):
        return dev._lineage(sql, column, dialect, json.dumps(schema or {}), limit)

    def test_alias_and_cte_lineage(self):
        result = self.lineage('WITH recent AS (SELECT id FROM users) SELECT r.id AS user_id FROM recent r', 'user_id')
        self.assertEqual(result["sources"], [{"table": {"identity": ["users"], "name": "users"}, "column": "id"}])
        self.assertTrue(result["column_references_resolved"])

    def test_expression_tracks_multiple_sources(self):
        result = self.lineage('SELECT a.total + b.fee AS amount FROM orders a JOIN fees b ON a.id=b.id', 'amount')
        self.assertEqual(result["source_count"], 2)
        self.assertEqual({row["column"] for row in result["sources"]}, {"total", "fee"})

    def test_union_traces_both_branches(self):
        result = self.lineage('SELECT a.id AS id FROM a UNION ALL SELECT b.other_id FROM b')
        self.assertEqual(result["source_count"], 2)
        self.assertEqual({tuple(row["table"]["identity"]) for row in result["sources"]}, {("a",), ("b",)})

    def test_duplicate_source_dependencies_deduplicate(self):
        result = self.lineage('SELECT u.id + u.id AS id FROM users u')
        self.assertEqual(result["source_count"], 1)

    def test_ambiguous_unqualified_join_column_remains_unknown(self):
        result = self.lineage('SELECT id FROM a JOIN b ON a.id=b.id')
        self.assertFalse(result["column_references_resolved"])
        self.assertEqual(result["source_count"], 0)
        self.assertEqual(result["unresolved"][0]["reason"], 'unresolved_or_ambiguous_reference')

    def test_unknown_alias_is_not_inferred_as_a_struct_field(self):
        result = self.lineage('SELECT a.id + missing.id AS id FROM a')
        self.assertFalse(result["column_references_resolved"])
        self.assertEqual(result["source_count"], 0)
        self.assertEqual(result["unresolved_count"], 1)
        self.assertEqual(result["unresolved"][0]["reason"], 'unknown_qualifier_or_unsupported_struct_reference')

    def test_supplied_schema_resolves_unqualified_join_column(self):
        result = self.lineage('SELECT id FROM a JOIN b ON a.other=b.other', schema={"a": {"id": "INT", "other": "INT"}, "b": {"other": "INT"}})
        self.assertTrue(result["column_references_resolved"])
        self.assertEqual(result["sources"][0]["table"]["identity"], ["a"])

    def test_wildcard_without_metadata_remains_unknown(self):
        for sql in ('SELECT * FROM users', 'WITH x AS (SELECT * FROM users) SELECT id FROM x'):
            with self.subTest(sql=sql):
                result = self.lineage(sql)
                self.assertFalse(result["column_references_resolved"])
                self.assertEqual(result["source_count"], 0)
                self.assertEqual(result["unresolved"][0]["reason"], 'wildcard_requires_schema')

    def test_wildcard_schema_and_qualified_nested_schema(self):
        result = self.lineage('SELECT * FROM public.users', schema={"public": {"users": {"id": "INT", "name": "TEXT"}}})
        self.assertTrue(result["schema_supplied"])
        self.assertTrue(result["column_references_resolved"])
        self.assertEqual(result["sources"][0]["table"]["identity"], ["public", "users"])

    def test_missing_metadata_column_is_not_reported_resolved(self):
        result = self.lineage('SELECT u.missing AS id FROM users u', schema={"users": {"id": "INT"}})
        self.assertFalse(result["column_references_resolved"])
        self.assertEqual(result["unresolved"][0]["reason"], 'qualification_failed')

    def test_constants_and_count_have_no_direct_column_sources(self):
        for sql, column in (('SELECT 42 AS answer', 'answer'), ('SELECT COUNT(*) AS n FROM users', 'n')):
            result = self.lineage(sql, column)
            self.assertEqual(result["source_count"], 0)
            self.assertTrue(result["column_references_resolved"])
            self.assertIn('row counts', ' '.join(result["notes"]))

    def test_quoted_identifiers_and_dot_names_preserved(self):
        result = self.lineage('SELECT u."a.b" AS "Result" FROM "my.table" u', 'Result')
        self.assertEqual(result["sources"][0]["column"], 'a.b')
        self.assertEqual(result["sources"][0]["table"]["identity"], ['my.table'])

    def test_schema_supplied_quoted_identifier(self):
        result = self.lineage('SELECT * FROM "Users"', 'Id', {"\"Users\"": {"\"Id\"": "INT"}})
        self.assertTrue(result["column_references_resolved"])
        self.assertEqual(result["sources"][0]["column"], 'Id')

    def test_lineage_never_returns_expression_literals_or_comments(self):
        result = self.lineage("SELECT CONCAT(u.id, 'private-marker') AS id FROM users u -- comment-marker")
        text = dev._dump(result)
        self.assertNotIn('private-marker', text)
        self.assertNotIn('comment-marker', text)
        self.assertEqual(result["source_count"], 1)

    def test_missing_or_duplicate_output_names_fail(self):
        for sql, column in (('SELECT id FROM users', 'missing'), ('SELECT a.id,b.id FROM a JOIN b ON a.id=b.id', 'id'),
                            ('WITH x AS (SELECT id,id FROM users) SELECT id FROM x', 'id')):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                self.lineage(sql, column)

    def test_non_query_and_duplicate_cte_definitions_fail(self):
        for sql in ('WITH x AS (DELETE FROM users RETURNING id) SELECT id FROM x',
                    'WITH x AS (INSERT INTO users SELECT id FROM t RETURNING id) SELECT id FROM x',
                    'WITH x AS (SELECT id FROM a), X AS (SELECT id FROM b) SELECT id FROM x'):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                self.lineage(sql)

    def test_unsupported_lineage_query_shapes_fail(self):
        for sql in ('UPDATE users SET id=1', 'SELECT id INTO other FROM users', 'SELECT id FROM users;SELECT id FROM users',
                    'WITH RECURSIVE x AS (SELECT id FROM users UNION ALL SELECT id FROM x) SELECT id FROM x',
                    'SELECT t.id FROM users u, LATERAL (SELECT u.id) t',
                    'SELECT id FROM READ_CSV(\'private-marker.csv\')',
                    'SELECT (SELECT a.id FROM a WHERE a.id=b.id) AS id FROM b'):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                self.lineage(sql)

    def test_lineage_counts_before_limits(self):
        result = self.lineage('SELECT a.id+b.id+c.id AS id FROM a CROSS JOIN b CROSS JOIN c', limit=1)
        self.assertEqual(result["source_count"], 3)
        self.assertEqual(len(result["sources"]), 1)
        self.assertTrue(result["truncated"])
        self.assertTrue(result["column_references_resolved"])

    def test_schema_json_invalid_duplicate_nonfinite_and_mixed_depth(self):
        for content in ('[]', '{bad', '{"a":{"id":"INT","id":"TEXT"}}', '{"a":{"id":NaN}}',
                        '{"a":{}}', '{"a":{"id":1}}', '{"a":{"ID":"INT","id":"INT"}}',
                        '{"a":{"id":"INT"},"db":{"b":{"id":"INT"}}}', '{"id":"INT"}',
                        '{"catalog":{"schema":{"extra":{"table":{"id":"INT"}}}}}'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                dev._schema_json(content, 'postgres')

    def test_schema_json_table_and_column_limits(self):
        for schema in ({f't{i}': {'id': 'INT'} for i in range(51)},
                       {'t': {f'c{i}': 'INT' for i in range(101)}},
                       {f't{i}': {f'c{j}': 'INT' for j in range(100)} for i in range(11)}):
            with self.assertRaises(ValueError):
                dev._schema_json(json.dumps(schema), 'postgres')


class SqlDevelopmentMcpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP('sql-development-tests')
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return '\n'.join(item.text for item in content if item.type == 'text')

    async def test_four_tools_through_real_spawned_workers(self):
        result = json.loads(await self.call('inspect_sql_schema', ddl='CREATE TABLE users(id INT PRIMARY KEY)'))
        self.assertEqual(result['tables'][0]['primary_key']['columns'], ['id'])
        result = json.loads(await self.call('compare_sql_schemas', before='CREATE TABLE users(id INT)', after='CREATE TABLE users(id BIGINT)'))
        self.assertEqual(result['counts']['changed_columns'], 1)
        result = json.loads(await self.call('transpile_sql', sql='SELECT TOP 2 [id] FROM [users]', source_dialect='tsql', target_dialect='postgres'))
        self.assertIn('LIMIT 2', result['statements'][0])
        result = json.loads(await self.call('extract_sql_lineage', sql='WITH x AS (SELECT id FROM users) SELECT id FROM x', column='id'))
        self.assertEqual(result['sources'][0]['table']['identity'], ['users'])

    async def test_worker_errors_sanitize_source_and_diagnostic_values(self):
        for name, arguments in (
            ('inspect_sql_schema', {'ddl': "CREATE TABLE x(id INT DEFAULT 'private-marker', ) broken"}),
            ('transpile_sql', {'sql': "SELECT ARRAY['private-marker']", 'source_dialect': 'postgres', 'target_dialect': 'mysql'}),
            ('extract_sql_lineage', {'sql': "SELECT 'private-marker' AS id FROM (", 'column': 'id'})):
            with self.subTest(name=name):
                result = await self.call(name, **arguments)
                self.assertTrue(result.startswith('Error:'))
                self.assertNotIn('private-marker', result)

    async def test_invalid_input_and_dialect_fail_before_worker(self):
        for name, arguments in (
            ('inspect_sql_schema', {'ddl': ''}), ('inspect_sql_schema', {'ddl': 'x' * 50001}),
            ('inspect_sql_schema', {'ddl': 'CREATE TABLE t(id INT)', 'dialect': 'invalid'}),
            ('compare_sql_schemas', {'before': 'CREATE TABLE t(id INT)', 'after': 'x' * 50001}),
            ('inspect_sql_schema', {'ddl': 'CREATE TABLE t(id INT)', 'limit': 51}),
            ('transpile_sql', {'sql': 'SELECT 1', 'source_dialect': 'postgres', 'target_dialect': 'invalid'}),
            ('extract_sql_lineage', {'sql': 'SELECT 1 AS id', 'column': 'id', 'schema_json': 'x' * 50001}),
            ('extract_sql_lineage', {'sql': 'SELECT 1 AS id', 'column': '\n'})):
            with self.subTest(name=name), patch.object(dev.multiprocessing, 'get_context') as context:
                self.assertTrue((await self.call(name, **arguments)).startswith('Error:'))
                context.assert_not_called()

    async def test_shared_busy_slot_with_existing_analyzer(self):
        self.assertTrue(service._SQL_SLOT.acquire(blocking=False))
        try:
            self.assertIn('busy', await self.call('inspect_sql_schema', ddl='CREATE TABLE t(id INT)'))
            self.assertIn('busy', await self.call('analyze_sql', sql='SELECT 1'))
        finally:
            service._SQL_SLOT.release()


class SqlDevelopmentWorkerTests(unittest.TestCase):
    def setUp(self):
        self.receiver, self.sender, self.process = Mock(), Mock(), Mock(pid=123)
        self.context = Mock()
        self.context.Pipe.return_value = (self.receiver, self.sender)
        self.context.Process.return_value = self.process
        self.process.is_alive.return_value = False
        self.arguments = {'ddl': 'CREATE TABLE t(id INT)', 'dialect': 'postgres', 'limit': 20}

    def assert_slot_released(self):
        self.assertTrue(service._SQL_SLOT.acquire(blocking=False))
        service._SQL_SLOT.release()

    def test_timeout_terminate_then_kill(self):
        self.receiver.poll.return_value = False
        self.process.is_alive.side_effect = [True, True]
        with patch.object(dev.multiprocessing, 'get_context', return_value=self.context):
            with self.assertRaisesRegex(ValueError, '5-second'):
                dev.run('inspect', self.arguments)
        self.process.terminate.assert_called_once()
        self.process.kill.assert_called_once()
        self.process.close.assert_called_once()
        self.receiver.close.assert_called_once()
        self.assert_slot_released()

    def test_worker_eof_error_and_context_failure_release_slot(self):
        self.receiver.poll.return_value = True
        self.receiver.recv.side_effect = EOFError()
        with patch.object(dev.multiprocessing, 'get_context', return_value=self.context):
            with self.assertRaisesRegex(ValueError, 'without a result'):
                dev.run('inspect', self.arguments)
        self.assert_slot_released()
        with patch.object(dev.multiprocessing, 'get_context', side_effect=OSError('no context')):
            with self.assertRaises(OSError):
                dev.run('inspect', self.arguments)
        self.assert_slot_released()

    def test_failed_start_closes_pipes_and_releases_slot(self):
        self.process.pid = None
        self.process.start.side_effect = OSError('no process')
        with patch.object(dev.multiprocessing, 'get_context', return_value=self.context):
            with self.assertRaises(OSError):
                dev.run('inspect', self.arguments)
        self.sender.close.assert_called_once()
        self.receiver.close.assert_called_once()
        self.process.join.assert_not_called()
        self.assert_slot_released()

    def test_parent_rejects_oversized_worker_output_and_error_payload(self):
        self.receiver.poll.return_value = True
        for payload in ({'result': 'x' * 100001}, {'error': 'bounded error'}, {'result': None}):
            self.receiver.recv.return_value = payload
            with patch.object(dev.multiprocessing, 'get_context', return_value=self.context):
                with self.assertRaises(ValueError):
                    dev.run('inspect', self.arguments)
            self.assert_slot_released()

    def test_success_uses_spawn_and_returns_complete_output(self):
        self.receiver.poll.return_value = True
        self.receiver.recv.return_value = {'result': '{}'}
        with patch.object(dev.multiprocessing, 'get_context', return_value=self.context) as context:
            self.assertEqual(dev.run('inspect', self.arguments), '{}')
        context.assert_called_once_with('spawn')
        self.assert_slot_released()

    def test_worker_serialization_limit_and_error_redaction(self):
        sender = Mock()
        with patch.object(dev, '_MAX_OUTPUT', 10):
            dev._worker(sender, 'inspect', self.arguments)
        self.assertIn('output exceeds', sender.send.call_args[0][0]['error'])
        sender = Mock()
        with patch.object(dev, '_inspect', side_effect=ValueError('private-marker')):
            dev._worker(sender, 'inspect', self.arguments)
        self.assertNotIn('private-marker', sender.send.call_args[0][0]['error'])
        sender.close.assert_called_once()

    def test_ast_node_and_depth_limits(self):
        with self.assertRaisesRegex(ValueError, 'AST nodes'):
            dev._bound_ast([exp.Select(expressions=[exp.column('id') for _ in range(5001)])])
        tree = exp.column('id')
        for _ in range(102):
            tree = exp.Paren(this=tree)
        with self.assertRaisesRegex(ValueError, 'nested levels'):
            dev._bound_ast([tree])

    def test_invalid_identifier_controls_length_and_boolean_limit(self):
        for name in ('', 'a' * 201, 'a\x00', 'a\x7f'):
            with self.assertRaises(ValueError):
                dev._name(name)
        with self.assertRaisesRegex(ValueError, 'integer'):
            dev.run('inspect', {**self.arguments, 'limit': True})


if __name__ == '__main__':
    unittest.main()
