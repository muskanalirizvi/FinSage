import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.agents.analyst import _compute_metrics
from backend.config import structured, with_fallback
from backend.financials import financial_rows, financials_text
from backend.state import FinSageState


class Claim(BaseModel):
    text: str = Field(description="One factual sentence, max 25 words.")
    source: str = Field(description="Exactly one source id from ALLOWED SOURCES, e.g. stock, fin, sec, news1.")


class InvestmentReport(BaseModel):
    headline: str = Field(description="One short sentence. (Replaced by code that builds it from data.)")
    stance: Literal["Bullish", "Neutral", "Bearish", "Insufficient data"]
    thesis_points: list[Claim] = Field(description="3 to 4 points supporting the stance.")
    risks: list[Claim] = Field(description="0 to 4 risks; an empty list if the evidence shows no adverse facts.")


SYSTEM_PROMPT = """You are the Writer in a financial research pipeline.
Turn the Analyst's work into a short research brief, returned as structured data.

Rules:
- Use ONLY facts found in the ANALYSIS or KEY FACTS. Never add numbers or events.
- Every claim must cite exactly one source id from ALLOWED SOURCES (e.g. "news2").
- Give 3-4 thesis points and up to 4 risks. Each claim: one sentence, max 25 words.
- Never pad the risks. If the sources show no real adverse fact, return an empty risks
  list. A routine daily price move is not a risk.
- Thesis points are supporting facts (price position, valuation, earnings results,
  analyst targets). Risks are adverse facts (cost pressure, supply-chain warnings,
  insider selling). Never repeat a fact, in the same section or in the other one.
- One fact per claim, from one source. Never combine facts from different sources
  in a single claim.
- Never write source ids (news1, fin, stock...) inside the claim text. State the fact;
  the citation tag is added for you.
- Every claim must state a concrete fact: include the number, date or named party.
  Never write vague statements such as "X is noted" or "Y is reported".
- Stance: Bullish, Neutral or Bearish based on the evidence. Use "Insufficient data"
  if the stock data or the news is missing or failed.
- This is research, not advice: never tell the reader to buy or sell.
- State facts only. Add no interpretation, motive or prediction: avoid words like
  "indicating", "signaling", "reflecting", "suggesting", "raising concerns".
  This applies to the headline too.
- Cite the source that actually contains the fact: price, P/E and 52-week data come
  from "stock"; revenue, operating income, net income and EPS come from "fin" (reported
  financials from SEC filings); analyst targets, insider trades and other news facts
  come from the news article that states them. If a news article gives a different
  figure than "fin", use "fin".
- Describe reporting periods by their end date (for example "the quarter ended
  2026-06-27"), never as "Q3" or "FY2026"."""


def _money(x) -> str:
    return f"${x:,.2f}" if isinstance(x, (int, float)) else "n/a"


def _big(x) -> str:
    if not isinstance(x, (int, float)):
        return "n/a"
    for divisor, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if x >= divisor:
            return f"${x / divisor:.2f}{suffix}"
    return f"${x:,.0f}"


def _num(x) -> str:
    return f"{x:.2f}" if isinstance(x, (int, float)) else "n/a"


def _build_sources(evidence: dict) -> dict:
    """Short ids the Writer can cite, mapped to a readable label."""
    sources = {"stock": "Stock data (yfinance)"}
    if financial_rows(evidence.get("get_financials")):
        sources["fin"] = "Reported financials (SEC EDGAR XBRL data)"
    sources["sec"] = "SEC filing metadata (EDGAR)"
    news = evidence.get("search_news") or {}
    for i, article in enumerate(news.get("articles", []), start=1):
        date = (article.get("published_date") or "")[:16]
        sources[f"news{i}"] = f"{article.get('title')} ({date}) - {article.get('url')}"
    return sources


STALE_DAYS = 30


def _article_age_days(published: str):
    try:
        when = parsedate_to_datetime(published)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).days


def build_data_gaps(evidence: dict, report: InvestmentReport) -> list:
    """Limitations written by code from what actually happened, so they can't be wrong."""
    names = {"get_stock_data": "Stock data", "get_financials": "Reported financials",
             "get_sec_filing": "SEC filing data", "search_news": "News search"}
    gaps = [f"{names.get(t, t)} was unavailable in this run."
            for t in (evidence.get("failed_tools") or []) + (evidence.get("missing_tools") or [])]
    if not financial_rows(evidence.get("get_financials")):
        gaps.append("Without reported financials, revenue and earnings figures come from news "
                    "articles and are not checked against SEC filings.")
    news_ev = evidence.get("search_news") or {}
    articles = news_ev.get("articles", [])
    if articles:
        gaps.append("News claims are checked against article titles and short snippets, "
                    "not the full articles.")
    elif "articles" in news_ev:
        gaps.append("No recent news articles (within 45 days) were found, so the brief has "
                    "no news-based claims.")
    cited = {c.source for c in report.thesis_points + report.risks}
    for i, article in enumerate(articles, start=1):
        age = _article_age_days(article.get("published_date") or "")
        if f"news{i}" in cited and age is not None and age > STALE_DAYS:
            gaps.append(f"Source [news{i}] is {age} days old.")
    return gaps


def build_headline(evidence: dict, ticker: str) -> str:
    """The headline is built from tool data only, so it can never contain an unsupported claim."""
    stock = evidence.get("get_stock_data") or {}
    metrics = _compute_metrics(stock)
    name = stock.get("company_name") or ticker
    price, high = stock.get("current_price"), stock.get("fifty_two_week_high")
    if not (price and high and "percent_below_52w_high" in metrics):
        return f"{name}: market data was not available."
    text = (f"{name} trades at ${price:,.2f}, {metrics['percent_below_52w_high']}% below its "
            f"52-week high of ${high:,.2f}")
    fin = evidence.get("get_financials") or {}
    block = None if "error" in fin else (fin.get("latest_quarter") or fin.get("annual"))
    if block and block.get("revenue") is not None:
        kind = "quarter" if fin.get("latest_quarter") else "fiscal year"
        text += f"; revenue for the {kind} ended {block['period_end']} was {_big(block['revenue'])}"
        growth = block.get("revenue_growth_percent")
        if growth is not None:
            text += f" ({growth:+.1f}% year over year)"
    return text + "."


def render_report(
    ticker: str,
    report: InvestmentReport,
    evidence: dict,
    sources: dict,
    verification_md: str = "",
) -> str:
    """Build the Markdown brief. Numbers in the tables come from tool data, not the LLM."""
    stock = evidence.get("get_stock_data") or {}
    filing = evidence.get("get_sec_filing") or {}
    metrics = _compute_metrics(stock)
    name = stock.get("company_name") or ticker
    pos = metrics.get("percent_of_way_from_52w_low_to_high")
    position = f"{pos:.1f}% of the way from low to high" if pos is not None else "n/a"

    fin_rows = financial_rows(evidence.get("get_financials"))
    fin_table = []
    if fin_rows:
        fin_table = [
            "## Reported financials (SEC filings)",
            "",
            "| Period | Revenue | Operating income | Net income | Diluted EPS |",
            "|---|---|---|---|---|",
            *[f"| {' | '.join(row)} |" for row in fin_rows],
            "",
            "*Growth is versus the same period a year earlier.*",
            "",
        ]

    stale = {}  # news ids older than STALE_DAYS -> age in days
    for i, article in enumerate((evidence.get("search_news") or {}).get("articles", []), start=1):
        age = _article_age_days(article.get("published_date") or "")
        if age is not None and age > STALE_DAYS:
            stale[f"news{i}"] = age

    def claim_line(c: Claim) -> str:
        if c.source not in sources:
            return f"- {c.text} [unlisted source]"
        age_note = f", {stale[c.source]} days old" if c.source in stale else ""
        return f"- {c.text} [{c.source}{age_note}]"

    lines = [
        f"# {name} ({ticker}) - Research Brief",
        "",
        f"**Overall read (the model's opinion, not verified):** {report.stance}",
        "",
        f"> {report.headline}",
        "",
        "## Key metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Price | {_money(stock.get('current_price'))} |",
        f"| Market cap | {_big(stock.get('market_cap'))} |",
        f"| P/E (trailing / forward) | {_num(stock.get('pe_ratio'))} / {_num(stock.get('forward_pe'))} |",
        f"| 52-week range | {_money(stock.get('fifty_two_week_low'))} - {_money(stock.get('fifty_two_week_high'))} |",
        f"| Position in 52-week range | {position} |",
        f"| Latest 10-K filed | {filing.get('filing_date', 'n/a')} |",
        "",
        *fin_table,
        "## Thesis",
        "",
        *[claim_line(c) for c in report.thesis_points],
        "",
        "## Risks",
        "",
        *([claim_line(c) for c in report.risks]
          or ["- No adverse facts were found in the retrieved sources."]),
        "",
        "## Data gaps and limitations",
        "",
        *[f"- {gap}" for gap in build_data_gaps(evidence, report)],
        "",
        *(["## Verification", "", verification_md, ""] if verification_md else []),
        "## Sources",
        "",
        *[f"- [{sid}] {label}" for sid, label in sources.items()],
        "",
        "---",
        "*Automated research summary for educational purposes. Not financial advice.*",
    ]
    return "\n".join(lines)


def normalize_periods(text: str, evidence: dict) -> str:
    """For claims about the SEC financials: turn 'FY2026' or 'Q3 FY2026' into the exact period
    end date, but only when the year matches the filing (otherwise leave it to be flagged)."""
    fin = evidence.get("get_financials") or {}
    annual_end = (fin.get("annual") or {}).get("period_end")
    quarter_end = (fin.get("latest_quarter") or {}).get("period_end")

    def phrase(end: str, kind: str):
        def replace(m):
            words = f"the {kind} ended {end}"
            return words[0].upper() + words[1:] if m.start() == 0 else words
        return replace

    flags = re.IGNORECASE
    if quarter_end:
        quarter_year = int(quarter_end[:4])

        def quarter_with_year(m):
            year = int(next(g for g in m.groups() if g))
            return phrase(quarter_end, "quarter")(m) if year == quarter_year else m.group(0)

        text = re.sub(r"\bQ[1-4]\s*(?:FY|fiscal\s*(?:year\s*)?)\s*(\d{4})\b"
                      r"|\b(?:FY|fiscal\s*(?:year\s*)?)\s*(\d{4})\s*Q[1-4]\b",
                      quarter_with_year, text, flags=flags)
        text = re.sub(r"\bQ[1-4]\b", phrase(quarter_end, "quarter"), text, flags=flags)
    if annual_end:
        annual_year = int(annual_end[:4])

        def fiscal_year(m):
            return phrase(annual_end, "fiscal year")(m) if int(m.group(1)) == annual_year else m.group(0)

        text = re.sub(r"\b(?:FY|fiscal(?:\s+year)?)\s*(\d{4})\b", fiscal_year, text, flags=flags)
    return text


async def writer_node(state: FinSageState) -> dict:
    evidence = state.get("evidence", {})
    stock = evidence.get("get_stock_data") or {}
    sources = _build_sources(evidence)

    key_facts = {
        "company": stock.get("company_name"),
        "ticker": state.get("ticker"),
        "price": stock.get("current_price"),
        "pe_ratio": stock.get("pe_ratio"),
        "forward_pe": stock.get("forward_pe"),
        "computed_metrics": _compute_metrics(stock),
        "reported_financials (source: fin)": financials_text(evidence.get("get_financials")) or "unavailable",
        "tool_problems": {
            "not_called": evidence.get("missing_tools"),
            "failed": evidence.get("failed_tools"),
        },
    }
    allowed = "\n".join(f"[{sid}] {label[:90]}" for sid, label in sources.items())
    user_message = (
        f"ANALYSIS:\n{state.get('analysis', '')}\n\n"
        f"KEY FACTS:\n{json.dumps(key_facts, indent=2)}\n\n"
        f"ALLOWED SOURCES:\n{allowed}"
    )
    feedback = state.get("feedback", "")
    if feedback:  # second attempt: the Verifier rejected parts of the first draft
        user_message += (
            "\n\nYOUR PREVIOUS DRAFT WAS CHECKED AND THESE ITEMS FAILED:\n"
            f"{feedback}\n"
            "Rewrite the whole brief. For each failed item, remove it or restate ONLY what "
            "its source says, citing the source id where that fact really appears. "
            "Add no interpretation, motive or prediction anywhere, including the headline."
        )

    async def write(llm):
        return await structured(llm, InvestmentReport).ainvoke(
            [("system", SYSTEM_PROMPT), ("user", user_message)]
        )

    report = await with_fallback("writer", write)
    report.headline = build_headline(evidence, state["ticker"])  # built by code, never by the model
    for claim in report.thesis_points + report.risks:  # fix period wording in code, not by asking again
        if claim.source == "fin":
            claim.text = normalize_periods(claim.text, evidence)

    return {
        "report": render_report(state["ticker"], report, evidence, sources),
        "report_data": report.model_dump(),
        "sources": sources,
        "feedback": "",
        "revisions": state.get("revisions", 0) + (1 if feedback else 0),
    }