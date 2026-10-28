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
        "search", "get_series", "list_markets", "list_events", "get_market", "market_price_history",
        "list_datasets", "dataset_series", "recording_status", "list_files", "download_links",
    }


async def test_search_trims_fields_and_converts_times(api):
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
    assert seen[0].url.params["limit"] == "1" and seen[0].url.params["offset"] == "0"
    assert "category" not in seen[0].url.params


async def test_search_pages_series_and_says_how_many_events_and_markets_matched(api):
    routes, seen = api
    routes["/search"] = {
        "series": [{"id": "KXFEDDECISION"}, {"id": "KXFED"}],
        "events": [{"id": f"E{i}"} for i in range(10)],
        "markets": [{"ticker": f"M{i}"} for i in range(10)],
        "series_total": 7,
        "has_more": True,
        "events_found": 37,
        "events_found_exact": True,
        "more_events": "GET /api/v1/events?q=fed",
        "markets_found": 10000,
        "markets_found_exact": False,
        "more_markets": "GET /api/v1/markets?q=fed",
    }
    async with Client(server.server) as client:
        out = _result(await client.call_tool("search", {"query": "fed", "limit": 2, "offset": 4}))
    assert seen[0].url.params["limit"] == "2" and seen[0].url.params["offset"] == "4"
    assert (out["series_total"], out["has_more"]) == (7, True)
    # limit counts series; events and markets are the API's best 10, not cut to limit
    assert len(out["series"]) == 2 and len(out["events"]) == 10 and len(out["markets"]) == 10
    assert (out["events_found"], out["events_found_exact"], out["more_events"]) == (37, True, "GET /api/v1/events?q=fed")
    # past 10,000 the count is a labeled lower bound
    assert (out["markets_found"], out["markets_found_exact"], out["more_markets"]) == (10000, False, "GET /api/v1/markets?q=fed")


async def test_list_markets_pages_one_series(api):
    routes, seen = api
    routes["/markets"] = {
        "count": 2,
        "total": 258,
        "offset": 40,
        "next_offset": 42,
        "source": "archive",
        "markets": [{"ticker": "KXFED-26DEC-T4.00", "close_ts": 1791850500.0}, {"ticker": "KXFED-26DEC-T4.25"}],
    }
    async with Client(server.server) as client:
        out = _result(await client.call_tool("list_markets", {"series": "KXFED", "limit": 2, "offset": 40}))
    assert dict(seen[0].url.params) == {"series": "KXFED", "limit": "2", "offset": "40"}
    assert (out["total"], out["offset"], out["returned"], out["next_offset"]) == (258, 40, 2, 42)
    assert "count" not in out
    assert out["markets"][0] == {"ticker": "KXFED-26DEC-T4.00", "close_utc": "2026-10-13T00:15:00Z"}


async def test_list_markets_searches_every_kalshi_market(api):
    routes, seen = api
    routes["/markets"] = {"count": 1, "total": None, "offset": 0, "next_offset": None, "markets": [{"ticker": "KXNBA-26-OKC"}]}
    async with Client(server.server) as client:
        out = _result(await client.call_tool("list_markets", {"q": "championship"}))
    assert dict(seen[0].url.params) == {"q": "championship", "limit": "20", "offset": "0"}
    assert out["total"] is None and out["next_offset"] is None and out["returned"] == 1


async def test_list_markets_pages_a_word_search_by_cursor(api):
    routes, seen = api
    routes["/markets"] = {"count": 1, "total": 10000, "total_exact": False, "offset": 0, "next_offset": None,
                          "next_cursor": "c2", "markets": [{"ticker": "KXBTCD-26OCT28-T1"}]}
    async with Client(server.server) as client:
        out = _result(await client.call_tool("list_markets", {"q": "bitcoin", "cursor": "c1", "limit": 1}))
    assert dict(seen[0].url.params) == {"q": "bitcoin", "limit": "1", "offset": "0", "cursor": "c1"}
    assert (out["total"], out["total_exact"], out["next_cursor"]) == (10000, False, "c2")


async def test_list_events_pages_every_event_holding_the_words(api):
    routes, seen = api
    routes["/events"] = {"count": 2, "total": 180, "total_exact": True, "next_cursor": "e2",
                         "events": [{"id": "KXNBAGAME-26OCT28LALBOS", "venue": "kalshi", "extra": 1}, {"id": "pm:lakers-celtics"}]}
    async with Client(server.server) as client:
        out = _result(await client.call_tool("list_events", {"query": "lakers", "venue": "kalshi", "limit": 2}))
    assert dict(seen[0].url.params) == {"q": "lakers", "venue": "kalshi", "limit": "2"}
    assert (out["total"], out["total_exact"], out["returned"], out["next_cursor"]) == (180, True, 2, "e2")
    assert out["events"][0] == {"id": "KXNBAGAME-26OCT28LALBOS", "venue": "kalshi"}


async def test_dataset_series_pages(api):
    routes, seen = api
    routes["/datasets/trades/series"] = {"dataset": "trades", "total": 1203, "series": [{"series": f"S{i}"} for i in range(500)]}
    async with Client(server.server) as client:
        out = _result(await client.call_tool("dataset_series", {"dataset_id": "trades", "limit": 900, "offset": 500}))
        assert seen[0].url.params["limit"] == "500" and seen[0].url.params["offset"] == "500"
        assert (out["total"], out["offset"], out["next_offset"]) == (1203, 500, 1000)
        assert len(out["series"]) == 500
        # the last page has no next page
        routes["/datasets/trades/series"] = {"dataset": "trades", "total": 1203, "series": [{"series": f"S{i}"} for i in range(203)]}
        out = _result(await client.call_tool("dataset_series", {"dataset_id": "trades", "limit": 500, "offset": 1000}))
    assert out["next_offset"] is None


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
