import asyncio
import json
import sys

from backend.agents.researcher import researcher_node


async def main():
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    out = await researcher_node({"ticker": ticker})
    print("=== NOTES ===")
    print(out["research_notes"])
    print("\n=== EVIDENCE ===")
    print("missing tools:", out["evidence"]["missing_tools"])
    print("failed tools:", out["evidence"]["failed_tools"])
    print(json.dumps(out["evidence"], indent=2)[:3500])


asyncio.run(main())