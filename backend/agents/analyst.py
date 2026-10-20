import json

from backend.config import with_fallback
from backend.financials import financials_text
from backend.state import FinSageState

SYSTEM_PROMPT = """You are the Analyst in a financial research pipeline.
You receive evidence gathered by tools (stock data, reported financials from SEC
filings, SEC filing metadata, news), pre-computed metrics, and the Researcher's
notes. Use ONLY this material.

Write a short analysis with these five sections:
1. VALUATION - what the price, P/E, forward P/E and 52-week position suggest.
2. FUNDAMENTALS - revenue, profit and EPS trends from the reported financials.
3. CROSS-CHECKS - compare revenue, EPS and profit figures quoted in the news with
   the reported financials and list every mismatch (say if one figure is "adjusted"
   and the other is GAAP or diluted). Also list conflicts between sources, and any
   claim in the Researcher's notes that the evidence does not support.
4. RISKS & CATALYSTS - drawn from the news. Name the article by its id (for example news3).
5. DATA GAPS - tools that failed or returned nothing, plus what cannot be verified.

Rules:
- Never use a number that is not in the material.
- Use the pre-computed metrics instead of doing arithmetic yourself.
  "percent_of_way_from_52w_low_to_high" says how far up the 52-week range the
  price sits (e.g. 88.5 = 88.5% of the way from the low to the high). It is
  NOT a percentile; never call it one.
- Report what the sources say. Do NOT speculate about motives or meaning
  (for example, why an insider sold shares).
- A CONFLICT means two sources state incompatible facts. A source that simply
  does not mention something is NOT a conflict. A past event (such as earnings
  already reported) is not a future catalyst.
- Refer to news articles by their id (news1, news2, ...). Describe reporting periods by
  their end date (for example "the quarter ended 2026-06-27"), never as "Q3" or "FY2025".
- Do not compare with historical or industry averages unless the evidence states them.
- Each section: at most 3 bullets, one sentence each.
  The whole analysis must stay under 300 words."""


def _compute_metrics(stock: dict) -> dict:
    """Do the arithmetic in Python (LLMs are unreliable at maths)."""
    price = stock.get("current_price")
    high = stock.get("fifty_two_week_high")
    low = stock.get("fifty_two_week_low")
    pe = stock.get("pe_ratio")
    fpe = stock.get("forward_pe")
    metrics = {}
    if price and high:
        metrics["percent_below_52w_high"] = round((high - price) / high * 100, 1)
    if price and high and low and high != low:
        metrics["percent_of_way_from_52w_low_to_high"] = round((price - low) / (high - low) * 100, 1)
    if pe and fpe:
        metrics["forward_pe_percent_below_trailing_pe"] = round((pe - fpe) / pe * 100, 1)
    return metrics


async def analyst_node(state: FinSageState) -> dict:
    evidence = state.get("evidence", {})
    stock = evidence.get("get_stock_data") or {}
    news = evidence.get("search_news") or {}
    if "articles" in news:  # give each article an id the Writer can cite
        news = {**news, "articles": [{"id": f"news{i}", **a}
                                     for i, a in enumerate(news["articles"], start=1)]}
    payload = {
        "stock": stock,
        "reported_financials (growth is vs the same period a year earlier)":
            financials_text(evidence.get("get_financials")) or "unavailable",
        "sec_filing": evidence.get("get_sec_filing"),
        "news": news,
        "computed_metrics": _compute_metrics(stock),
        "tool_problems": {
            "not_called": evidence.get("missing_tools"),
            "failed": evidence.get("failed_tools"),
        },
    }
    user_message = (
        f"EVIDENCE:\n{json.dumps(payload, indent=2)}\n\n"
        f"RESEARCHER NOTES:\n{state.get('research_notes', '')}"
    )
    reply = await with_fallback(
        "analyst",
        lambda llm: llm.ainvoke([("system", SYSTEM_PROMPT), ("user", user_message)]),
    )
    return {"analysis": reply.text}