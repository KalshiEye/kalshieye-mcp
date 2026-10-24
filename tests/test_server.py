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
    """Answer API calls from a dict of path -> JSON, and record the requests."""
    routes: dict[str, object] = {}
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path.removeprefix("/api/v1")
        if path not in routes:
            return httpx.Response(401, json={"detail": "not authenticated"})
        return httpx.Response(200, json=routes[path])

    monkeypatch.setattr(server, "TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.delenv("KALSHIEYE_API_KEY", raising=False)
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
        out = _result(await client.call_tool("search", {"query": "bitcoin", "venue": "kalshi"}))
    assert out["series"] == [{"id": "KXBTC15M", "label": "Bitcoin price up down", "next_close_utc": "2026-10-13T00:15:00Z"}]
    assert out["markets"][0]["close_utc"] == "2026-10-13T00:15:00Z"
    assert seen[0].url.params["q"] == "bitcoin" and seen[0].url.params["venue"] == "kalshi"
    assert "category" not in seen[0].url.params


async def test_price_history(api):
    routes, _ = api
    routes["/markets/T/preview"] = {
        "ticker": "T",
        "series": "S",
        "coverage": {"first_print_ts": 1791850000.0, "last_print_ts": 1791850500.0, "has_l2": True},
        "path": [{"ts": 1791850000.0, "yes_best_bid": 0.4, "yes_best_ask": 0.42}],
    }
    async with Client(server.server) as client:
        out = _result(await client.call_tool("market_price_history", {"ticker": "T"}))
    assert out["path"] == [{"time_utc": "2026-10-13T00:06:40Z", "yes_bid": 0.4, "yes_ask": 0.42}]
    assert out["has_full_order_book"] is True


async def test_key_tools_explain_a_missing_key(api):
    async with Client(server.server) as client:
        res = await client.call_tool("list_files", {"dataset": "trades", "start_date": "2026-10-13", "end_date": "2026-10-13"})
    assert res.is_error
    assert "KALSHIEYE_API_KEY" in res.content[0].text


async def test_sends_the_key_when_set(api, monkeypatch):
    routes, seen = api
    routes["/files"] = {"files": []}
    monkeypatch.setenv("KALSHIEYE_API_KEY", "clab_test")
    async with Client(server.server) as client:
        await client.call_tool("list_files", {"dataset": "trades", "start_date": "2026-10-13", "end_date": "2026-10-13"})
    assert seen[0].headers["Authorization"] == "Bearer clab_test"
