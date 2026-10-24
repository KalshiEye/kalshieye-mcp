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

    Like the real API: an unknown path is a 404, a key-only path without a valid key is a 401, and any
    request carrying an invalid key is a 401.
    """
    routes: dict[str, object] = {}
    keyed: set[str] = set()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path.removeprefix("/api/v1")
        auth = request.headers.get("Authorization", "")
        if auth and auth != "Bearer clab_good":
            return httpx.Response(401, json={"detail": "invalid token"})
        if path in keyed and not auth:
            return httpx.Response(401, json={"detail": "not authenticated"})
        if path not in routes:
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json=routes[path])

    monkeypatch.setattr(server, "TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.delenv("KALSHIEYE_API_KEY", raising=False)
    return routes, keyed, seen


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
    routes, _, seen = api
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
    routes, _, _ = api
    routes["/series/KXFED"] = {"series": {"id": "KXFED", "label": "Fed funds rate"}, "markets_total": 258, "events_total": 9, "days_total": 30}
    routes["/coverage/series"] = {"series": {"KXFED": {"days": 12, "first_date": "2026-10-12", "last_date": "2026-10-23", "datasets": ["trades"]}}}
    async with Client(server.server) as client:
        out = _result(await client.call_tool("get_series", {"series_id": "KXFED"}))
    assert out["files"] == {"days": 12, "first_date": "2026-10-12", "last_date": "2026-10-23", "datasets": ["trades"]}
    assert out["markets_in_catalog"] == 258


async def test_price_history(api):
    routes, _, _ = api
    routes["/markets/T"] = {"market": {"ticker": "T"}}
    routes["/markets/T/preview"] = {
        "ticker": "T",
        "series": "S",
        "start_ts": 1791850000.0,
        "end_ts": 1791850500.0,
        "coverage": {"has_l2": True},
        "path": [{"ts": 1791850000.0, "yes_best_bid": 0.4, "yes_best_ask": 0.42}],
    }
    async with Client(server.server) as client:
        out = _result(await client.call_tool("market_price_history", {"ticker": "T"}))
    assert out["path"] == [{"time_utc": "2026-10-13T00:06:40Z", "yes_bid": 0.4, "yes_ask": 0.42}]
    assert out["window_start_utc"] == "2026-10-13T00:06:40Z" and out["has_full_order_book"] is True
    assert "note" not in out


async def test_price_history_rejects_unknown_ticker_without_building_a_preview(api):
    _, _, seen = api
    async with Client(server.server) as client:
        res = await client.call_tool("market_price_history", {"ticker": "NOPE-XYZ"})
    assert res.is_error and "404" in res.content[0].text
    assert [r.url.path for r in seen] == ["/api/v1/markets/NOPE-XYZ"]


async def test_rejects_ids_that_are_not_ids(api):
    _, _, seen = api
    async with Client(server.server) as client:
        res = await client.call_tool("get_market", {"ticker": "../series/KXNFLGAME"})
    assert res.is_error and "not a valid market ticker" in res.content[0].text
    assert seen == []


async def test_key_tools_explain_a_missing_key(api):
    _, keyed, _ = api
    keyed.add("/files")
    async with Client(server.server) as client:
        res = await client.call_tool("list_files", {"dataset": "trades", "start_date": "2026-10-13", "end_date": "2026-10-13"})
    assert res.is_error
    assert "needs a Kalshi Eye API key" in res.content[0].text


async def test_sends_the_key_when_set(api, monkeypatch):
    routes, keyed, seen = api
    routes["/files"] = {"files": [], "next_cursor": None}
    keyed.add("/files")
    monkeypatch.setenv("KALSHIEYE_API_KEY", "clab_good")
    async with Client(server.server) as client:
        await client.call_tool("list_files", {"dataset": "trades", "start_date": "2026-10-13", "end_date": "2026-10-13", "cursor": "abc"})
    assert seen[0].headers["Authorization"] == "Bearer clab_good"
    assert seen[0].url.params["cursor"] == "abc"


async def test_a_placeholder_key_is_ignored(api, monkeypatch):
    routes, _, seen = api
    routes["/search"] = {"series": [], "events": [], "markets": []}
    monkeypatch.setenv("KALSHIEYE_API_KEY", "optional: clab_...")
    async with Client(server.server) as client:
        res = await client.call_tool("search", {"query": "fed"})
    assert not res.is_error
    assert "Authorization" not in seen[0].headers


async def test_a_rejected_key_does_not_break_public_tools(api, monkeypatch):
    routes, keyed, seen = api
    routes["/search"] = {"series": [], "events": [], "markets": []}
    keyed.add("/files")
    monkeypatch.setenv("KALSHIEYE_API_KEY", "clab_revoked")
    async with Client(server.server) as client:
        ok = await client.call_tool("search", {"query": "fed"})
        bad = await client.call_tool("list_files", {"dataset": "trades", "start_date": "2026-10-13", "end_date": "2026-10-13"})
    assert not ok.is_error
    assert [r.headers.get("Authorization") for r in seen[:2]] == ["Bearer clab_revoked", None]
    assert bad.is_error and "rejected the key" in bad.content[0].text


async def test_download_links_limits(api, monkeypatch):
    monkeypatch.setenv("KALSHIEYE_API_KEY", "clab_good")
    async with Client(server.server) as client:
        res = await client.call_tool("download_links", {"keys": [f"k{i}" for i in range(101)]})
    assert res.is_error and "At most 100 keys" in res.content[0].text
