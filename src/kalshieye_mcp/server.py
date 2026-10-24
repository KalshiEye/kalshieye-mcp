"""Kalshi Eye MCP server: search and inspect the Kalshi Eye archive of prediction market data.

Every tool reads the public Kalshi Eye API (https://kalshieye.com/docs/api/). Searching,
coverage and market previews need no account. Set KALSHIEYE_API_KEY to also list daily
Parquet files and get download links for the datasets your plan includes.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from kalshieye_mcp import __version__

BASE_URL = os.environ.get("KALSHIEYE_BASE_URL", "https://kalshieye.com").rstrip("/")

INSTRUCTIONS = """\
Kalshi Eye records prediction market order books around the clock and publishes each UTC day
as Parquet files: Kalshi since October 12, 2026; Polymarket, Limitless and Chainlink prices
since October 15, 2026. Use search to find series, events and markets; get_series and
get_market for details; market_price_history for a recorded YES bid/ask path; coverage tools
to see what was recorded; list_datasets for file schemas and plans. Prices are dollars between
0 and 1 (the market's probability). Times are UTC. A YES ask on Kalshi is 1 minus the best NO bid.
"""

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

# Tests swap in an httpx.MockTransport here.
TRANSPORT: httpx.AsyncBaseTransport | None = None

server = MCPServer(
    name="kalshieye",
    title="Kalshi Eye",
    instructions=INSTRUCTIONS,
    website_url="https://kalshieye.com",
    version=__version__,
)


class KalshiEyeError(ToolError):
    """The API refused a request or could not be reached; the message, which the assistant sees, says why."""


def _api_key() -> str:
    return os.environ.get("KALSHIEYE_API_KEY", "").strip()


async def _call(method: str, path: str, *, params: dict[str, Any] | None = None, body: Any = None) -> Any:
    headers = {"User-Agent": f"kalshieye-mcp/{__version__}"}
    if _api_key():
        headers["Authorization"] = f"Bearer {_api_key()}"
    params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
    try:
        async with httpx.AsyncClient(base_url=f"{BASE_URL}/api/v1", timeout=30, follow_redirects=True, transport=TRANSPORT) as client:
            r = await client.request(method, path, params=params, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise KalshiEyeError(f"Could not reach {BASE_URL}: {exc}") from exc
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        if r.status_code == 401:
            detail = "This needs a Kalshi Eye API key: set KALSHIEYE_API_KEY (create one at https://kalshieye.com/app/api/)."
        raise KalshiEyeError(f"{r.status_code}: {detail}")
    return r.json()


def _iso(ts: Any) -> str | None:
    """Epoch seconds to an ISO 8601 UTC string."""
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _pick(row: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    out = {}
    for k in keys:
        v = row.get(k)
        if v is None:
            continue
        out[k.removesuffix("_ts") + "_utc" if k.endswith("_ts") else k] = _iso(v) if k.endswith("_ts") else v
    return out


SERIES_KEYS = ["venue", "id", "label", "category", "frequency", "status", "data_status", "markets_n", "live_n", "settled_n", "next_close_ts", "last_close_ts"]
EVENT_KEYS = ["venue", "id", "title", "series", "category", "status", "markets_n", "open_ts", "close_ts"]
MARKET_KEYS = [
    "venue", "ticker", "event_ticker", "series", "title", "yes_sub_title", "occasion", "category", "status", "result",
    "data_status", "capture", "open_ts", "close_ts", "floor_strike", "cap_strike", "strike_type",
]


@server.tool(annotations=READ)
async def search(
    query: str,
    venue: Literal["kalshi", "polymarket", "limitless", "chainlink"] | None = None,
    category: str | None = None,
    status: Literal["live", "closed"] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Search Kalshi, Polymarket and Limitless series, events and markets by keyword.

    Examples: "bitcoin 15 minute", "fed rate", "NFL", "New York temperature".
    category is an archive category such as Crypto, Economics, Sports or Politics.
    status "live" keeps markets still trading.
    """
    params = {"q": query, "venue": venue, "category": category, "status": status, "limit": max(1, min(limit, 50))}
    d = await _call("GET", "/search", params=params)
    return {
        "series": [_pick(s, SERIES_KEYS) for s in d.get("series", [])[:limit]],
        "events": [_pick(e, EVENT_KEYS) for e in d.get("events", [])[:limit]],
        "markets": [_pick(m, MARKET_KEYS) for m in d.get("markets", [])[:limit]],
    }


@server.tool(annotations=READ)
async def get_series(series_id: str) -> dict[str, Any]:
    """One series (for example KXBTC15M or KXFEDDECISION): what it is, how often it runs, and how many markets and days the archive has."""
    d = await _call("GET", f"/series/{series_id}", params={"limit": 1})
    return {
        "series": _pick(d.get("series") or {}, SERIES_KEYS + ["series_title", "shape", "min_open_ts"]),
        "days_recorded": d.get("days_total"),
        "markets_total": d.get("markets_total"),
        "events_total": d.get("events_total"),
    }


@server.tool(annotations=READ)
async def list_markets(series: str, days: int = 1, status: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Markets in one series that closed or close within the last `days` days (1 to 7), with status, result and times.

    status is a Kalshi market status, such as active or finalized.
    """
    params = {"series": series, "days": max(1, min(days, 7)), "status": status, "limit": max(1, min(limit, 200))}
    d = await _call("GET", "/markets", params=params)
    return {"count": d.get("count"), "markets": [_pick(m, MARKET_KEYS) for m in d.get("markets", [])]}


@server.tool(annotations=READ)
async def get_market(ticker: str) -> dict[str, Any]:
    """One market by ticker (Kalshi ticker, or a Polymarket token id): terms, status, result, and how much of its life was recorded."""
    d = await _call("GET", f"/markets/{ticker}")
    out: dict[str, Any] = {"market": _pick(d.get("market") or {}, MARKET_KEYS + ["settlement_ts", "expiration_value"])}
    try:
        cov = await _call("GET", f"/markets/{ticker}/coverage")
        out["recorded_pct"] = cov.get("pct")
    except KalshiEyeError:
        pass
    return out


@server.tool(annotations=READ)
async def market_price_history(ticker: str) -> dict[str, Any]:
    """The recorded YES best bid and ask over a market's life, about 40 points, plus how much was recorded.

    Good for "what did the market think over time". For every order book change, use the
    daily Parquet files (list_datasets, list_files).
    """
    d = await _call("GET", f"/markets/{ticker}/preview")
    path = [
        {"time_utc": _iso(p.get("ts")), "yes_bid": p.get("yes_best_bid"), "yes_ask": p.get("yes_best_ask")}
        for p in d.get("path") or []
    ]
    cov = d.get("coverage") or {}
    return {
        "ticker": d.get("ticker"),
        "series": d.get("series"),
        "first_recorded_utc": _iso(cov.get("first_print_ts")),
        "last_recorded_utc": _iso(cov.get("last_print_ts")),
        "has_full_order_book": cov.get("has_l2"),
        "pending": bool(d.get("pending")),
        "path": path,
    }


@server.tool(annotations=READ)
async def list_datasets() -> dict[str, Any]:
    """Every dataset in the archive (order books, top of book, minute bars, trades, settlements, Polymarket, Chainlink...):
    what it holds, the plan it needs, days available, and its columns."""
    d = await _call("GET", "/datasets")
    return {
        "first_date": d.get("first_date"),
        "last_date": d.get("last_date"),
        "datasets": [
            {
                "id": x.get("id"),
                "title": x.get("title"),
                "summary": x.get("summary"),
                "plan": x.get("required_plan"),
                "path_template": x.get("path_template"),
                "columns": [f"{c.get('name')} ({c.get('type')})" for c in x.get("columns") or []],
                "sample_parquet": f"{BASE_URL}{(x.get('samples') or {}).get('parquet', '')}" if x.get("samples") else None,
            }
            for x in d.get("datasets", [])
        ],
        "dictionary": f"{BASE_URL}/docs/datasets/",
    }


@server.tool(annotations=READ)
async def dataset_series(dataset_id: str, query: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Which series have files in one dataset (for example book_l2 or trades), with days, rows and size."""
    d = await _call("GET", f"/datasets/{dataset_id}/series", params={"q": query, "limit": max(1, min(limit, 200))})
    return {"dataset": d.get("dataset"), "total": d.get("total"), "series": d.get("series", [])}


@server.tool(annotations=READ)
async def recording_status() -> dict[str, Any]:
    """Whether the recorder is running now, the last published day, and the recorded share of recent days by venue."""
    d = await _call("GET", "/status")
    return {
        "recording": d.get("recording"),
        "checked_at": d.get("checked_at"),
        "first_date": d.get("first_date"),
        "last_published": d.get("last_published"),
        "uptime_7d_pct": (d.get("uptime_7d") or {}).get("recorded_pct"),
        "uptime_30d_pct": (d.get("uptime_30d") or {}).get("recorded_pct"),
        "streams": d.get("streams"),
        "days": d.get("days"),
        "coverage_page": f"{BASE_URL}/app/coverage/",
    }


@server.tool(annotations=READ)
async def list_files(dataset: str, start_date: str, end_date: str, series: str | None = None, limit: int = 100) -> dict[str, Any]:
    """Daily Parquet files for a dataset and date range (YYYY-MM-DD, UTC), optionally one series. Needs KALSHIEYE_API_KEY."""
    d = await _call(
        "GET",
        "/files",
        params={"dataset": dataset, "start_date": start_date, "end_date": end_date, "series": series, "limit": max(1, min(limit, 500))},
    )
    return d


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True, openWorldHint=True))
async def download_links(keys: list[str]) -> dict[str, Any]:
    """Signed download URLs for file keys from list_files. Needs KALSHIEYE_API_KEY.

    The first download of a file in a month counts toward the plan's monthly allowance.
    """
    return await _call("POST", "/files/links", body={"keys": keys[:100]})


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is noise in a client's log
    server.run()


if __name__ == "__main__":
    main()
