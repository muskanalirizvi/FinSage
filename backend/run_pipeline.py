import asyncio
import sys
import traceback
from pathlib import Path

from backend.graph import build_graph


async def main():
    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
    show_all = len(sys.argv) > 2 and sys.argv[2] == "full"

    try:
        result = await build_graph().ainvoke({"ticker": ticker})
    except Exception as error:  # noqa: BLE001
        traceback.print_exc()
        print(f"\nThe run failed: {type(error).__name__}: {str(error)[:300]}")
        print("This is usually a network timeout or a free-tier rate limit. "
              "Wait a minute and run it again.")
        sys.exit(1)

    if show_all:
        print("=== RESEARCHER NOTES ===")
        print(result["research_notes"])
        print("\n=== ANALYSIS ===")
        print(result["analysis"])
        print("\n=== VERIFICATION HISTORY ===")
        for i, h in enumerate(result.get("verification_history", []), start=1):
            print(f"pass {i}: {h['flagged']} of {h['total']} flagged")
            for reason in h.get("reasons", []):
                print(f"   - {reason}")
        print("\n=== REPORT ===")
    print(result["report"])

    out_dir = Path("reports")
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"{ticker}.md"
    out_file.write_text(result["report"], encoding="utf-8")
    print(f"\n(saved to {out_file})")


asyncio.run(main())