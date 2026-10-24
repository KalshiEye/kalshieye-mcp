"""Kalshi Eye MCP server: search and inspect the Kalshi Eye archive of prediction market data.

Every tool reads the public Kalshi Eye API (https://kalshieye.com/docs/api/). Searching,
coverage and price history need no account. Set KALSHIEYE_API_KEY to also list daily
Parquet files and get download links for the datasets your plan includes.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from kalshieye_mcp import __version__

BASE_URL = os.environ.get("KALSHIEYE_BASE_URL", "https://kalshieye.com").rstrip("/")
KEYS_URL = "https://kalshieye.com/app/api/"

INSTRUCTIONS = """\
Kalshi Eye records prediction market order books around the clock and publishes each UTC day
as Parquet files: Kalshi since October 12, 2026; Polymarket, Limitless and Chainlink prices
since October 15, 2026. Use search to find series, events and markets; get_series and
get_market for details; market_price_history for a short recorded YES bid/ask path; coverage
tools to see what was recorded; list_datasets for file schemas and plans. Prices are dollars
between 0 and 1 (the market's probability). Times are UTC. A YES ask on Kalshi is 1 minus the
best NO bid.
"""

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

# Tests swap in an httpx.MockTransport here.
TRANSPORT: httpx.AsyncBaseTransport | None = None

log = logging.getLogger("kalshieye_mcp")

server = MCPServer(
    name="kalshieye",
    title="Kalshi Eye",
    instructions=INSTRUCTIONS,
    website_url="https://kalshieye.com",
    version=__version__,
)


class KalshiEyeError(ToolError):
    """The API refused a request or could not be reached; the message, which the assistant sees, says why."""


_warned: set[str] = set()


def _warn_once(message: str) -> None:
    if message not in _warned:
        _warned.add(message)
        log.warning(message)


def _api_key() -> str:
    """The key from KALSHIEYE_API_KEY, or "" when unset or not a key (e.g. a placeholder left in a config)."""
    key = os.environ.get("KALSHIEYE_API_KEY", "").strip()
    if key and not re.fullmatch(r"clab_\S+", key):
        _warn_once("KALSHIEYE_API_KEY is not a Kalshi Eye key (they start with clab_); ignoring it")
        return ""
    return key


_ID = re.compile(r"[A-Za-z0-9._:\-]{1,200}")


def _segment(value: str, what: str) -> str:
    """A ticker or id, checked and escaped for use in a URL path."""
    if not _ID.fullmatch(value or ""):
        raise KalshiEyeError(f"{value!r} is not a valid {what}. Use search to find one.")
    return quote(value, safe=":")


async def _request(method: str, path: str, params: dict[str, Any], body: Any, key: str) -> httpx.Response:
    headers = {"User-Agent": f"kalshieye-mcp/{__version__}"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        async with httpx.AsyncClient(base_url=f"{BASE_URL}/api/v1", timeout=30, follow_redirects=True, transport=TRANSPORT) as client:
            return await client.request(method, path, params=params, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise KalshiEyeError(f"Could not reach {BASE_URL}: {exc}") from exc


def _detail(r: httpx.Response) -> str:
    try:
        return str(r.json().get("detail", r.text))
    except ValueError:
        return r.text


async def _call(method: str, path: str, *, params: dict[str, Any] | None = None, body: Any = None, needs_key: bool = False) -> Any:
    params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
    key = _api_key()
    r = await _request(method, path, params, body, key)
    if r.status_code == 401 and key and not needs_key:
        # A rejected key fails even public calls; those work without one.
        _warn_once(f"Kalshi Eye rejected KALSHIEYE_API_KEY ({_detail(r)}); public tools run without it")
        r = await _request(method, path, params, body, "")
    if r.status_code == 401:
        if key:
            raise KalshiEyeError(f"Kalshi Eye rejected the key in KALSHIEYE_API_KEY ({_detail(r)}). Check it at {KEYS_URL}.")
        raise KalshiEyeError(f"This needs a Kalshi Eye API key: set KALSHIEYE_API_KEY (create one at {KEYS_URL}).")
    if r.status_code >= 400:
        raise KalshiEyeError(f"{r.status_code}: {_detail(r)}")
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


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(int(value), high))


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
    status "live" keeps markets still trading. limit is 1 to 50 per kind.
    """
    limit = _clamp(limit, 1, 50)
    d = await _call("GET", "/search", params={"q": query, "venue": venue, "category": category, "status": status, "limit": limit})
    return {
        "series": [_pick(s, SERIES_KEYS) for s in d.get("series", [])[:limit]],
        "events": [_pick(e, EVENT_KEYS) for e in d.get("events", [])[:limit]],
        "markets": [_pick(m, MARKET_KEYS) for m in d.get("markets", [])[:limit]],
    }


@server.tool(annotations=READ)
async def get_series(series_id: str) -> dict[str, Any]:
    """One series (for example KXBTC15M, KXFEDDECISION, or a pm:/lm: id from search): what it is, how often it
    runs, how many markets the catalog lists, and how many days of data files the archive has for it."""
    seg = _segment(series_id, "series id")
    d = await _call("GET", f"/series/{seg}", params={"limit": 1})
    cov = await _call("GET", "/coverage/series", params={"ids": series_id})
    files = next(iter((cov.get("series") or {}).values()), None)
    return {
        "series": _pick(d.get("series") or {}, SERIES_KEYS + ["series_title", "shape", "min_open_ts"]),
        "markets_in_catalog": d.get("markets_total"),
        "events_in_catalog": d.get("events_total"),
        "files": (
            {
                "days": files.get("days"),
                "first_date": files.get("first_date"),
                "last_date": files.get("last_date"),
                "datasets": files.get("datasets"),
            }
            if files
            else None
        ),
    }


@server.tool(annotations=READ)
async def list_markets(series: str, status: str | None = None, limit: int = 20) -> dict[str, Any]:
    """The most recent markets in one series, newest first, with status, result and times.

    status is a market status such as active, closed or finalized. limit is 1 to 200.
    """
    d = await _call("GET", "/markets", params={"series": series, "status": status, "limit": _clamp(limit, 1, 200)})
    return {"count": d.get("count"), "markets": [_pick(m, MARKET_KEYS) for m in d.get("markets", [])]}


@server.tool(annotations=READ)
async def get_market(ticker: str) -> dict[str, Any]:
    """One market: terms, status, result, and how much of it the archive recorded.

    ticker is a Kalshi market ticker (KXBTC15M-26OCT121545-45) or a Polymarket or Limitless market id as
    search returns it (pm:0x..., lm:...).
    """
    seg = _segment(ticker, "market ticker")
    d = await _call("GET", f"/markets/{seg}")
    out: dict[str, Any] = {"market": _pick(d.get("market") or {}, MARKET_KEYS + ["settlement_ts", "expiration_value"])}
    try:
        cov = await _call("GET", f"/markets/{seg}/coverage")
    except KalshiEyeError:
        return out
    if cov.get("measured"):
        # Measured from when recording began (October 12, 2026 for Kalshi), not from the market's open.
        out["recorded_pct"] = cov.get("pct")
        out["recorded_window_utc"] = [_iso(cov.get("start")), _iso(cov.get("end"))]
    return out


@server.tool(annotations=READ)
async def market_price_history(ticker: str) -> dict[str, Any]:
    """A short recorded YES best bid and ask path for one market: up to about 40 points over the window the
    archive's preview covers, usually the market's most recent recorded stretch rather than its whole life.

    For every order book change, use the daily Parquet files (list_datasets, list_files). Previews are built
    for Kalshi markets; Polymarket and Limitless markets may return no points.
    """
    seg = _segment(ticker, "market ticker")
    await _call("GET", f"/markets/{seg}")  # an unknown ticker is an error here, not an empty preview
    d = await _call("GET", f"/markets/{seg}/preview")
    path = [
        {"time_utc": _iso(p.get("ts")), "yes_bid": p.get("yes_best_bid"), "yes_ask": p.get("yes_best_ask")}
        for p in d.get("path") or []
    ]
    out: dict[str, Any] = {
        "ticker": d.get("ticker") or ticker,
        "series": d.get("series"),
        "window_start_utc": _iso(d.get("start_ts")),
        "window_end_utc": _iso(d.get("end_ts")),
        "has_full_order_book": (d.get("coverage") or {}).get("has_l2"),
        "path": path,
    }
    if d.get("pending"):
        out["note"] = "The preview is still being built; try again in a few seconds."
    elif not path:
        out["note"] = "No recorded price path in the preview for this market."
    return out


@server.tool(annotations=READ)
async def list_datasets() -> dict[str, Any]:
    """Every dataset in the archive (order books, top of book, minute bars, trades, settlements, Polymarket,
    Limitless, Chainlink...): what it holds, the plan it needs, its dates, and its columns."""
    d = await _call("GET", "/datasets")
    out = []
    for x in d.get("datasets", []):
        cov = x.get("coverage") or {}
        out.append(
            {
                "id": x.get("id"),
                "title": x.get("title"),
                "summary": x.get("summary"),
                "plan": x.get("required_plan"),
                "first_date": cov.get("first_date"),
                "last_date": cov.get("last_date"),
                "days": cov.get("days"),
                "path_template": x.get("path_template"),
                "columns": [f"{c.get('name')} ({c.get('type')})" for c in x.get("columns") or []],
                "sample_parquet": f"{BASE_URL}{(x.get('samples') or {}).get('parquet', '')}" if x.get("samples") else None,
            }
        )
    return {"datasets": out, "dictionary": f"{BASE_URL}/docs/datasets/"}


@server.tool(annotations=READ)
async def dataset_series(dataset_id: str, query: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Which series have files in one dataset (for example book_l2 or trades), with days, rows and size."""
    seg = _segment(dataset_id, "dataset id")
    d = await _call("GET", f"/datasets/{seg}/series", params={"q": query, "limit": _clamp(limit, 1, 200)})
    return {"dataset": d.get("dataset"), "total": d.get("total"), "series": d.get("series", [])}


@server.tool(annotations=READ)
async def recording_status() -> dict[str, Any]:
    """Whether the recorder is running now, the last published day, and the recorded share of recent days,
    overall and by venue."""
    d = await _call("GET", "/status")
    return {
        "recording": d.get("recording"),
        "checked_at": d.get("checked_at"),
        "first_date": d.get("first_date"),
        "last_published": d.get("last_published"),
        "uptime_7d_pct": (d.get("uptime_7d") or {}).get("recorded_pct"),
        "uptime_30d_pct": (d.get("uptime_30d") or {}).get("recorded_pct"),
        "uptime_by_venue": d.get("uptime_by_venue"),
        "streams": d.get("streams"),
        "days": d.get("days"),
        "coverage_page": f"{BASE_URL}/app/coverage/",
    }


@server.tool(annotations=READ)
async def list_files(
    dataset: str,
    start_date: str,
    end_date: str,
    series: str | None = None,
    cursor: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Daily Parquet files for a dataset and date range (YYYY-MM-DD, UTC), optionally one series. Needs
    KALSHIEYE_API_KEY. When next_cursor is set, call again with it for the next page."""
    params = {
        "dataset": dataset,
        "start_date": start_date,
        "end_date": end_date,
        "series": series,
        "cursor": cursor,
        "limit": _clamp(limit, 1, 500),
    }
    return await _call("GET", "/files", params=params, needs_key=True)


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True))
async def download_links(keys: list[str]) -> dict[str, Any]:
    """Signed download URLs for up to 100 file keys from list_files. Needs KALSHIEYE_API_KEY.

    The first download of a file in a month counts toward the plan's monthly allowance.
    """
    if not keys:
        raise KalshiEyeError("Pass at least one file key from list_files.")
    if len(keys) > 100:
        raise KalshiEyeError(f"At most 100 keys per call ({len(keys)} given); call again for the rest.")
    return await _call("POST", "/files/links", body={"keys": keys}, needs_key=True)


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is noise in a client's log
    server.run()


if __name__ == "__main__":
    main()
