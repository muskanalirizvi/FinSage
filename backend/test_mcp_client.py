import asyncio
import sys
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

SERVER = Path(__file__).resolve().parent / "mcp_server" / "financial_mcp_server.py"


async def main():
    client = MultiServerMCPClient(
        {
            "financial": {
                "command": sys.executable,  # uses your venv's Python
                "args": [str(SERVER)],
                "transport": "stdio",
            }
        }
    )

    tools = await client.get_tools()
    print("Tools loaded:", [t.name for t in tools])

    stock = next(t for t in tools if t.name == "get_stock_data")
    print("Call result:", await stock.ainvoke({"ticker": "AAPL"}))


asyncio.run(main())