"""Bounded, read-only Indian market data from official Upstox APIs."""

import os
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlencode

from app.tools.data_transform.service import load
from app.tools.webpage.service import request_public


_HOST = "api.upstox.com"
_IST = timezone(timedelta(hours=5, minutes=30))
_ISIN = re.compile(r"IN[A-Z0-9]{9}[0-9]\Z")
_INDEX = re.compile(r"[A-Za-z0-9][A-Za-z0-9 &._()\-]{0,79}\Z")
_EXPIRIES = {"current_week", "next_week", "far_week", "current_month", "next_month", "far_month"}
_FII_SEGMENTS = {"NSE_EQ|CASH", "NSE_FO|INDEX_FUTURES", "NSE_FO|STOCK_FUTURES",
                 "NSE_FO|INDEX_OPTIONS", "NSE_FO|STOCK_OPTIONS"}


class MarketDataError(ValueError):
    """A safe error message that never contains provider bodies or credentials."""


def _integer(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise MarketDataError(f"{name} must be an integer between 1 and {maximum}")
    return value


def _choice(value, name, choices, *, upper=False):
    if not isinstance(value, str):
        raise MarketDataError(f"{name} must be a string")
    value = value.strip().upper() if upper else value.strip().lower()
    if value not in choices:
        raise MarketDataError(f"{name} must be one of: {', '.join(sorted(choices))}")
    return value


def _date(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise MarketDataError(f"{name} must be a valid YYYY-MM-DD date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise MarketDataError(f"{name} must be a valid YYYY-MM-DD date") from None


def _isin(value):
    if not isinstance(value, str) or not _ISIN.fullmatch(value.strip().upper()):
        raise MarketDataError("isin must be a 12-character Indian ISIN, e.g. INE002A01018")
    return value.strip().upper()


def _instrument(value, *, underlying=False):
    if not isinstance(value, str) or len(value) > 100 or value.count("|") != 1:
        raise MarketDataError("Use an NSE/BSE instrument_key returned by search_indian_stocks")
    segment, identifier = value.strip().split("|")
    segment = segment.upper()
    if segment in {"NSE_EQ", "BSE_EQ"}:
        identifier = _isin(identifier)
    elif segment in {"NSE_INDEX", "BSE_INDEX"}:
        if not _INDEX.fullmatch(identifier):
            raise MarketDataError("Index instrument keys have an invalid name")
    elif segment in {"NSE_FO", "BSE_FO"} and not underlying:
        if not re.fullmatch(r"[0-9]{1,20}", identifier):
            raise MarketDataError("Derivative instrument keys require a numeric identifier")
    else:
        raise MarketDataError("Supported instruments are NSE/BSE equities and indices"
                              + ("" if underlying else ", and NSE/BSE equity derivatives"))
    return segment + "|" + identifier


def _instruments(value, maximum):
    if not isinstance(value, str) or len(value) > 6000:
        raise MarketDataError("instrument_keys must be a bounded comma-separated string")
    items = value.split(",")
    if not 1 <= len(items) <= maximum:
        raise MarketDataError(f"Provide between 1 and {maximum} instrument keys")
    return list(dict.fromkeys(_instrument(item) for item in items))


def _request(path, params=None, *, shape=dict):
    url = "https://" + _HOST + path
    if params:
        url += "?" + urlencode(params)
    if len(url) > 4096:
        raise MarketDataError("Request URL exceeds 4096 characters; request fewer instruments")
    token = os.environ.get("UPSTOX_ANALYTICS_TOKEN", "")
    if not token:
        raise MarketDataError("Configure UPSTOX_ANALYTICS_TOKEN as a server environment variable")
    if len(token) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise MarketDataError("UPSTOX_ANALYTICS_TOKEN has an invalid format")
    try:
        status, headers, body, _ = request_public(
            url, method="GET", headers={"Accept": "application/json", "Authorization": "Bearer " + token},
            allowed_host=_HOST, follow_redirects=False, timeout_seconds=15)
    except Exception:
        # Transport exception text may include headers. Never propagate it.
        raise MarketDataError("Upstox request failed or exceeded the 1 MB download limit") from None
    if status in {401, 403}:
        raise MarketDataError("Upstox authorization failed; check the server Analytics Token and API access")
    if status == 429:
        raise MarketDataError("Upstox rate limit reached; retry later")
    if status != 200:
        raise MarketDataError(f"Upstox returned HTTP {status}; check inputs or provider availability")
    content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise MarketDataError("Upstox returned an unsupported content type")
    try:
        payload = load(body.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        raise MarketDataError("Upstox returned invalid or oversized JSON; narrow the request") from None
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise MarketDataError("Upstox did not return a successful data response")
    if not isinstance(payload.get("data"), shape):
        raise MarketDataError("Upstox returned an unexpected data structure")
    metadata = {}
    for key in ("meta_data", "metadata"):
        if key in payload:
            if not isinstance(payload[key], dict):
                raise MarketDataError("Upstox returned invalid pagination metadata")
            metadata[key] = payload[key]
    return {"provider": "Upstox", "source_url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "exchange_timezone": "Asia/Kolkata", "data": payload["data"],
            "provider_metadata": metadata}


def _rows(report):
    if any(not isinstance(row, dict) for row in report["data"]):
        raise MarketDataError("Upstox returned invalid data rows")
    return report["data"]


def _page(report, limit, page):
    rows = _rows(report)
    report.update({"data": rows[:limit], "page": page, "limit": limit,
                   "received_items": len(rows), "returned_items": min(limit, len(rows)),
                   "truncated": len(rows) > limit})
    metadata = report["provider_metadata"]
    info = metadata.get("meta_data", metadata.get("metadata", {})).get("page", {})
    total_pages = info.get("total_pages") if isinstance(info, dict) else None
    report["has_more"] = page < total_pages if type(total_pages) is int and total_pages >= 0 else None
    report["next_page"] = page + 1 if report["has_more"] and page < 100 else None
    return report


def search_indian_stocks(query, exchange="NSE", segment="EQ", limit=10, page=1):
    if (not isinstance(query, str) or not query.strip() or len(query) > 50
            or any(ord(c) < 32 or ord(c) == 127 for c in query)):
        raise MarketDataError("query must be 1-50 characters without control characters")
    exchange = _choice(exchange, "exchange", {"NSE", "BSE", "BOTH"}, upper=True)
    segment = _choice(segment, "segment", {"EQ", "INDEX", "FO"}, upper=True)
    _integer(limit, "limit", 30)
    _integer(page, "page", 100)
    report = _request("/v2/instruments/search", {
        "query": query.strip(), "exchanges": "NSE,BSE" if exchange == "BOTH" else exchange,
        "segments": segment, "records": limit, "page_number": page}, shape=list)
    return _page(report, limit, page)


def get_indian_market_quotes(instrument_keys):
    keys = _instruments(instrument_keys, 50)
    report = _request("/v3/market-quote/quotes", {"instrument_key": ",".join(keys)})
    if any(not isinstance(row, dict) for row in report["data"].values()):
        raise MarketDataError("Upstox returned invalid quote rows")
    found = {row.get("instrument_token") for row in report["data"].values()
             if isinstance(row.get("instrument_token"), str)}
    found.update(key.replace(":", "|", 1) for key in report["data"])
    report.update({"requested_instrument_keys": keys,
                   "missing_instrument_keys": [key for key in keys if key not in found],
                   "price_currency": "INR"})
    return report


def get_indian_stock_history(instrument_key, from_date, to_date, unit="days", interval=1, limit=250):
    key = _instrument(instrument_key)
    start, end = _date(from_date, "from_date"), _date(to_date, "to_date")
    if start > end:
        raise MarketDataError("from_date must not be later than to_date")
    unit = _choice(unit, "unit", {"minutes", "hours", "days", "weeks", "months"})
    _integer(interval, "interval", 300 if unit == "minutes" else 5 if unit == "hours" else 1)
    _integer(limit, "limit", 500)
    span = (end - start).days
    if ((unit == "minutes" and span > (31 if interval <= 15 else 92))
            or (unit == "hours" and span > 92) or (unit == "days" and span > 3652)
            or (unit in {"weeks", "months"} and span > 7305)):
        raise MarketDataError("Date range is too large: minutes 31/92 days, hours 92 days, days 10 years, weeks/months 20 years")
    report = _request(f"/v3/historical-candle/{quote(key, safe='')}/{unit}/{interval}/{to_date}/{from_date}")
    candles = report["data"].get("candles")
    if not isinstance(candles, list):
        raise MarketDataError("Upstox returned invalid candle data")
    ordered = []
    seen = set()
    for row in candles:
        if (not isinstance(row, list) or len(row) not in {6, 7}
                or not isinstance(row[0], str) or len(row[0]) > 60
                or any(type(v) not in {int, float} for v in row[1:5])
                or type(row[5]) is not int or row[5] < 0
                or (len(row) == 7 and (type(row[6]) is not int or row[6] < 0))):
            raise MarketDataError("Upstox returned an invalid OHLCV candle")
        try:
            timestamp = datetime.fromisoformat(row[0])
            if timestamp.utcoffset() is None:
                raise ValueError()
            timestamp = timestamp.astimezone(timezone.utc)
        except ValueError:
            raise MarketDataError("Upstox returned an invalid candle timestamp") from None
        if timestamp in seen:
            raise MarketDataError("Upstox returned duplicate candle timestamps")
        seen.add(timestamp)
        ordered.append((timestamp, {"timestamp": row[0], "open": row[1], "high": row[2],
                                    "low": row[3], "close": row[4], "volume": row[5],
                                    "open_interest": row[6] if len(row) == 7 else None}))
    ordered.sort(key=lambda item: item[0])
    report.update({"data": {"candles": [item[1] for item in ordered[-limit:]]},
                   "instrument_key": key, "unit": unit, "interval": interval,
                   "price_currency": "INR", "order": "oldest_first", "selection": "latest",
                   "received_candles": len(candles), "returned_candles": min(limit, len(candles)),
                   "truncated": len(candles) > limit})
    return report


def _fundamental(isin, resource, params=None, *, shape=dict):
    return _request(f"/v2/fundamentals/{_isin(isin)}/{resource}", params, shape=shape)


def get_indian_company_profile(isin):
    return _fundamental(isin, "profile")


def get_indian_financial_statements(isin, statement="income_statement", statement_type="consolidated",
                                    time_period="yearly", full_statement=False):
    statement = _choice(statement, "statement", {"income_statement", "balance_sheet", "cash_flow"})
    statement_type = _choice(statement_type, "statement_type", {"consolidated", "standalone"})
    time_period = _choice(time_period, "time_period", {"yearly", "quarterly"})
    if type(full_statement) is not bool:
        raise MarketDataError("full_statement must be a boolean")
    if statement != "income_statement" and time_period != "yearly":
        raise MarketDataError("Only income_statement accepts a quarterly selector")
    params = {"type": statement_type, "fs": "true" if full_statement else "false"}
    if statement == "income_statement":
        params["time_period"] = time_period
    report = _fundamental(isin, statement.replace("_", "-"), params)
    report["monetary_amount_unit"] = "INR crore (1 crore = 10000000 INR); preserve provider field units"
    return report


def get_indian_stock_ratios(isin):
    report = _fundamental(isin, "key-ratios", shape=list)
    _rows(report)
    return report


def get_indian_shareholding(isin):
    report = _fundamental(isin, "share-holdings", shape=list)
    _rows(report)
    report["holding_unit"] = "percent of total shares"
    return report


def get_indian_corporate_actions(isin, limit=50):
    _integer(limit, "limit", 100)
    report = _fundamental(isin, "corporate-actions", shape=list)
    rows = _rows(report)
    report.update({"data": rows[:limit], "received_events": len(rows),
                   "returned_events": min(limit, len(rows)), "truncated": len(rows) > limit,
                   "order": "provider_order"})
    return report


def get_indian_market_calendar(kind="status", exchange="NSE", date=""):
    kind = _choice(kind, "kind", {"status", "timings", "holidays"})
    exchange = _choice(exchange, "exchange", {"NSE", "BSE"}, upper=True)
    if kind == "status":
        if date:
            raise MarketDataError("status is current; date is only used for timings or holidays")
        return _request("/v2/market/status/" + exchange)
    if date:
        _date(date, "date")
    if kind == "timings" and not date:
        date = datetime.now(_IST).date().isoformat()
    suffix = "/" + date if date else ""
    # Timings and holidays include all provider exchanges and trading segments.
    report = _request("/v2/market/" + kind + suffix, shape=list)
    _rows(report)
    return report


def get_indian_option_chain(instrument_key, expiry_date, limit=50):
    key = _instrument(instrument_key, underlying=True)
    if expiry_date not in _EXPIRIES:
        _date(expiry_date, "expiry_date")
    _integer(limit, "limit", 100)
    report = _request("/v2/option/chain", {"instrument_key": key, "expiry_date": expiry_date}, shape=list)
    rows = _rows(report)
    report.update({"data": rows[:limit], "received_strikes": len(rows),
                   "returned_strikes": min(limit, len(rows)), "truncated": len(rows) > limit,
                   "order": "provider_order", "price_currency": "INR"})
    return report


def get_indian_fii_dii_activity(investor="FII", segment="NSE_EQ|CASH", interval="1D", from_date=""):
    investor = _choice(investor, "investor", {"FII", "DII"}, upper=True)
    interval = _choice(interval, "interval", {"1D", "1M"}, upper=True)
    segment = _choice(segment, "segment", _FII_SEGMENTS if investor == "FII" else {"NSE_EQ|CASH"}, upper=True)
    params = {"data_type": segment, "interval": interval}
    if from_date:
        if _date(from_date, "from_date") < date(2026, 4, 1):
            raise MarketDataError("Upstox institutional activity is available from 2026-04-01")
        params["from"] = from_date
    report = _request("/v2/market/" + investor.lower(), params)
    if any(not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
           for rows in report["data"].values()):
        raise MarketDataError("Upstox returned invalid institutional activity rows")
    report.update({"investor": investor, "segment": segment, "interval": interval,
                   "coverage_start": "2026-04-01"})
    return report


def get_indian_stock_news(instrument_keys, limit=20, page=1):
    keys = _instruments(instrument_keys, 30)
    _integer(limit, "limit", 100)
    _integer(page, "page", 100)
    report = _request("/v2/news", {"category": "instrument_keys", "instrument_keys": ",".join(keys),
                                  "page_size": limit, "page_number": page})
    if any(not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
           for rows in report["data"].values()):
        raise MarketDataError("Upstox returned invalid news rows")
    report.update({"requested_instrument_keys": keys, "page": page, "limit": limit,
                   "coverage": "provider news from the past 7 days"})
    return report


def get_indian_ipos(status="open", issue_type="", limit=20, page=1, ipo_id=""):
    if ipo_id:
        if not isinstance(ipo_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9\-]{0,199}", ipo_id):
            raise MarketDataError("ipo_id must be the slug ID returned by get_indian_ipos")
        return _request("/v2/ipos/" + ipo_id)
    status = _choice(status, "status", {"open", "closed", "listed", "upcoming"})
    _integer(limit, "limit", 30)
    _integer(page, "page", 100)
    params = {"status": status, "records": limit, "page_number": page}
    if issue_type:
        params["issue_type"] = _choice(issue_type, "issue_type", {"regular", "sme"})
    return _page(_request("/v2/ipos", params, shape=list), limit, page)
