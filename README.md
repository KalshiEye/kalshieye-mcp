# Kalshi Eye MCP server

<!-- mcp-name: io.github.KalshiEye/kalshieye-mcp -->

An [MCP](https://modelcontextprotocol.io) server that lets AI assistants such as Claude and Cursor search the [Kalshi Eye](https://kalshieye.com) archive of prediction market data. It can find Kalshi, Polymarket and Limitless markets, show how a market's price moved, check what was recorded, and list the order book files you can download.

Searching, price history and coverage need no account. Add a Kalshi Eye API key to also list daily Parquet files and get download links.

## Install

Claude Code:

```bash
claude mcp add kalshieye -- uvx kalshieye-mcp
```

Claude Desktop, Cursor and other clients (`claude_desktop_config.json`, `.cursor/mcp.json`, ...):

```json
{
  "mcpServers": {
    "kalshieye": {
      "command": "uvx",
      "args": ["kalshieye-mcp"]
    }
  }
}
```

To list and download files too, add your key from [API keys](https://kalshieye.com/app/api/) to that entry:

```json
"env": { "KALSHIEYE_API_KEY": "clab_your_key" }
```

A missing or placeholder key is ignored, and a rejected key only affects the two file tools.

`uvx` comes with [uv](https://docs.astral.sh/uv/). With pip instead: `pip install kalshieye-mcp`, then use `kalshieye-mcp` as the command.

## Tools

| Tool | What it does | Key |
|---|---|---|
| `search` | Find series, events and markets by keyword, venue, category or status | No |
| `get_series` | One series: what it is, how often it runs, markets in the catalog, and days of data files | No |
| `list_markets` | A series' most recent markets, newest first, with status and result | No |
| `get_market` | One market's terms, status, result, and how much of it was recorded | No |
| `market_price_history` | A short recorded YES bid/ask path (up to about 40 points) | No |
| `list_datasets` | Every dataset: what it holds, columns, plan, days available | No |
| `dataset_series` | Which series have files in a dataset, with days, rows and size | No |
| `recording_status` | Whether recording is running, and the recorded share of recent days by venue | No |
| `list_files` | Daily Parquet files for a dataset, date range and series, page by page | Yes |
| `download_links` | Signed download URLs for up to 100 of those files (counts toward the monthly allowance) | Yes |

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
