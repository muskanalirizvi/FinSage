import json
import re
from typing import Literal

from pydantic import BaseModel, Field

from backend.agents.analyst import _compute_metrics
from backend.agents.writer import InvestmentReport, render_report
from backend.config import structured, with_fallback
from backend.financials import financials_text
from backend.state import FinSageState

MAX_REVISIONS = 2  # how many times a flagged draft goes back to the Writer

# ---------- Check 1: numbers (plain Python, no LLM) ----------
# Models write non-breaking hyphens (U+2011) in things like "52-week", so treat all dashes alike.
_DASHES = "\\-\u2010-\u2015\u2212"
# A number may be followed by a unit letter ("$331.84B"), but not by other letters or dashes
# ("Q3", "10-K", "52-week").
_CLAIM_NUMBER = re.compile(
    rf"(?<![A-Za-z0-9.,])\d[\d,]*(?:\.\d+)?(?:(?=[BMTKbmtk](?![A-Za-z0-9]))|(?![\w{_DASHES}]))"
)
_ANY_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _claim_numbers(text: str):
    """Numbers in a claim as (raw text, value, decimals). Skips years, 'Q3', '52-week', '10-K'."""
    found = []
    for m in _CLAIM_NUMBER.finditer(text):
        raw = m.group().rstrip(",")
        value = float(raw.replace(",", ""))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        if 1900 <= value <= 2100 and decimals == 0 and "," not in raw:
            continue  # a year
        found.append((raw, value, decimals))
    return found


def _source_values(text: str) -> list:
    return [float(m.group().rstrip(",").replace(",", "")) for m in _ANY_NUMBER.finditer(text)]


def _found(value: float, decimals: int, source_values: list) -> bool:
    """Is this number in the source? Allows rounding, sign, and units (M/B/T)."""
    target = abs(value)
    for m in source_values:
        for scale in (1, 1e6, 1e9, 1e12):
            if scale > 1 and abs(m) < scale:
                continue
            if abs(round(abs(m) / scale, decimals) - target) < 1e-9:
                return True
    return False


def _source_text(source_id: str, evidence: dict) -> str:
    """The raw material a claim citing this source id must be backed by."""
    if source_id == "stock":
        stock = evidence.get("get_stock_data") or {}
        return json.dumps({"stock_data": stock, "computed_metrics": _compute_metrics(stock)})
    if source_id == "fin":
        fin = evidence.get("get_financials") or {}
        return json.dumps(fin) + "\n" + financials_text(fin)
    if source_id == "sec":
        return json.dumps(evidence.get("get_sec_filing") or {})
    if source_id == "all":  # used for the headline: everything the brief may draw on
        ids = ["stock", "fin", "sec"] + [f"news{i}" for i in range(1, 11)]
        return "\n".join(part for part in (_source_text(sid, evidence) for sid in ids) if part)
    if source_id.startswith("news"):
        try:
            index = int(source_id[4:]) - 1
        except ValueError:
            return ""
        articles = (evidence.get("search_news") or {}).get("articles", [])
        if 0 <= index < len(articles):
            a = articles[index]
            return f"{a.get('title')}\n{a.get('published_date')}\n{a.get('snippet')}"
    return ""


# ---------- Check 2: meaning (LLM) ----------
class ClaimCheck(BaseModel):
    id: int
    verdict: Literal["supported", "unsupported", "speculative"]
    reason: str = Field(description="Max 20 words.")


class VerificationResult(BaseModel):
    checks: list[ClaimCheck]


SYSTEM_PROMPT = """You are the Verifier in a financial research pipeline.
For each numbered claim you get the SOURCE TEXT it cites. Judge the claim ONLY
against that source text, nothing else you know.

Verdicts:
- supported: the source text states the claim or directly shows it.
- unsupported: the source text does not contain the claim, or contradicts it.
- speculative: the claim adds an interpretation, motive or prediction the source
  does not state (for example "reflecting concerns", "signals confidence").
  Judgment words such as "strong", "weak", "premium", "cheap" or "concerning" also
  count as speculative, unless the source itself uses that word for it.

Return one check per claim id, with a reason of at most 20 words."""


# ---------- Check 3: quality and wording (plain Python) ----------
# A claim can be "supported" and still worthless, e.g. "Memory costs are reported."
META_PHRASES = ("is noted", "are noted", "is reported", "are reported",
                "is mentioned", "are mentioned", "is highlighted", "are highlighted",
                "is present", "are present")
# Opinion words. In the headline they are never allowed; in a claim only if its source uses them.
JUDGMENT_WORDS = ("strong", "weak", "premium", "cheap", "expensive", "impressive", "robust",
                  "solid", "attractive", "concerning", "worrying", "alarming", "stretched",
                  "elevated", "overvalued", "undervalued")
# Cause-and-effect wording: a source that lists two events does not say one caused the other.
CAUSAL_PHRASES = ("causing", "caused", "because", "due to", "driven by", "led to",
                  "leading to", "resulting in", "as a result", "triggered")
# "Q3" / "FY2025": companies' fiscal calendars differ, so periods must be given as end dates.
PERIOD_LABEL = re.compile(r"\b(?:Q[1-4]|FY\s?\d{2,4})\b", re.IGNORECASE)


def _quality_problems(claim: dict, seen: set, source_text: str) -> list:
    text = " ".join(claim["text"].lower().split()).rstrip(".")
    in_source = source_text.lower()
    headline = claim["section"] == "Headline"
    problems = []
    if not headline:
        if text in seen:
            problems.append("duplicate: this fact already appears elsewhere in the brief")
        seen.add(text)
    if not re.search(r"\d", text) and any(p in text for p in META_PHRASES):
        problems.append("uninformative: says a topic exists instead of stating the fact")
    for word in JUDGMENT_WORDS:
        if re.search(rf"\b{word}\b", text) and (headline or word not in in_source):
            problems.append(f"opinion word '{word}' is not stated by the source")
            break
    for phrase in CAUSAL_PHRASES:
        if re.search(rf"\b{phrase}\b", text) and (headline or phrase not in in_source):
            problems.append(f"cause-and-effect wording ('{phrase}') is not stated by the source")
            break
    if PERIOD_LABEL.search(claim["text"]):
        problems.append("name the period by its end date (for example 'the quarter ended "
                        "2026-06-27'), not Q3 or FY2025")
    if re.search(r"\bnews\d+\b", claim["text"], re.IGNORECASE):
        problems.append("do not write source ids like 'news3' in the claim; state the fact itself")
    return problems


def _safe_headline(evidence: dict, ticker: str) -> str:
    """A headline built from tool data only, used if the Writer's headline fails verification."""
    stock = evidence.get("get_stock_data") or {}
    metrics = _compute_metrics(stock)
    name = stock.get("company_name") or ticker
    price, high = stock.get("current_price"), stock.get("fifty_two_week_high")
    if price and high and "percent_below_52w_high" in metrics:
        return (f"{name} trades at ${price:,.2f}, {metrics['percent_below_52w_high']}% "
                f"below its 52-week high of ${high:,.2f}.")
    return "No verified headline is available."


def _verification_markdown(claims: list, llm_error: str, history: list, removed: bool,
                           shown_pass: int) -> str:
    verified = sum(c["status"] == "verified" for c in claims)
    lines = [f"Checked {len(claims)} claims against their cited sources: "
             f"{verified} verified, {len(claims) - verified} flagged."]
    if len(history) > 1:
        steps = ", ".join(f"pass {i}: {h['flagged']} of {h['total']} flagged"
                          for i, h in enumerate(history, start=1))
        lines.append(f"The draft was rewritten after verification ({steps}).")
        if shown_pass != len(history):
            lines.append(f"The best draft (pass {shown_pass}) is shown, because the last "
                         "rewrite was worse.")
    if llm_error:
        lines.append(f"Note: the verifier model was unavailable ({llm_error}); only number checks "
                     "ran, so nothing was rewritten or removed.")
    if removed:
        lines.append("Claims that still failed were removed from the brief above and are "
                     "listed below for transparency.")
    lines += ["", "| # | Type | Claim | Source | Result |", "|---|---|---|---|---|"]
    for c in claims:
        text = c["text"].replace("|", "/")
        text = text if len(text) <= 70 else text[:67] + "..."
        result = "verified" if c["status"] == "verified" else f"FLAGGED - {c['note']}".replace("|", "/")
        lines.append(f"| {c['id']} | {c['section']} | {text} | {c['source']} | {result} |")
    return "\n".join(lines)


def _drop_flagged(data: dict, claims: list, evidence: dict, ticker: str) -> dict:
    """Keep only what passed verification (a flagged headline is replaced by a data-built one)."""
    bad = {c["id"] for c in claims if c["status"] == "FLAGGED"}
    n_thesis = len(data["thesis_points"])
    kept = dict(data)
    kept["thesis_points"] = [c for i, c in enumerate(data["thesis_points"]) if (i + 2) not in bad]
    kept["risks"] = [c for j, c in enumerate(data["risks"]) if (n_thesis + j + 2) not in bad]
    if 1 in bad:
        kept["headline"] = _safe_headline(evidence, ticker)
    return kept


async def verifier_node(state: FinSageState) -> dict:
    evidence = state.get("evidence", {})
    sources = state.get("sources", {})
    data = state["report_data"]
    ticker = state["ticker"]

    if not data["thesis_points"] and not data["risks"]:  # nothing to check (e.g. all tools failed)
        note = "No claims to verify."
        return {"verification": {"claims": [], "verified": 0, "flagged": 0, "markdown": note},
                "report": render_report(ticker, InvestmentReport(**data), evidence, sources, note),
                "feedback": ""}

    # Every claim gets an id: 1 = headline, then thesis points, then risks.
    claims = [{"id": 1, "section": "Headline", "text": data["headline"], "source": "all"}]
    for section, items in (("Thesis", data["thesis_points"]), ("Risk", data["risks"])):
        for c in items:
            claims.append({"id": len(claims) + 1, "section": section,
                           "text": c["text"], "source": c["source"]})

    # Check 1: numbers, in plain Python
    texts = {}
    for c in claims:
        texts[c["id"]] = _source_text(c["source"], evidence)
        values = _source_values(texts[c["id"]])
        c["missing_numbers"] = [raw for raw, v, d in _claim_numbers(c["text"])
                                if not _found(v, d, values)]

    # Check 2: meaning, by the Verifier model (the run still finishes if it is down)
    verdicts, llm_error = {}, ""
    try:
        blocks = [
            f"[{c['id']}] CLAIM: {c['text']}\n    SOURCE TEXT ({c['source']}): "
            f"{texts[c['id']][: 20000 if c['source'] == 'all' else 4000] or '(no such source)'}"
            for c in claims
        ]

        async def judge(llm):
            return await structured(llm, VerificationResult).ainvoke(
                [("system", SYSTEM_PROMPT), ("user", "\n\n".join(blocks))]
            )

        result = await with_fallback("verifier", judge)
        verdicts = {check.id: check for check in result.checks}
    except Exception as e:  # noqa: BLE001
        llm_error = str(e)[:100]

    # Merge all checks
    seen = set()
    for c in claims:
        problems = []
        check = verdicts.get(c["id"])
        if check is None:
            problems.append("not checked by the verifier model")
        elif check.verdict != "supported":
            problems.append(f"{check.verdict} ({check.reason})")
        if c["missing_numbers"]:
            problems.append("number not found in source: " + ", ".join(c["missing_numbers"]))
        problems += _quality_problems(c, seen, texts[c["id"]])
        c["status"] = "FLAGGED" if problems else "verified"
        c["note"] = "; ".join(problems)

    flagged = [c for c in claims if c["status"] == "FLAGGED"]
    history = list(state.get("verification_history", [])) + [
        {"total": len(claims), "flagged": len(flagged),
         "reasons": [f"{c['section']}: {c['note']}" for c in flagged]}]

    # Remember the best draft so far: a rewrite can fix some claims and break others.
    this_draft = {"flagged": len(flagged), "pass": len(history), "data": data, "claims": claims}
    best = state.get("best_draft")
    if best is None or this_draft["flagged"] < best["flagged"]:
        best = this_draft

    can_judge = not llm_error
    retry = can_judge and bool(flagged) and state.get("revisions", 0) < MAX_REVISIONS

    # While rewriting we show the current draft; at the end we show the best one.
    shown = this_draft if (retry or not can_judge) else best
    shown_flagged = [c for c in shown["claims"] if c["status"] == "FLAGGED"]
    finalize = can_judge and not retry and bool(shown_flagged)  # still failing after the last rewrite

    final_data = _drop_flagged(shown["data"], shown["claims"], evidence, ticker) if finalize \
        else dict(shown["data"])

    feedback = ""
    if retry:
        feedback = "\n".join(
            f"- {c['section']}: \"{c['text']}\" (cited: {c['source']}) -> {c['note']}"
            for c in flagged)

    markdown = _verification_markdown(shown["claims"], llm_error, history, finalize, shown["pass"])
    verification = {"claims": shown["claims"],
                    "verified": len(shown["claims"]) - len(shown_flagged),
                    "flagged": len(shown_flagged), "markdown": markdown}
    return {
        "verification": verification,
        "report": render_report(ticker, InvestmentReport(**final_data), evidence, sources, markdown),
        "report_data": final_data,
        "feedback": feedback,
        "verification_history": history,
        "best_draft": best,
    }