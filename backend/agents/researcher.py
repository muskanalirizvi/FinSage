import json

from langchain.agents import create_agent
from langchain_core.messages import ToolMessage

from backend.config import with_fallback
from backend.state import FinSageState
from backend.tools import load_tools

EXPECTED_TOOLS = ["get_stock_data", "get_financials", "get_sec_filing", "search_news"]
NEWS_SNIPPET_CHARS = 800  # long enough for concrete facts, short enough for Groq's token limits

SYSTEM_PROMPT = """You are the Researcher in a financial research pipeline.
Given a stock ticker, call each of these tools exactly once:
1. get_stock_data (the ticker)
2. get_financials (the ticker)
3. get_sec_filing (the ticker, filing_type "10-K")
4. search_news (query: "<ticker> stock news")
Then reply with 3-5 short bullet points of notes: what the data shows and
anything that looks odd or conflicting. If a tool returned an error, say so.
Never invent numbers. Max 150 words."""


def _trim_news(news: dict) -> dict:
    """Keep title, link, date and a short snippet of each article."""
    if "articles" not in news:
        return news  # an error dict, keep as-is
    return {
        "query": news.get("query"),
        "articles": [
            {
                "title": a.get("title"),
                "url": a.get("url"),
                "published_date": a.get("published_date"),
                "snippet": (a.get("content") or "")[:NEWS_SNIPPET_CHARS],
            }
            for a in news["articles"]
        ],
    }


def _extract_evidence(messages) -> dict:
    """Pull the raw tool results out of the conversation (exact numbers, no LLM)."""
    evidence = {}
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.name in EXPECTED_TOOLS:
            try:
                data = json.loads(msg.text)
            except json.JSONDecodeError:
                data = {"error": f"Tool returned non-JSON output: {msg.text[:200]}"}
            evidence[msg.name] = _trim_news(data) if msg.name == "search_news" else data
    evidence["missing_tools"] = [t for t in EXPECTED_TOOLS if t not in evidence]
    evidence["failed_tools"] = [t for t in EXPECTED_TOOLS if "error" in evidence.get(t, {})]
    return evidence


async def researcher_node(state: FinSageState) -> dict:
    tools = await load_tools()

    async def run(llm):
        agent = create_agent(model=llm, tools=tools, system_prompt=SYSTEM_PROMPT)
        return await agent.ainvoke(
            {"messages": [("user", f"Research this ticker: {state['ticker']}")]}
        )

    result = await with_fallback("researcher", run)
    return {
        "evidence": _extract_evidence(result["messages"]),
        "research_notes": result["messages"][-1].text,
    }