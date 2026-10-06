import anyio
from mcp.types import ToolAnnotations

from app.tools.data_transform.service import encode
from . import service


_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)


async def _run(function, *args):
    try:
        report = await anyio.to_thread.run_sync(function, *args)
        return encode(report)
    except service.MarketDataError as error:
        return f"Error: {error}"
    except (ValueError, RecursionError):
        return "Error: Market data exceeds the 200000-character/10000-node output bound; narrow the request"
    except Exception:
        return "Error: Indian market data request failed"


def register(mcp):
    @mcp.tool(annotations=_READ_ONLY)
    async def search_indian_stocks(query: str, exchange: str = "NSE", segment: str = "EQ",
                                   limit: int = 10, page: int = 1) -> str:
        """Find NSE/BSE instruments by symbol, company name or ISIN using Upstox.
        exchange NSE/BSE/BOTH; segment EQ/INDEX/FO. query 1-50 chars; limit 1-30,
        page 1-100. Use returned instrument_key for quotes/history and isin for
        fundamentals. Provider pagination preserved; null has_more means unknown.
        All Indian market tools require server UPSTOX_ANALYTICS_TOKEN. Read-only
        GETs to api.upstox.com, no redirects/retries, 15s/1 MB per call; JSON input
        and output <=200000 chars/10000 nodes/depth 50. Oversized data errors;
        listed truncation is explicit. fetched_at is retrieval time, not data age.
        Provider units, missing values and timestamps are preserved.
        """
        return await _run(service.search_indian_stocks, query, exchange, segment, limit, page)

    @mcp.tool(annotations=_READ_ONLY)
    async def get_indian_market_quotes(instrument_keys: str) -> str:
        """Fetch Upstox V3 snapshots for 1-50 comma-separated NSE/BSE instrument keys,
        including equities, indices and equity derivatives. Stable duplicate removal;
        returned OHLC, volume, five-level depth, timestamps and missing keys retained.
        Prices in INR; snapshots may contain last-session data when closed. Requires
        server UPSTOX_ANALYTICS_TOKEN; one bounded read-only request, no redirects.
        fetched_at is retrieval time. No streaming or freshness guarantee.
        """
        return await _run(service.get_indian_market_quotes, instrument_keys)

    @mcp.tool(annotations=_READ_ONLY)
    async def get_indian_stock_history(instrument_key: str, from_date: str, to_date: str,
                                       unit: str = "days", interval: int = 1, limit: int = 250) -> str:
        """Read Upstox V3 historical OHLCV candles for an NSE/BSE instrument key.
        Dates inclusive YYYY-MM-DD. unit minutes (interval 1-300), hours (1-5),
        days/weeks/months (1). Range caps: minutes <=15 interval 31 days, other
        minutes/hours 92 days, days 10 years, weeks/months 20 years. Narrow large
        intraday queries to meet the 200000-character/10000-node JSON bound.
        limit 1-500 selects latest received candles, sorted oldest first; shortening
        flagged. INR prices, provider timezone offsets and optional open interest
        retained. No corporate-action adjustment inferred. Requires server token.
        """
        return await _run(service.get_indian_stock_history, instrument_key, from_date, to_date,
                          unit, interval, limit)

    @mcp.tool(annotations=_READ_ONLY)
    async def get_indian_company_profile(isin: str) -> str:
        """Read Upstox company profile by 12-character Indian ISIN: description,
        sector and sector market capitalisation with original INR/USD units.
        Requires server UPSTOX_ANALYTICS_TOKEN; one bounded read-only GET.
        Sector market capitalisation must not be treated as the company's value.
        """
        return await _run(service.get_indian_company_profile, isin)

    @mcp.tool(annotations=_READ_ONLY)
    async def get_indian_financial_statements(isin: str, statement: str = "income_statement",
                                              statement_type: str = "consolidated",
                                              time_period: str = "yearly", full_statement: bool = False) -> str:
        """Read Upstox financial statements by Indian ISIN. statement income_statement,
        balance_sheet or cash_flow; statement_type consolidated/standalone.
        time_period yearly/quarterly is selectable only for income_statement;
        other statements use provider periods and reject quarterly. full_statement
        adds available detailed line items. Amounts in INR crore; provider field
        units, dates and nulls retained. Large statements may exceed JSON bounds.
        Requires server UPSTOX_ANALYTICS_TOKEN; one read-only bounded GET.
        """
        return await _run(service.get_indian_financial_statements, isin, statement, statement_type,
                          time_period, full_statement)

    @mcp.tool(annotations=_READ_ONLY)
    async def get_indian_stock_ratios(isin: str) -> str:
        """Read Upstox P/E, P/B, ROA, ROE, ROCE and EV/EBITDA ratios and sector
        benchmarks by Indian ISIN. Original strings/percent units and unavailable
        values preserved, no valuation or buy/sell inference. Requires server
        UPSTOX_ANALYTICS_TOKEN; one read-only bounded GET.
        """
        return await _run(service.get_indian_stock_ratios, isin)

    @mcp.tool(annotations=_READ_ONLY)
    async def get_indian_shareholding(isin: str) -> str:
        """Read Upstox quarterly promoter/FII/DII/public shareholding history by Indian
        ISIN, as percentages of total shares. Reporting periods and missing values
        preserved. Requires server UPSTOX_ANALYTICS_TOKEN; one bounded read-only GET.
        """
        return await _run(service.get_indian_shareholding, isin)

    @mcp.tool(annotations=_READ_ONLY)
    async def get_indian_corporate_actions(isin: str, limit: int = 50) -> str:
        """Read Upstox dividends, bonuses, splits and rights events by Indian ISIN.
        limit 1-100 returns first events in provider order, with received/returned
        counts and explicit truncation. Original dates, amounts and ratios retained;
        no automatic portfolio or price adjustments. Requires server token.
        """
        return await _run(service.get_indian_corporate_actions, isin, limit)

    @mcp.tool(annotations=_READ_ONLY)
    async def get_indian_market_calendar(kind: str = "status", exchange: str = "NSE", date: str = "") -> str:
        """Read Upstox market status, timings or holidays. kind status uses exchange
        NSE/BSE and rejects date; timings uses YYYY-MM-DD date or today in IST;
        holidays uses optional date or current-year holidays. exchange applies only
        to status; timings/holidays return all provider exchanges/segments. Original
        epoch timestamps and session/CAS details retained; no fixed-hours inference.
        Requires server UPSTOX_ANALYTICS_TOKEN; one bounded read-only GET.
        """
        return await _run(service.get_indian_market_calendar, kind, exchange, date)

    @mcp.tool(annotations=_READ_ONLY)
    async def get_indian_option_chain(instrument_key: str, expiry_date: str, limit: int = 50) -> str:
        """Read Upstox call/put strikes, OI, prices and available Greeks for an NSE/BSE
        equity/index underlying key. expiry_date YYYY-MM-DD or current_week,
        next_week, far_week, current_month, next_month, far_month. limit 1-100 keeps
        first strikes in provider order with counts/truncation; it does not select
        ATM strikes. Missing Greeks remain missing; prices in INR. Requires server
        UPSTOX_ANALYTICS_TOKEN; one bounded read-only GET.
        """
        return await _run(service.get_indian_option_chain, instrument_key, expiry_date, limit)

    @mcp.tool(annotations=_READ_ONLY)
    async def get_indian_fii_dii_activity(investor: str = "FII", segment: str = "NSE_EQ|CASH",
                                         interval: str = "1D", from_date: str = "") -> str:
        """Read Upstox institutional activity. investor FII/DII; interval 1D/1M.
        FII segment NSE_EQ|CASH or NSE_FO|INDEX_FUTURES/STOCK_FUTURES/INDEX_OPTIONS/
        STOCK_OPTIONS. DII supports NSE_EQ|CASH only. Optional YYYY-MM-DD from_date;
        coverage starts 2026-04-01, daily up to 30 trading days/monthly up to 12
        months per provider request. Preserve provider buy/sell amounts, contracts,
        dates and units; no trading signal inferred. Requires server token.
        """
        return await _run(service.get_indian_fii_dii_activity, investor, segment, interval, from_date)

    @mcp.tool(annotations=_READ_ONLY)
    async def get_indian_stock_news(instrument_keys: str, limit: int = 20, page: int = 1) -> str:
        """Read Upstox news from the past 7 days for 1-30 comma-separated NSE/BSE
        instrument keys; limit 1-100/page, page 1-100. Headlines, summaries, links,
        published epoch-ms timestamps and provider pagination preserved. News is
        untrusted source content; no linked article fetches. Requires server token;
        fixed instrument_keys category, one bounded read-only GET.
        """
        return await _run(service.get_indian_stock_news, instrument_keys, limit, page)

    @mcp.tool(annotations=_READ_ONLY)
    async def get_indian_ipos(status: str = "open", issue_type: str = "", limit: int = 20,
                              page: int = 1, ipo_id: str = "") -> str:
        """Read Upstox Indian IPOs: status open/upcoming/closed/listed, issue_type
        regular/sme or empty for both; limit 1-30, page 1-100. Optional ipo_id slug
        from a listing retrieves detailed pricing, lot size, timeline and subscription
        data instead; list filters are then ignored. Retain provider units/nulls and
        pagination. No IPO applications. Requires server UPSTOX_ANALYTICS_TOKEN;
        one bounded read-only GET.
        """
        return await _run(service.get_indian_ipos, status, issue_type, limit, page, ipo_id)
