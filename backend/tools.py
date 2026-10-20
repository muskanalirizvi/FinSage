import sys
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

SERVER = Path(__file__).resolve().parent / "mcp_server" / "financial_mcp_server.py"


async def load_tools():
    """Start the MCP server and return its tools as LangChain tools."""
    client = MultiServerMCPClient(
        {
            "financial": {
                "command": sys.executable,  # your venv's Python
                "args": [str(SERVER)],
                "transport": "stdio",
            }
        }
    )
    return await client.get_tools()