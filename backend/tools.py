import os
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
                # MCP only passes a few safe variables to the subprocess by default.
                # Pass everything so TAVILY_API_KEY and SEC_USER_AGENT reach the server on Render.
                "env": dict(os.environ),
            }
        }
    )
    return await client.get_tools()