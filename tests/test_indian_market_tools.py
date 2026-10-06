import json
import os
import unittest
from datetime import datetime
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from mcp.server.fastmcp import FastMCP

from app.tools.indian_market import service, tool


ISIN = "INE002A01018"
KEY = "NSE_EQ|" + ISIN
INDEX = "NSE_INDEX|Nifty 50"
TOKEN = "test-only-analytics-token"
TOOLS = {
    "search_indian_stocks", "get_indian_market_quotes", "get_indian_stock_history",
    "get_indian_company_profile", "get_indian_financial_statements", "get_indian_stock_ratios",
    "get_indian_shareholding", "get_indian_corporate_actions", "get_indian_market_calendar",
    "get_indian_option_chain", "get_indian_fii_dii_activity", "get_indian_stock_news", "get_indian_ipos",
}


class IndianMarketTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("indian-market-tests")
        tool.register(self.mcp)
        self.env_patch = patch.dict(os.environ, {"UPSTOX_ANALYTICS_TOKEN": TOKEN})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    async def call(self, name, **args):
        result = await self.mcp.call_tool(name, args)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def response(self, name, data, metadata=None, **args):
        payload = {"status": "success", "data": data, **(metadata or {})}
        with patch.object(service, "request_public", return_value=(
                200, {"Content-Type": "application/json; charset=utf-8"},
                json.dumps(payload).encode(), "https://api.upstox.com/ignored")) as request:
            value = json.loads(await self.call(name, **args))
        return value, request

    def request_parts(self, request):
        parts = urlsplit(request.call_args.args[0])
        self.assertEqual(parts.scheme, "https")
        self.assertEqual(parts.netloc, "api.upstox.com")
        self.assertEqual(request.call_args.kwargs["method"], "GET")
        self.assertEqual(request.call_args.kwargs["allowed_host"], "api.upstox.com")
        self.assertFalse(request.call_args.kwargs["follow_redirects"])
        self.assertEqual(request.call_args.kwargs["timeout_seconds"], 15)
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer " + TOKEN)
        self.assertNotIn(TOKEN, parts.geturl())
        request.assert_called_once()
        return parts.path, parse_qs(parts.query)

    async def test_thirteen_tools_registered_with_typed_inputs(self):
        catalog = await self.mcp.list_tools()
        self.assertEqual({item.name for item in catalog}, TOOLS)
        history = next(item for item in catalog if item.name == "get_indian_stock_history")
        self.assertEqual(set(history.inputSchema["required"]), {"instrument_key", "from_date", "to_date"})
        self.assertNotIn("token", history.inputSchema["properties"])
        for item in catalog:
            self.assertTrue(item.annotations.readOnlyHint)
            self.assertFalse(item.annotations.destructiveHint)

    async def test_search_filters_pagination_and_provenance(self):
        data = [{"instrument_key": KEY, "isin": ISIN, "exchange": "NSE"}]
        meta = {"meta_data": {"page": {"page_number": 2, "total_pages": 3, "total_records": 21}}}
        value, request = await self.response("search_indian_stocks", data, meta,
                                              query="Reliance & Industries", exchange="both", limit=10, page=2)
        path, params = self.request_parts(request)
        self.assertEqual(path, "/v2/instruments/search")
        self.assertEqual(params, {"query": ["Reliance & Industries"], "exchanges": ["NSE,BSE"],
                                  "segments": ["EQ"], "records": ["10"], "page_number": ["2"]})
        self.assertEqual(value["data"], data)
        self.assertTrue(value["has_more"])
        self.assertEqual(value["next_page"], 3)
        self.assertEqual(value["provider_metadata"], meta)
        self.assertEqual(value["exchange_timezone"], "Asia/Kolkata")
        self.assertIsNotNone(datetime.fromisoformat(value["fetched_at"]).utcoffset())
        self.assertNotIn(TOKEN, json.dumps(value))

    async def test_search_shortening_and_unknown_page_count_are_explicit(self):
        value, _ = await self.response("search_indian_stocks", [{}, {}], query="NIFTY", segment="INDEX", limit=1)
        self.assertTrue(value["truncated"])
        self.assertEqual(value["received_items"], 2)
        self.assertEqual(value["returned_items"], 1)
        self.assertIsNone(value["has_more"])
        value, _ = await self.response("search_indian_stocks", [],
                                       {"meta_data": {"page": {"total_pages": 101}}}, query="RELIANCE", page=100)
        self.assertTrue(value["has_more"])
        self.assertIsNone(value["next_page"])

    async def test_quotes_preserve_depth_dates_nulls_and_missing_instruments(self):
        data = {"NSE_EQ:" + ISIN: {"instrument_token": KEY, "last_price": 0, "prev_close_price": None,
                                  "timestamp": "2026-10-05T15:30:00+05:30",
                                  "depth": {"buy": [{"price": 100, "quantity": 5}]}}}
        value, request = await self.response("get_indian_market_quotes", data,
                                              instrument_keys=KEY + "," + INDEX + "," + KEY)
        path, params = self.request_parts(request)
        self.assertEqual(path, "/v3/market-quote/quotes")
        self.assertEqual(params["instrument_key"], [KEY + "," + INDEX])
        self.assertEqual(value["data"], data)
        self.assertEqual(value["missing_instrument_keys"], [INDEX])
        self.assertEqual(value["price_currency"], "INR")

    async def test_history_encodes_keys_sorts_by_instant_and_selects_latest(self):
        rows = [["2026-10-03T09:15:00+05:30", 11, 12, 10, 11.5, 300, 20],
                ["2026-10-01T09:15:00+05:30", 9, 10, 8, 9.5, 100],
                ["2026-10-02T03:45:00+00:00", 10, 11, 9, 10.5, 200, 0]]
        value, request = await self.response("get_indian_stock_history", {"candles": rows},
                                              instrument_key=INDEX, from_date="2026-10-01",
                                              to_date="2026-10-03", limit=2)
        path, _ = self.request_parts(request)
        self.assertEqual(path, "/v3/historical-candle/NSE_INDEX%7CNifty%2050/days/1/2026-10-03/2026-10-01")
        self.assertEqual([row["close"] for row in value["data"]["candles"]], [10.5, 11.5])
        self.assertEqual(value["received_candles"], 3)
        self.assertTrue(value["truncated"])
        self.assertEqual(value["order"], "oldest_first")
        value, _ = await self.response("get_indian_stock_history", {"candles": [rows[1]]},
                                       instrument_key=KEY, from_date="2026-10-01", to_date="2026-10-01")
        self.assertIsNone(value["data"]["candles"][0]["open_interest"])

    async def test_history_rejects_invalid_rows_timestamps_and_duplicates(self):
        base = ["2026-10-01T09:15:00+05:30", 9, 10, 8, 9.5, 100, 0]
        cases = [[base, base], [["2026-10-01", *base[1:]]],
                 [[base[0], True, *base[2:]]], [[*base[:5], -1, 0]],
                 [[*base[:6], None]], [{"close": 9.5}]]
        for rows in cases:
            with self.subTest(rows=rows), patch.object(service, "request_public", return_value=(
                    200, {"Content-Type": "application/json"},
                    json.dumps({"status": "success", "data": {"candles": rows}}).encode(), "")):
                result = await self.call("get_indian_stock_history", instrument_key=KEY,
                                         from_date="2026-10-01", to_date="2026-10-01")
                self.assertTrue(result.startswith("Error:"))

    async def test_profile_ratios_and_shareholdings_preserve_provider_units(self):
        cases = [("get_indian_company_profile", "profile", {"sector": "Refineries",
                   "sector_market_cap_inr": {"value": 12, "unit": "crore"},
                   "sector_market_cap_usd": {"value": 1, "unit": "billion"}}),
                 ("get_indian_stock_ratios", "key-ratios", [{"name": "ROE", "company_value": "8.94%", "sector_value": None}]),
                 ("get_indian_shareholding", "share-holdings", [{"category": "promoters", "history": [{"period": "Mar 2026", "value": 50}]}])]
        for name, resource, data in cases:
            with self.subTest(tool=name):
                value, request = await self.response(name, data, isin=ISIN.lower())
                path, params = self.request_parts(request)
                self.assertEqual(path, f"/v2/fundamentals/{ISIN}/{resource}")
                self.assertEqual(params, {})
                self.assertEqual(value["data"], data)

    async def test_financial_statement_selectors_match_supported_endpoints(self):
        for statement in ("income_statement", "balance_sheet", "cash_flow"):
            with self.subTest(statement=statement):
                period = "quarterly" if statement == "income_statement" else "yearly"
                value, request = await self.response("get_indian_financial_statements", {"time_period": period},
                    isin=ISIN, statement=statement, statement_type="standalone", time_period=period, full_statement=True)
                path, params = self.request_parts(request)
                self.assertEqual(path, f"/v2/fundamentals/{ISIN}/{statement.replace('_', '-')}")
                self.assertEqual(params["type"], ["standalone"])
                self.assertEqual(params["fs"], ["true"])
                self.assertEqual("time_period" in params, statement == "income_statement")
                self.assertIn("crore", value["monetary_amount_unit"])

    async def test_corporate_actions_and_option_chain_shortening(self):
        value, request = await self.response("get_indian_corporate_actions",
                                              [{"name": "Dividend", "ratio": None}, {"name": "Split"}], isin=ISIN, limit=1)
        path, _ = self.request_parts(request)
        self.assertTrue(path.endswith("/corporate-actions"))
        self.assertTrue(value["truncated"])
        value, request = await self.response("get_indian_option_chain",
                                              [{"strike_price": 24000}, {"strike_price": 24050}],
                                              instrument_key=INDEX, expiry_date="next_month", limit=1)
        path, params = self.request_parts(request)
        self.assertEqual(path, "/v2/option/chain")
        self.assertEqual(params, {"instrument_key": [INDEX], "expiry_date": ["next_month"]})
        self.assertEqual(value["returned_strikes"], 1)
        self.assertTrue(value["truncated"])

    async def test_calendar_modes_and_ist_default(self):
        for kind, date_value, data, expected_path in [
                ("status", "", {"exchange": "BSE", "status": "NORMAL_CLOSE"}, "/v2/market/status/BSE"),
                ("timings", "2026-10-05", [{"exchange": "MCX", "start_time": 100}], "/v2/market/timings/2026-10-05"),
                ("holidays", "", [], "/v2/market/holidays"),
                ("holidays", "2026-10-02", [{"date": "2026-10-02"}], "/v2/market/holidays/2026-10-02")]:
            with self.subTest(kind=kind, date=date_value):
                value, request = await self.response("get_indian_market_calendar", data,
                                                      kind=kind, exchange="BSE", date=date_value)
                self.assertEqual(self.request_parts(request)[0], expected_path)
                self.assertEqual(value["data"], data)
        with patch.object(service, "datetime") as clock:
            clock.now.return_value = datetime.fromisoformat("2026-10-06T00:15:00+05:30")
            _, request = await self.response("get_indian_market_calendar", [], kind="timings")
            self.assertTrue(self.request_parts(request)[0].endswith("/2026-10-06"))
            self.assertEqual(clock.now.call_args_list[0].args[0].utcoffset(None).total_seconds(), 19800)

    async def test_institutional_endpoints_and_coverage(self):
        for investor, segment in [("FII", "NSE_FO|INDEX_FUTURES"), ("DII", "NSE_EQ|CASH")]:
            value, request = await self.response("get_indian_fii_dii_activity", {segment: [{"buy_amount": 12}]},
                investor=investor, segment=segment, interval="1M", from_date="2026-04-01")
            path, params = self.request_parts(request)
            self.assertEqual(path, "/v2/market/" + investor.lower())
            self.assertEqual(params, {"data_type": [segment], "interval": ["1M"], "from": ["2026-04-01"]})
            self.assertEqual(value["coverage_start"], "2026-04-01")

    async def test_news_only_uses_public_instrument_category(self):
        data = {KEY: [{"heading": "News", "summary": "Summary", "published_time": 123, "article_link": "https://example.org/news"}]}
        meta = {"metadata": {"page": {"total_pages": 3, "page_number": 2}}}
        value, request = await self.response("get_indian_stock_news", data, meta,
                                              instrument_keys=KEY, limit=5, page=2)
        path, params = self.request_parts(request)
        self.assertEqual(path, "/v2/news")
        self.assertEqual(params, {"category": ["instrument_keys"], "instrument_keys": [KEY],
                                  "page_size": ["5"], "page_number": ["2"]})
        self.assertEqual(value["data"], data)
        self.assertEqual(value["provider_metadata"], meta)

    async def test_ipo_listing_and_detail_never_apply(self):
        value, request = await self.response("get_indian_ipos", [{"id": "test-company-ipo", "status": "upcoming"}],
            {"meta_data": {"page": {"total_pages": 2}}}, status="upcoming", issue_type="sme", limit=5)
        path, params = self.request_parts(request)
        self.assertEqual(path, "/v2/ipos")
        self.assertEqual(params, {"status": ["upcoming"], "issue_type": ["sme"], "records": ["5"], "page_number": ["1"]})
        self.assertTrue(value["has_more"])
        value, request = await self.response("get_indian_ipos", {"minimum_price": 100, "lot_size": 50, "listing_price": None},
                                              ipo_id="test-company-ipo")
        self.assertEqual(self.request_parts(request), ("/v2/ipos/test-company-ipo", {}))
        self.assertIsNone(value["data"]["listing_price"])

    async def test_invalid_arguments_fail_before_network(self):
        cases = [("search_indian_stocks", {"query": "x\n"}),
                 ("search_indian_stocks", {"query": "x", "exchange": "MCX"}),
                 ("search_indian_stocks", {"query": "x", "limit": 31}),
                 ("get_indian_company_profile", {"isin": "../../orders"}),
                 ("get_indian_market_quotes", {"instrument_keys": "NSE_EQ|../../orders"}),
                 ("get_indian_market_quotes", {"instrument_keys": "NSE_INDEX|Nifty%2050"}),
                 ("get_indian_market_quotes", {"instrument_keys": ",".join([KEY] * 51)}),
                 ("get_indian_stock_news", {"instrument_keys": ",".join([KEY] * 31)}),
                 ("get_indian_stock_history", {"instrument_key": KEY, "from_date": "2026-02-30", "to_date": "2026-03-01"}),
                 ("get_indian_stock_history", {"instrument_key": KEY, "from_date": "2026-10-03", "to_date": "2026-10-01"}),
                 ("get_indian_stock_history", {"instrument_key": KEY, "from_date": "2026-04-01", "to_date": "2026-10-01", "unit": "minutes"}),
                 ("get_indian_stock_history", {"instrument_key": KEY, "from_date": "2026-10-01", "to_date": "2026-10-01", "interval": 2}),
                 ("get_indian_financial_statements", {"isin": ISIN, "statement": "cash_flow", "time_period": "quarterly"}),
                 ("get_indian_market_calendar", {"kind": "status", "date": "2026-10-01"}),
                 ("get_indian_option_chain", {"instrument_key": "NSE_FO|123", "expiry_date": "next_week"}),
                 ("get_indian_option_chain", {"instrument_key": INDEX, "expiry_date": "tomorrow"}),
                 ("get_indian_fii_dii_activity", {"investor": "DII", "segment": "NSE_FO|STOCK_OPTIONS"}),
                 ("get_indian_fii_dii_activity", {"from_date": "2026-03-31"}),
                 ("get_indian_ipos", {"ipo_id": "../orders"}),
                 ("get_indian_ipos", {"status": "all"})]
        with patch.object(service, "request_public") as request:
            for name, args in cases:
                with self.subTest(tool=name, args=args):
                    self.assertTrue((await self.call(name, **args)).startswith("Error:"))
            request.assert_not_called()

    async def test_missing_and_invalid_credentials_never_make_requests(self):
        with patch.object(service, "request_public") as request:
            for token in ("", "bad\r\ntoken", "Bearer token", "x" * 4097):
                with patch.dict(os.environ, {"UPSTOX_ANALYTICS_TOKEN": token}):
                    result = await self.call("get_indian_company_profile", isin=ISIN)
                self.assertTrue(result.startswith("Error:"))
                if len(token) > 20:
                    self.assertNotIn(token, result)
            request.assert_not_called()

    async def test_http_transport_and_provider_errors_do_not_expose_secrets(self):
        for status in (301, 400, 401, 403, 429, 500):
            with self.subTest(status=status), patch.object(service, "request_public", return_value=(
                    status, {"Location": "https://example.org/" + TOKEN}, TOKEN.encode(), "")):
                result = await self.call("get_indian_company_profile", isin=ISIN)
                self.assertTrue(result.startswith("Error:"))
                self.assertNotIn(TOKEN, result)
                if status == 429:
                    self.assertIn("retry later", result)
        with patch.object(service, "request_public", side_effect=OSError("Authorization: " + TOKEN)):
            result = await self.call("get_indian_company_profile", isin=ISIN)
            self.assertNotIn(TOKEN, result)
        with patch.object(service, "request_public", return_value=(
                200, {"Content-Type": "application/json"},
                json.dumps({"status": "error", "errors": [{"message": TOKEN}]}).encode(), "")):
            result = await self.call("get_indian_company_profile", isin=ISIN)
            self.assertNotIn(TOKEN, result)
            self.assertTrue(result.startswith("Error:"))

    async def test_malformed_nonfinite_deep_and_oversized_provider_data_rejected(self):
        bodies = [b"invalid " + TOKEN.encode(), b'{"status":"success","data":{"x":NaN}}',
                  b'{"status":"success","data":{"x":1e999}}',
                  b'{"status":"success","data":{},"data":{}}',
                  b'{"status":"success","data":{"x":' + b"[" * 60 + b"0" + b"]" * 60 + b"}}",
                  json.dumps({"status": "success", "data": {"profile": "x" * 200001}}).encode(),
                  json.dumps({"status": "success", "data": {"rows": [0] * 10001}}).encode(),
                  b'{"status":"success","data":null}',
                  b'{"status":"success","data":{},"metadata":[]}']
        for body in bodies:
            with self.subTest(size=len(body)), patch.object(service, "request_public", return_value=(
                    200, {"Content-Type": "application/json"}, body, "")):
                result = await self.call("get_indian_company_profile", isin=ISIN)
                self.assertTrue(result.startswith("Error:"))
                self.assertNotIn(TOKEN, result)
        with patch.object(service, "request_public", return_value=(200, {"Content-Type": "text/html"}, b"{}", "")):
            self.assertTrue((await self.call("get_indian_company_profile", isin=ISIN)).startswith("Error:"))

    def test_strict_integer_and_boolean_service_validation(self):
        with patch.object(service, "request_public") as request:
            for limit in (True, 1.5, 0, 501):
                with self.assertRaises(service.MarketDataError):
                    service.get_indian_stock_history(KEY, "2026-10-01", "2026-10-01", limit=limit)
            with self.assertRaises(service.MarketDataError):
                service.get_indian_financial_statements(ISIN, full_statement="true")
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
