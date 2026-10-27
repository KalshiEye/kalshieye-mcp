# Kalshi Eye MCP server

<!-- mcp-name: io.github.KalshiEye/kalshieye-mcp -->

An [MCP](https://modelcontextprotocol.io) server that lets AI assistants such as Claude and Cursor search the [Kalshi Eye](https://kalshieye.com) archive of prediction market data. It can find Kalshi, Polymarket and Limitless markets, show how a market's price moved, check what was recorded, and list the order book files you can download.

It needs a Kalshi Eye API key: create one at [API keys](https://kalshieye.com/app/api/) (a free account works) and set it as `KALSHIEYE_API_KEY`.

## Install

Claude Code:

```bash
claude mcp add kalshieye -e KALSHIEYE_API_KEY=clab_your_key -- uvx kalshieye-mcp
```

Claude Desktop, Cursor and other clients (`claude_desktop_config.json`, `.cursor/mcp.json`, ...):

```json
{
  "mcpServers": {
    "kalshieye": {
      "command": "uvx",
      "args": ["kalshieye-mcp"],
      "env": { "KALSHIEYE_API_KEY": "clab_your_key" }
    }
  }
}
```

Without a key, or with a placeholder, every tool answers with how to get one. Listing files and download links cover the datasets your plan includes.

`uvx` comes with [uv](https://docs.astral.sh/uv/). With pip instead: `pip install kalshieye-mcp`, then use `kalshieye-mcp` as the command.

## Tools

| Tool | What it does |
|---|---|
| `search` | Find series, events and markets by keyword, venue, category or status. Series come a page at a time (`series_total`, `has_more`, `offset`); events and markets are the 10 best matches, with `events_found`, `markets_found` and `more_markets`, the paged call that lists every matching market |
| `get_series` | One series: what it is, how often it runs, markets in the catalog, and days of data files |
| `list_markets` | A series' markets, or every Kalshi market matching `q`, newest first, with status and result. A page at a time: `total` (null on the all-markets list) and `next_offset`, passed back as `offset` until it is null |
| `get_market` | One market's terms, status, result, and how much of it was recorded |
| `market_price_history` | The recorded YES bid/ask path, up to about 240 points over the market's busiest stretch; `path_source` is `life`, `busiest` or `window` |
| `list_datasets` | Every dataset: what it holds, columns, plan, days available |
| `dataset_series` | Which series have files in a dataset, with days, rows and size, up to 500 a page with `total` and `next_offset` |
| `recording_status` | Whether recording is running, and the recorded share of recent days by venue |
| `list_files` | Daily Parquet files for a dataset, date range and series, page by page |
| `download_links` | Signed download URLs for up to 100 of those files (counts toward the monthly allowance) |

Things to ask:

- "Which bitcoin markets does Kalshi Eye record, and since when?"
- "What were the last few hours of the Bills vs Rams market on October 12 like?"
- "How much of the Fed decision series is in the order book files?"
- "Is the recorder running, and how complete was last week?"

## Notes

- Kalshi is recorded since October 12, 2026; Polymarket, Limitless and Chainlink prices since October 15, 2026. Each UTC day is published the next morning.
- Prices are dollars between 0 and 1. A Kalshi YES ask is 1 minus the best NO bid. Times are UTC.
- Free data without any key: a [one-day sample on Hugging Face](https://huggingface.co/datasets/KalshiEye/kalshi-order-book-sample) and [runnable examples](https://github.com/KalshiEye/kalshieye-examples). The Python client for downloading files is [`kalshieye`](https://pypi.org/project/kalshieye/).
- `KALSHIEYE_BASE_URL` points the server at another deployment (default `https://kalshieye.com`).

Kalshi Eye is independent and is not affiliated with Kalshi, Polymarket or Limitless. MIT licensed.
