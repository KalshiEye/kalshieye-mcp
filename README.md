# Kalshi Eye MCP server

<!-- mcp-name: io.github.KalshiEye/kalshieye-mcp -->

An [MCP](https://modelcontextprotocol.io) server that lets AI assistants such as Claude, ChatGPT and Cursor search the [Kalshi Eye](https://kalshieye.com) archive of prediction market data. It can find Kalshi, Polymarket and Limitless markets, show how a market's price moved, check what was recorded, and list the order book files you can download.

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
      "args": ["kalshieye-mcp"],
      "env": { "KALSHIEYE_API_KEY": "optional: clab_..." }
    }
  }
}
```

`uvx` comes with [uv](https://docs.astral.sh/uv/). With pip instead: `pip install kalshieye-mcp`, then use `kalshieye-mcp` as the command.

## Tools

| Tool | What it does | Key |
|---|---|---|
| `search` | Find series, events and markets by keyword, venue, category or status | No |
| `get_series` | One series: what it is, how often it runs, markets and days recorded | No |
| `list_markets` | A series' markets from the last 1 to 7 days, with status and result | No |
| `get_market` | One market's terms, status, result, and share of its life recorded | No |
| `market_price_history` | The recorded YES bid and ask over a market's life | No |
| `list_datasets` | Every dataset: what it holds, columns, plan, days available | No |
| `dataset_series` | Which series have files in a dataset, with days, rows and size | No |
| `recording_status` | Whether recording is running and the recorded share of recent days | No |
| `list_files` | Daily Parquet files for a dataset, date range and series | Yes |
| `download_links` | Signed download URLs for those files (counts toward the monthly allowance) | Yes |

Things to ask:

- "Which bitcoin markets does Kalshi Eye record, and since when?"
- "How did the Bills vs Rams market on October 12 trade over the game?"
- "How much of the Fed decision series is in the order book files?"
- "Is the recorder running, and how complete was last week?"

## Notes

- Kalshi is recorded since October 12, 2026; Polymarket, Limitless and Chainlink prices since October 15, 2026. Each UTC day is published the next morning.
- Prices are dollars between 0 and 1. A Kalshi YES ask is 1 minus the best NO bid. Times are UTC.
- Free data without any key: a [one-day sample on Hugging Face](https://huggingface.co/datasets/KalshiEye/kalshi-order-book-sample) and [runnable examples](https://github.com/KalshiEye/kalshieye-examples). The Python client for downloading files is [`kalshieye`](https://pypi.org/project/kalshieye/).
- `KALSHIEYE_BASE_URL` points the server at another deployment (default `https://kalshieye.com`).

Kalshi Eye is independent and is not affiliated with Kalshi, Polymarket or Limitless. MIT licensed.
