"""Runs the full FinSage pipeline on many tickers and measures how well it does.

    python -m backend.evaluate                    # built-in list of 13 tickers
    python -m backend.evaluate AAPL MSFT NVDA     # your own tickers
    python -m backend.evaluate --pause 15         # wait longer between runs

Results are printed as a table and saved to reports/evaluation.md and reports/evaluation.json.
"""

import argparse
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.financials import financial_rows
from backend.graph import build_graph

# Large US companies from different sectors (banks, energy and retail use different SEC labels),
# plus one ticker that does not exist, to check that failures are handled calmly.
DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META",
                   "JPM", "KO", "XOM", "JNJ", "WMT", "ZZZZ"]

# (label shown in the report, text to look for in a flag reason)
REASON_TYPES = [
    ("number not found in its source", "number not found"),
    ("opinion word", "opinion word"),
    ("cause-and-effect wording", "cause-and-effect"),
    ("Q3/FY label instead of end date", "end date"),
    ("judged speculative by the verifier model", "speculative"),
    ("judged unsupported by the verifier model", "unsupported"),
    ("duplicate claim", "duplicate"),
    ("vague claim", "uninformative"),
    ("source id written in the claim", "source ids"),
    ("verifier model unavailable", "not checked"),
]


class FallbackCounter(logging.Handler):
    """Counts how often a backup model had to take over."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.count = 0

    def emit(self, record):
        if "main model failed" in record.getMessage():
            self.count += 1


async def run_one(graph, ticker: str, counter: FallbackCounter) -> dict:
    counter.count = 0
    started = time.time()
    try:
        state = await graph.ainvoke({"ticker": ticker})
    except Exception as error:  # noqa: BLE001
        return {"ticker": ticker, "ok": False, "seconds": round(time.time() - started),
                "error": f"{type(error).__name__}: {str(error)[:120]}", "fallbacks": counter.count}

    history = state.get("verification_history", [])
    verification = state.get("verification", {})
    data = state.get("report_data", {})
    evidence = state.get("evidence", {})
    first = history[0] if history else {"total": 0, "flagged": 0, "reasons": []}
    return {
        "ticker": ticker,
        "ok": True,
        "seconds": round(time.time() - started),
        "passes": len(history),
        "first_total": first["total"],
        "first_flagged": first["flagged"],
        "claims_kept": len(data.get("thesis_points", [])) + len(data.get("risks", [])),
        "risks_kept": len(data.get("risks", [])),
        "claims_dropped": verification.get("flagged", 0),
        "headline_replaced": bool(verification.get("claims"))
        and verification["claims"][0]["status"] == "FLAGGED" and verification.get("flagged", 0) > 0,
        "has_financials": bool(financial_rows(evidence.get("get_financials"))),
        "news_articles": len((evidence.get("search_news") or {}).get("articles", [])),
        "failed_tools": evidence.get("failed_tools", []),
        "fallbacks": counter.count,
        "first_pass_reasons": first.get("reasons", []),
        "report": state.get("report", ""),
    }


def classify(reasons: list) -> dict:
    """How many flagged claims fall into each kind of problem (a claim can have several)."""
    counts = {label: 0 for label, _ in REASON_TYPES}
    for reason in reasons:
        for label, keyword in REASON_TYPES:
            if keyword in reason:
                counts[label] += 1
    return {label: n for label, n in counts.items() if n}


def table_rows(results: list) -> list:
    rows = []
    for r in results:
        if not r["ok"]:
            rows.append([r["ticker"], "FAILED", str(r["seconds"]), "-", "-", "-", "-", "-", "-", "-",
                         "-", str(r["fallbacks"]), r["error"][:40]])
            continue
        rows.append([
            r["ticker"], "ok", str(r["seconds"]), str(r["passes"]),
            f"{r['first_flagged']}/{r['first_total']}", str(r["claims_kept"]),
            str(r["risks_kept"]), str(r["claims_dropped"]),
            "yes" if r["headline_replaced"] else "no", "yes" if r["has_financials"] else "no",
            str(r["news_articles"]), str(r["fallbacks"]),
            ", ".join(r["failed_tools"]) or "-",
        ])
    return rows


HEADERS = ["Ticker", "Result", "Secs", "Passes", "1st flagged", "Kept", "Risks", "Dropped",
           "Headline fixed", "SEC table", "News", "Backup", "Failed tools"]


def summarize(results: list) -> list:
    ok = [r for r in results if r["ok"]]
    lines = [f"Runs completed: {len(ok)} of {len(results)}"]
    if not ok:
        return lines
    secs = sorted(r["seconds"] for r in ok)
    first_total = sum(r["first_total"] for r in ok)
    first_flagged = sum(r["first_flagged"] for r in ok)
    rewrote = sum(r["passes"] > 1 for r in ok)
    lines += [
        f"Time per run: median {secs[len(secs) // 2]}s, slowest {secs[-1]}s",
        f"Claims flagged on the first draft: {first_flagged} of {first_total} "
        f"({100 * first_flagged / max(first_total, 1):.0f}%)",
        f"Runs that needed at least one rewrite: {rewrote} of {len(ok)}",
        f"Claims dropped from the final briefs (still failing after rewrites): "
        f"{sum(r['claims_dropped'] for r in ok)}",
        f"Briefs with no risks listed: {sum(r['risks_kept'] == 0 for r in ok)} of {len(ok)}",
        f"Briefs where the headline had to be replaced by a data-built one: "
        f"{sum(r['headline_replaced'] for r in ok)} of {len(ok)}",
        f"Briefs with the SEC financials table: {sum(r['has_financials'] for r in ok)} of {len(ok)}",
        f"Runs where a backup model had to step in: {sum(r['fallbacks'] > 0 for r in results)} "
        f"of {len(results)}",
        "Every claim shown in a brief passed verification; claims that did not were removed.",
    ]
    return lines


def to_markdown(results: list, started: str) -> str:
    rows = table_rows(results)
    reasons = [x for r in results if r["ok"] for x in r["first_pass_reasons"]]
    kinds = classify(reasons)
    lines = [
        "# FinSage evaluation", "",
        f"Run on {started}: {len(results)} tickers, one after another, with the free-tier "
        "models and tools.", "",
        "| " + " | ".join(HEADERS) + " |",
        "|" + "---|" * len(HEADERS),
        *["| " + " | ".join(row) + " |" for row in rows],
        "", "## Summary", "",
        *[f"- {line}" for line in summarize(results)],
        "", "## Why claims were flagged on the first draft", "",
    ]
    if kinds:
        lines += ["| Reason | Claims |", "|---|---|"]
        lines += [f"| {label} | {n} |" for label, n in sorted(kinds.items(), key=lambda kv: -kv[1])]
    else:
        lines.append("No claims were flagged.")
    return "\n".join(lines) + "\n"


def print_table(results: list) -> None:
    rows = table_rows(results)
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(HEADERS)]
    line = "  ".join(h.ljust(w) for h, w in zip(HEADERS, widths))
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths)))


async def main():
    parser = argparse.ArgumentParser(description="Run FinSage on many tickers and measure the results.")
    parser.add_argument("tickers", nargs="*", help="tickers to run (default: a built-in list)")
    parser.add_argument("--pause", type=float, default=10,
                        help="seconds to wait between runs, to stay inside free-tier limits")
    args = parser.parse_args()
    tickers = [t.upper() for t in args.tickers] or DEFAULT_TICKERS

    counter = FallbackCounter()
    logging.getLogger("finsage").addHandler(counter)
    graph = build_graph()
    out_dir = Path("reports")
    out_dir.mkdir(exist_ok=True)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    results = []
    try:
        for i, ticker in enumerate(tickers, start=1):
            result = await run_one(graph, ticker, counter)
            results.append(result)
            if result["ok"]:
                (out_dir / f"{ticker}.md").write_text(result["report"], encoding="utf-8")
                print(f"[{i}/{len(tickers)}] {ticker}: done in {result['seconds']}s, "
                      f"{result['passes'] - 1} rewrite(s), {result['claims_kept']} claims kept", flush=True)
            else:
                print(f"[{i}/{len(tickers)}] {ticker}: FAILED ({result['error']})", flush=True)
            if i < len(tickers):
                await asyncio.sleep(args.pause)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nStopped early; reporting what finished so far.")

    if not results:
        return
    print()
    print_table(results)
    print()
    for line in summarize(results):
        print(line)
    kinds = classify([x for r in results if r["ok"] for x in r["first_pass_reasons"]])
    if kinds:
        print("\nWhy claims were flagged on the first draft:")
        for label, n in sorted(kinds.items(), key=lambda kv: -kv[1]):
            print(f"  {n:3d}  {label}")

    (out_dir / "evaluation.md").write_text(to_markdown(results, started), encoding="utf-8")
    slim = [{k: v for k, v in r.items() if k != "report"} for r in results]
    (out_dir / "evaluation.json").write_text(json.dumps(slim, indent=2), encoding="utf-8")
    print("\nSaved reports/evaluation.md and reports/evaluation.json "
          "(and each brief as reports/<TICKER>.md)")


asyncio.run(main())