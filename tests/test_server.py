import json

import httpx
import pytest
from mcp import Client

from kalshieye_mcp import server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def api(monkeypatch):
    """Answer API calls from a dict of path -> JSON, and record the requests.

    Like the real API: every call needs a valid key (401 otherwise), and an unknown path is a 404.
    """
    routes: dict[str, object] = {}
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path.removeprefix("/api/v1")
        if request.headers.get("Authorization") != "Bearer clab_good":
            return httpx.Response(401, json={"detail": "invalid api key"})
        if path not in routes:
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json=routes[path])

    monkeypatch.setattr(server, "TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setenv("KALSHIEYE_API_KEY", "clab_good")
    return routes, seen


def _result(res):
    return json.loads(res.content[0].text)


async def test_lists_every_tool():
    async with Client(server.server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert names == {
        "search", "get_series", "list_markets", "get_market", "market_price_history",
        "list_datasets", "dataset_series", "recording_status", "list_files", "download_links",
    }


async def test_search_trims_results_and_converts_times(api):
    routes, seen = api
    routes["/search"] = {
        "categories": [{"id": "Crypto"}],
        "series": [{"id": "KXBTC15M", "label": "Bitcoin price up down", "next_close_ts": 1791850500.0, "extra": "x"}],
        "events": [],
        "markets": [{"ticker": "KXBTC15M-26OCT121545-45", "status": "finalized", "result": "yes", "close_ts": 1791850500.0}],
    }
    async with Client(server.server) as client:
        out = _result(await client.call_tool("search", {"query": "bitcoin", "venue": "kalshi", "limit": -1}))
    assert out["series"] == [{"id": "KXBTC15M", "label": "Bitcoin price up down", "next_close_utc": "2026-10-13T00:15:00Z"}]
    assert out["markets"][0]["close_utc"] == "2026-10-13T00:15:00Z"
    assert seen[0].url.params["q"] == "bitcoin" and seen[0].url.params["venue"] == "kalshi"
    assert seen[0].url.params["limit"] == "1"
    assert "category" not in seen[0].url.params


async def test_get_series_reports_file_days(api):
    routes, _ = api
    routes["/series/KXFED"] = {"series": {"id": "KXFED", "label": "Fed funds rate"}, "markets_total": 258, "events_total": 9, "days_total": 30}
    routes["/coverage/series"] = {"series": {"KXFED": {"days": 12, "first_date": "2026-10-12", "last_date": "2026-10-23", "datasets": ["trades"]}}}
    async with Client(server.server) as client:
        out = _result(await client.call_tool("get_series", {"series_id": "KXFED"}))
    assert out["files"] == {"days": 12, "first_date": "2026-10-12", "last_date": "2026-10-23", "datasets": ["trades"]}
    assert out["markets_in_catalog"] == 258


async def test_price_history(api):
    routes, _ = api
    routes["/markets/T"] = {"market": {"ticker": "T"}}
    routes["/markets/T/preview"] = {
        "ticker": "T",
        "series": "S",
        "start_ts": 1791850000.0,
        "end_ts": 1791850500.0,
        "coverage": {"has_l2": True},
        "path_source": "busiest",
        "path": [
            {"ts": 1791850100.0, "yes_best_bid": 0.4, "yes_best_ask": 0.42},
            {"ts": 1791850400.0, "yes_best_bid": 0.45, "yes_best_ask": 0.47},
        ],
    }
    async with Client(server.server) as client:
        out = _result(await client.call_tool("market_price_history", {"ticker": "T"}))
    assert out["path"][0] == {"time_utc": "2026-10-13T00:08:20Z", "yes_bid": 0.4, "yes_ask": 0.42}
    # the window is the span the points cover, not the preview's start_ts / end_ts
    assert (out["window_start_utc"], out["window_end_utc"]) == ("2026-10-13T00:08:20Z", "2026-10-13T00:13:20Z")
    assert out["path_source"] == "busiest" and out["has_full_order_book"] is True
    assert "note" not in out


async def test_price_history_rejects_unknown_ticker_without_building_a_preview(api):
    _, seen = api
    async with Client(server.server) as client:
        res = await client.call_tool("market_price_history", {"ticker": "NOPE-XYZ"})
    assert res.is_error and "404" in res.content[0].text
    assert [r.url.path for r in seen] == ["/api/v1/markets/NOPE-XYZ"]


async def test_rejects_ids_that_are_not_ids(api):
    _, seen = api
    async with Client(server.server) as client:
        res = await client.call_tool("get_market", {"ticker": "../series/KXNFLGAME"})
    assert res.is_error and "not a valid market ticker" in res.content[0].text
    assert seen == []


async def test_every_tool_needs_a_key(api, monkeypatch):
    _, seen = api
    for value in (None, "optional: clab_..."):  # unset, or a placeholder left in a config
        if value is None:
            monkeypatch.delenv("KALSHIEYE_API_KEY", raising=False)
        else:
            monkeypatch.setenv("KALSHIEYE_API_KEY", value)
        async with Client(server.server) as client:
            res = await client.call_tool("search", {"query": "fed"})
        assert res.is_error and "needs an API key" in res.content[0].text
    assert seen == []


async def test_sends_the_key(api):
    routes, seen = api
    routes["/files"] = {"files": [], "next_cursor": None}
    async with Client(server.server) as client:
        await client.call_tool("list_files", {"dataset": "trades", "start_date": "2026-10-13", "end_date": "2026-10-13", "cursor": "abc"})
    assert seen[0].headers["Authorization"] == "Bearer clab_good"
    assert seen[0].url.params["cursor"] == "abc"


async def test_a_rejected_key_says_so(api, monkeypatch):
    monkeypatch.setenv("KALSHIEYE_API_KEY", "clab_revoked")
    async with Client(server.server) as client:
        res = await client.call_tool("search", {"query": "fed"})
    assert res.is_error and "rejected the key" in res.content[0].text


async def test_download_links_limits(api):
    async with Client(server.server) as client:
        res = await client.call_tool("download_links", {"keys": [f"k{i}" for i in range(101)]})
    assert res.is_error and "At most 100 keys" in res.content[0].text
