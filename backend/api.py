"""FinSage API: runs the research pipeline for a ticker and streams its progress."""

import asyncio
import json
import os
import re
import time
import traceback
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.graph import build_graph

CACHE_TTL_SECONDS = 6 * 3600   # reuse a finished report for 6 hours (saves free-tier quota)
MAX_CONCURRENT_RUNS = 1        # free-tier model limits can't handle parallel runs
RATE_LIMIT_RUNS = int(os.getenv("RATE_LIMIT_RUNS", "5"))  # fresh reports per visitor...
RATE_LIMIT_WINDOW = 3600       # ...per hour (cached reports are free and never counted)
TICKER_PATTERN = re.compile(r"^[A-Z]{1,5}([.-][A-Z]{1,2})?$")

SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "FinSage contact-not-set@example.com")
KNOWN_TICKERS_TTL = 24 * 3600

app = FastAPI(title="FinSage API")

origins = [o.strip() for o in os.getenv(
    "FRONTEND_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"])

graph = build_graph()
cache: dict = {}  # ticker -> (timestamp, payload)
run_slots = asyncio.Semaphore(MAX_CONCURRENT_RUNS)
run_log: dict = {}  # visitor ip -> timestamps of the fresh runs they started


def client_ip(request: Request) -> str:
    """The visitor's address. Behind Render's proxy it is the first entry of X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_wait(ip: str) -> int:
    """0 if this visitor may start a fresh run, otherwise the minutes until they may."""
    now = time.time()
    for key in [k for k, v in run_log.items() if not v or now - v[-1] > RATE_LIMIT_WINDOW]:
        del run_log[key]  # forget visitors with no recent runs, so the dict stays small
    recent = [t for t in run_log.get(ip, []) if now - t < RATE_LIMIT_WINDOW]
    run_log[ip] = recent
    if len(recent) >= RATE_LIMIT_RUNS:
        return max(1, round((recent[0] + RATE_LIMIT_WINDOW - now) / 60))
    return 0


def clean_ticker(raw: str) -> str:
    ticker = raw.strip().upper().replace(".", "-")  # BRK.B -> BRK-B, the form the data sources use
    if not TICKER_PATTERN.match(ticker):
        raise HTTPException(status_code=400, detail="Enter a stock ticker such as AAPL or MSFT.")
    return ticker


known_tickers = {"loaded_at": 0.0, "symbols": None}


def _fetch_sec_tickers() -> set:
    response = requests.get("https://www.sec.gov/files/company_tickers.json",
                            headers={"User-Agent": SEC_USER_AGENT}, timeout=15)
    response.raise_for_status()
    return {entry["ticker"].upper() for entry in response.json().values()}


async def ticker_exists(ticker: str) -> bool:
    """Is this a US-listed company? Checked against the SEC list, which is refreshed daily.
    If the list cannot be loaded right now, let the run go ahead instead of blocking everyone."""
    now = time.time()
    if known_tickers["symbols"] is None or now - known_tickers["loaded_at"] > KNOWN_TICKERS_TTL:
        try:
            known_tickers["symbols"] = await asyncio.to_thread(_fetch_sec_tickers)
            known_tickers["loaded_at"] = now
        except Exception:  # noqa: BLE001
            return True
    return ticker in known_tickers["symbols"]


def not_found_message(ticker: str) -> str:
    return f"{ticker} was not found among US-listed companies. Check the symbol."


def cached_payload(ticker: str):
    hit = cache.get(ticker)
    if hit and time.time() - hit[0] < CACHE_TTL_SECONDS:
        return {**hit[1], "cached": True}
    return None


def progress_message(node: str, update: dict) -> str:
    if node == "researcher":
        failed = (update.get("evidence") or {}).get("failed_tools") or []
        note = f" ({len(failed)} source(s) unavailable)" if failed else ""
        return "Gathered stock data, SEC financials, filings and news" + note
    if node == "analyst":
        return "Cross-checked the news against the SEC numbers"
    if node == "writer":
        return "Rewrote the draft using the Verifier's feedback" if update.get("revisions") \
            else "Drafted the brief"
    if node == "verifier":
        last = (update.get("verification_history") or [{}])[-1]
        flagged, total = last.get("flagged", 0), last.get("total", 0)
        if update.get("feedback"):
            return f"Flagged {flagged} of {total} claims; sending them back to the Writer"
        return f"Checked {total} claims: {flagged} flagged" if flagged else f"All {total} claims verified"
    return node


def build_payload(ticker: str, state: dict) -> dict:
    verification = state.get("verification", {})
    return {
        "ticker": ticker,
        "report_markdown": state["report"],
        "verification": {
            "verified": verification.get("verified", 0),
            "flagged": verification.get("flagged", 0),
            "passes": [{"total": h["total"], "flagged": h["flagged"]}
                       for h in state.get("verification_history", [])],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def run_events(ticker: str, ip: str):
    """Yield (event, data) pairs: 'queued', 'progress', then 'result' or 'error'."""
    cached = cached_payload(ticker)
    if cached:
        yield "result", cached
        return

    wait = rate_limit_wait(ip)
    if wait:
        yield "error", {"status": 429, "message": f"Limit reached: {RATE_LIMIT_RUNS} new reports per hour. "
                                                  f"Try again in about {wait} minute(s). "
                                                  "Reports you already requested are still available instantly."}
        return

    if run_slots.locked():
        yield "queued", {"message": "Another report is being generated. Yours is next in line."}
    async with run_slots:
        cached = cached_payload(ticker)  # it may have been produced while we waited
        if cached:
            yield "result", cached
            return

        run_log.setdefault(ip, []).append(time.time())  # counts from the moment the run starts
        started = time.time()
        yield "progress", {"step": "start", "message": f"Researching {ticker}...", "elapsed": 0}
        state: dict = {"ticker": ticker}
        try:
            async for chunk in graph.astream({"ticker": ticker}, stream_mode="updates"):
                for node, update in chunk.items():
                    state.update(update)
                    elapsed = round(time.time() - started)
                    print(f"[{ticker}] {node} finished after {elapsed}s", flush=True)
                    yield "progress", {"step": node, "elapsed": elapsed,
                                       "message": progress_message(node, update)}
        except Exception as error:  # noqa: BLE001
            traceback.print_exc()  # the full details go to the server terminal
            yield "error", {"message": f"The run failed ({type(error).__name__}: {str(error)[:150]}). "
                                       "If this is a timeout or rate limit, try again in a minute. "
                                       "Otherwise see the server terminal for details."}
            return

        payload = build_payload(ticker, state)
        cache[ticker] = (time.time(), payload)
        yield "result", {**payload, "cached": False}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/research/{ticker}")
async def research(ticker: str, request: Request):
    """Run (or fetch from cache) the full report and return it in one response."""
    ticker = clean_ticker(ticker)
    if not await ticker_exists(ticker):
        raise HTTPException(status_code=404, detail=not_found_message(ticker))
    result = error = None
    async for event, data in run_events(ticker, client_ip(request)):  # consume everything so the run slot is released
        if event == "result":
            result = data
        elif event == "error":
            error = data
    if error:
        raise HTTPException(status_code=error.get("status", 502), detail=error["message"])
    return result


@app.get("/api/research/{ticker}/stream")
async def research_stream(ticker: str, request: Request):
    """Same as above, but streams progress as Server-Sent Events while the agents work."""
    ticker = clean_ticker(ticker)
    ip = client_ip(request)

    async def sse():
        if not await ticker_exists(ticker):  # tell the page why, without starting any agents
            yield f"event: error\ndata: {json.dumps({'message': not_found_message(ticker)})}\n\n"
            return
        async for event, data in run_events(ticker, ip):
            yield f"event: {event}\ndata: {json.dumps(data)}\n\n"

    return StreamingResponse(
        sse(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
    
@app.get("/debug/news")
def debug_news():
    """TEMPORARY: runs the news tool directly so we can see its real error on Render."""
    from backend.mcp_server.financial_mcp_server import search_news
    result = search_news("Cisco CSCO stock")
    return {
        "tavily_key_set": bool(os.getenv("TAVILY_API_KEY")),
        "error": result.get("error"),
        "articles": [a["title"] for a in result.get("articles", [])],
    }    