"""
FinSage — Financial MCP Server

Exposes financial data tools over MCP so LangGraph agents can call them.

Tools:
  1. get_stock_data  -> yfinance (live price + fundamentals)
  2. get_sec_filing  -> SEC EDGAR (latest 10-K / 10-Q metadata)
  3. search_news     -> Tavily (recent news articles)
  4. get_financials  -> SEC EDGAR XBRL (reported revenue, profit, EPS)

Test with the Inspector:
    mcp dev backend/mcp_server/financial_mcp_server.py
"""

import functools
import os
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from itertools import zip_longest

import requests
import yfinance as yf
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from tavily import TavilyClient

load_dotenv()  # reads keys from the .env file in the project root

mcp = FastMCP("financial-research-agent")

# SEC requires a contact in the User-Agent header (set SEC_USER_AGENT in .env, or edit the fallback).
SEC_HEADERS = {"User-Agent": os.getenv("SEC_USER_AGENT", "FinSage muskanalirizvi1@gmail.com")}

# Words that mean "network hiccup" (worth retrying), not "bad input".
TRANSIENT = ("connection", "max retries", "timed out", "timeout", "getaddrinfo",
             "nameresolution", "temporarily", "503", "504", "429")


def with_retry(attempts: int = 4, delay: float = 3.0):
    """Re-run a tool if it returned a transient network error (waits longer each time)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            result = fn(*args, **kwargs)
            for attempt in range(attempts - 1):
                err = result.get("error", "") if isinstance(result, dict) else ""
                if not any(m in str(err).lower() for m in TRANSIENT):
                    break
                time.sleep(delay * (attempt + 1))  # waits 3s, 6s, 9s
                result = fn(*args, **kwargs)
            return result
        return wrapper
    return deco

def _round2(x):
    """Prices and ratios to 2 decimals, so every agent sees exactly the same number."""
    return round(x, 2) if isinstance(x, float) else x

@mcp.tool()
@with_retry()
def get_stock_data(ticker: str) -> dict:
    """
    Get current price, valuation, and key fundamentals for a stock ticker.

    Args:
        ticker: Stock ticker symbol, e.g. "AAPL", "TSLA", "MSFT".

    Returns:
        A dictionary with:
        - ticker: the symbol queried
        - company_name: full company name
        - current_price: latest market price
        - currency: price currency
        - market_cap: market capitalization
        - pe_ratio: trailing P/E ratio (None if not available)
        - forward_pe: forward P/E ratio (None if not available)
        - fifty_two_week_high / fifty_two_week_low
        - volume: latest trading volume
        - sector / industry
        - error: present only if the ticker could not be resolved
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        # yfinance returns a near-empty dict for invalid tickers instead of raising
        if not info or (info.get("regularMarketPrice") is None and info.get("currentPrice") is None):
            return {"ticker": ticker, "error": f"No data found for ticker '{ticker}'. Check the symbol."}

        return {
            "ticker": ticker.upper(),
            "company_name": info.get("longName") or info.get("shortName"),
            "current_price": _round2(info.get("currentPrice") or info.get("regularMarketPrice")),
            "currency": info.get("currency"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": _round2(info.get("trailingPE")),
            "forward_pe": _round2(info.get("forwardPE")),
            "fifty_two_week_high": _round2(info.get("fiftyTwoWeekHigh")),
            "fifty_two_week_low": _round2(info.get("fiftyTwoWeekLow")),
            "volume": info.get("volume") or info.get("regularMarketVolume"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


@mcp.tool()
@with_retry()
def get_sec_filing(ticker: str, filing_type: str = "10-K") -> dict:
    """
    Get the most recent SEC filing metadata for a company.

    Args:
        ticker: Stock ticker symbol, e.g. "AAPL".
        filing_type: Filing type to look for, e.g. "10-K" (annual report)
                      or "10-Q" (quarterly report). Defaults to "10-K".

    Returns:
        A dictionary with:
        - ticker, company_name, cik
        - filing_type, filing_date, accession_number
        - filing_url: link to the actual filing document
        - error: present only if no matching filing was found
    """
    try:
        # Step 1: resolve ticker -> CIK number (SEC's company ID)
        ticker_map_resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_HEADERS,
            timeout=15,
        )
        ticker_map_resp.raise_for_status()
        ticker_map = ticker_map_resp.json()

        cik = None
        company_name = None
        for entry in ticker_map.values():
            if entry["ticker"].upper() == ticker.upper():
                cik = str(entry["cik_str"]).zfill(10)
                company_name = entry["title"]
                break

        if not cik:
            return {"ticker": ticker, "error": f"Ticker '{ticker}' not found in SEC database."}

        # Step 2: get recent filings for that CIK
        filings_resp = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=SEC_HEADERS,
            timeout=15,
        )
        filings_resp.raise_for_status()
        filings = filings_resp.json()["filings"]["recent"]

        # Step 3: find the most recent filing of the requested type
        for i, form in enumerate(filings["form"]):
            if form == filing_type:
                accession = filings["accessionNumber"][i].replace("-", "")
                doc_name = filings["primaryDocument"][i]
                return {
                    "ticker": ticker.upper(),
                    "company_name": company_name,
                    "cik": cik,
                    "filing_type": filing_type,
                    "filing_date": filings["filingDate"][i],
                    "accession_number": filings["accessionNumber"][i],
                    "filing_url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{doc_name}",
                }

        return {"ticker": ticker, "error": f"No '{filing_type}' filing found for {ticker}."}

    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


# ---------- SEC financial statements (XBRL "company facts") ----------
# Companies label the same thing differently, so each metric lists the tags to look for.
FINANCIAL_METRICS = {
    "revenue": (["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"], "USD"),
    "operating_income": (["OperatingIncomeLoss"], "USD"),
    "net_income": (["NetIncomeLoss"], "USD"),
    "eps_diluted": (["EarningsPerShareDiluted"], "USD/shares"),
}


def _lookup_cik(ticker: str):
    resp = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS, timeout=15)
    resp.raise_for_status()
    for entry in resp.json().values():
        if entry["ticker"].upper() == ticker.upper():
            return str(entry["cik_str"]).zfill(10), entry["title"]
    return None, None


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _periods(entries: list, min_days: int, max_days: int) -> dict:
    """end date -> entry, for facts that cover a period of the wanted length."""
    found = {}
    for e in entries:
        if e.get("start") and e.get("end") and min_days <= _days(e["start"], e["end"]) <= max_days:
            if e["end"] not in found or e.get("filed", "") > found[e["end"]].get("filed", ""):
                found[e["end"]] = e
    return found


def _a_year_before(end: str, periods: dict):
    """The entry whose period ended about one year before `end`."""
    target = date.fromisoformat(end)
    for other_end, entry in periods.items():
        gap = (target - date.fromisoformat(other_end)).days
        if 350 <= gap <= 380:
            return entry
    return None


def _growth(current, prior):
    if current is None or not prior:
        return None
    return round((current - prior) / abs(prior) * 100, 1)


def _build_period(us_gaap: dict, min_days: int, max_days: int, after: str = ""):
    """Latest period of the wanted length, with the same period a year earlier."""
    per_metric = {}
    for name, (tags, unit) in FINANCIAL_METRICS.items():
        best = {}
        for tag in tags:  # use the tag with the most recent data
            periods = _periods(us_gaap.get(tag, {}).get("units", {}).get(unit, []), min_days, max_days)
            if periods and (not best or max(periods) > max(best)):
                best = periods
        if best:
            per_metric[name] = best
    if not per_metric:
        return None
    latest_end = max(max(p) for p in per_metric.values())
    if latest_end <= after:
        return None
    out = {"period_end": latest_end}
    for name, periods in per_metric.items():
        if latest_end not in periods:
            continue
        current = periods[latest_end]
        prior = _a_year_before(latest_end, periods)
        out[name] = current["val"]
        out[f"{name}_prior_year"] = prior["val"] if prior else None
        out[f"{name}_growth_percent"] = _growth(current["val"], prior["val"] if prior else None)
        out["filed"] = current.get("filed")
        out["form"] = current.get("form")
    return out


@mcp.tool()
@with_retry()
def get_financials(ticker: str) -> dict:
    """
    Get a company's reported financial results straight from its SEC filings
    (revenue, operating income, net income, diluted EPS), with growth versus the
    same period a year earlier.

    Args:
        ticker: Stock ticker symbol, e.g. "AAPL".

    Returns:
        A dictionary with:
        - ticker, company_name, source
        - annual: latest fiscal year from the 10-K (period_end, filed, form, and for each
          metric: the value, the prior-year value and growth_percent); null if the SEC has
          no annual figures for this company (for example a newly formed holding company)
        - latest_quarter: the most recent 10-Q quarter (3 months), if it is newer than the
          annual figures or there are no annual figures; otherwise null
        - values are in US dollars (eps in dollars per share)
        - error: present only if no financial data could be found at all
    """
    try:
        cik, company_name = _lookup_cik(ticker)
        if not cik:
            return {"ticker": ticker, "error": f"Ticker '{ticker}' not found in SEC database."}

        resp = requests.get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            headers=SEC_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        us_gaap = resp.json().get("facts", {}).get("us-gaap", {})

        annual = _build_period(us_gaap, 350, 380)
        quarter = _build_period(us_gaap, 80, 100, after=annual["period_end"] if annual else "")
        if annual is None and quarter is None:
            return {"ticker": ticker, "error": f"No US-GAAP financial data found for {ticker}."}
        return {
            "ticker": ticker.upper(),
            "company_name": company_name,
            "source": "SEC EDGAR XBRL company facts",
            "annual": annual,
            "latest_quarter": quarter,
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


NEWS_MAX_AGE_DAYS = 45  # older articles are history, not current news
RISK_TERMS = "risks concerns lawsuit regulation investigation downgrade"


def _news_age_days(published: str):
    try:
        when = parsedate_to_datetime(published)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).days


def _tavily_articles(client, query: str, wanted: int) -> list:
    """One Tavily news search, minus stock quote pages and old articles."""
    response = client.search(query=query, topic="news", max_results=wanted)
    articles = []
    for r in response.get("results", []):
        if "/quote/" in (r.get("url") or ""):  # price/option quote pages are not news
            continue
        age = _news_age_days(r.get("published_date") or "")
        if age is not None and age > NEWS_MAX_AGE_DAYS:
            continue
        articles.append(
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "content": r.get("content"),
                "published_date": r.get("published_date"),
            }
        )
    return articles


def _merge_news(general: list, risks: list, limit: int) -> list:
    """Alternate general and risk articles, skipping duplicate URLs."""
    merged, seen = [], set()
    for pair in zip_longest(general, risks):
        for article in pair:
            if article and article["url"] not in seen:
                seen.add(article["url"])
                merged.append(article)
    return merged[:limit]


@mcp.tool()
@with_retry()
def search_news(query: str, max_results: int = 6) -> dict:
    """
    Search recent news articles about a company or topic. Runs a general search
    and a risk-focused search (lawsuits, regulation, downgrades) and mixes them.

    Args:
        query: What to search for, e.g. "Apple AAPL earnings" or "Tesla stock news".
        max_results: Number of articles to return (default 6).

    Returns:
        A dictionary with:
        - query: the search text used
        - articles: list of {title, url, content, published_date}
          (only articles from the last 45 days; stock quote pages are skipped)
        - error: present only if the search failed
    """
    try:
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return {"query": query, "error": "TAVILY_API_KEY not found in .env file."}

        client = TavilyClient(api_key=api_key)
        # Ask for extra results, because some will be filtered out.
        general = _tavily_articles(client, query, max(max_results, 8))
        try:
            risks = _tavily_articles(client, f"{query} {RISK_TERMS}", 8)
        except Exception:
            risks = []  # risk search failed: use the general results only
        return {"query": query, "articles": _merge_news(general, risks, max_results)}

    except Exception as e:
        return {"query": query, "error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")