import json
import unittest
from unittest.mock import Mock, patch

from mcp.server.fastmcp import FastMCP

from app.tools.sql_utils import service, tool


class SqlAnalysisTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("sql-analysis-tests")
        tool.register(self.mcp)

    async def call(self, sql, dialect="postgres"):
        result = await self.mcp.call_tool("analyze_sql", {"sql": sql, "dialect": dialect})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_select_joins_and_cte_references(self):
        sql = 'WITH recent AS (SELECT id FROM users) SELECT r.id, o.total FROM recent r JOIN orders o ON r.id = o.user_id'
        result = json.loads(await self.call(sql))
        row = result["statements"][0]
        self.assertEqual(row["type"], "SELECT")
        self.assertEqual(set(row["tables"]), {"users", "recent AS r", "orders AS o"})
        self.assertIn("o.total", row["columns"])
        self.assertEqual(row["ctes"], ["recent"])
        self.assertFalse(row["has_wildcards"])
        self.assertIn("CTE references", result["notice"])

    async def test_multiple_statement_types_and_wildcards(self):
        result = json.loads(await self.call('INSERT INTO target SELECT * FROM source; UPDATE target SET id=2; DELETE FROM target; CREATE TABLE example (id INT); DROP TABLE example; TRUNCATE TABLE target;'))
        self.assertEqual([row["type"] for row in result["statements"]], ["INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "TRUNCATETABLE"])
        self.assertTrue(result["statements"][0]["has_wildcards"])
        self.assertIn("target", result["statements"][0]["tables"])

    async def test_dialect_specific_quoting(self):
        for dialect, sql, expected in (("mysql", 'SELECT `Order ID` FROM `Order Details`', '`Order Details`'),
                                       ("tsql", 'SELECT TOP 1 [Order ID] FROM [Order Details]', '[Order Details]'),
                                       ("bigquery", 'SELECT id FROM `project.dataset.orders`', 'project.dataset.orders')):
            with self.subTest(dialect=dialect):
                result = json.loads(await self.call(sql, dialect))
                self.assertEqual(result["dialect"], dialect)
                self.assertIn(expected, result["statements"][0]["tables"][0].replace('`', '') if dialect == "bigquery" else result["statements"][0]["tables"][0])

    async def test_semicolons_and_comments_do_not_split_strings(self):
        result = json.loads(await self.call("SELECT ';' AS value FROM users; -- comment\nSELECT id FROM users"))
        self.assertEqual(result["statement_count"], 2)
        self.assertFalse(result["truncated"])

    async def test_malformed_unsupported_and_too_many_statements(self):
        for sql in ("SELECT * FROM (", "SELECT FROM", "nonsense xyz", "VACUUM users", "-- comment only", "SELECT 1;" * 11):
            with self.subTest(sql=sql[:30]):
                self.assertTrue((await self.call(sql)).startswith("Error:"))

    async def test_input_limits_and_dialect_rejected_before_spawn(self):
        for sql, dialect in (("", "postgres"), ("x" * 50001, "postgres"), ("SELECT 1", "invalid")):
            with self.subTest(dialect=dialect), patch.object(service.multiprocessing, "get_context") as context:
                self.assertTrue((await self.call(sql, dialect)).startswith("Error:"))
                context.assert_not_called()

    async def test_reference_truncation_and_busy_worker(self):
        result = json.loads(await self.call("SELECT " + ",".join(f"column_{i}" for i in range(101)) + " FROM data"))
        self.assertEqual(len(result["statements"][0]["columns"]), 100)
        self.assertTrue(result["truncated"])
        self.assertTrue(service._SQL_SLOT.acquire(blocking=False))
        try:
            self.assertIn("busy", await self.call("SELECT 1"))
        finally:
            service._SQL_SLOT.release()


class SqlWorkerTests(unittest.TestCase):
    def setUp(self):
        self.receiver, self.sender, self.process = Mock(), Mock(), Mock(pid=123)
        self.context = Mock()
        self.context.Pipe.return_value = (self.receiver, self.sender)
        self.context.Process.return_value = self.process
        self.process.is_alive.return_value = False

    def assert_slot_released(self):
        self.assertTrue(service._SQL_SLOT.acquire(blocking=False))
        service._SQL_SLOT.release()

    def test_timeout_terminates_worker(self):
        self.receiver.poll.return_value = False
        self.process.is_alive.side_effect = [True, False]
        with patch.object(service.multiprocessing, "get_context", return_value=self.context):
            with self.assertRaisesRegex(ValueError, "5-second"):
                service.analyze("SELECT 1", "postgres")
        self.process.terminate.assert_called_once()
        self.receiver.close.assert_called_once()
        self.assert_slot_released()

    def test_crashed_and_failed_start_workers_release_slot(self):
        self.receiver.poll.return_value = True
        self.receiver.recv.side_effect = EOFError()
        with patch.object(service.multiprocessing, "get_context", return_value=self.context):
            with self.assertRaisesRegex(ValueError, "without a result"):
                service.analyze("SELECT 1", "postgres")
        self.assert_slot_released()
        self.process.pid = None
        self.process.start.side_effect = OSError("Cannot start worker")
        with patch.object(service.multiprocessing, "get_context", return_value=self.context):
            with self.assertRaises(OSError):
                service.analyze("SELECT 1", "postgres")
        self.assert_slot_released()

    def test_output_limit_and_ast_depth(self):
        with patch.object(service, "_MAX_OUTPUT", 100):
            with self.assertRaisesRegex(ValueError, "output exceeds"):
                service._analyze("SELECT id FROM users", "postgres")
        from sqlglot import exp

        tree = exp.column("id")
        for _ in range(102):
            tree = exp.Paren(this=tree)
        tree = exp.Select(expressions=[tree])
        with patch("sqlglot.parse", return_value=[tree]):
            with self.assertRaisesRegex(ValueError, "nested levels"):
                service._analyze("SELECT 1", "postgres")


if __name__ == "__main__":
    unittest.main()
