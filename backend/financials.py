"""Turns the get_financials tool output into readable text and table rows (no LLM involved)."""


def _usd_short(x) -> str:
    if x is None:
        return "n/a"
    for divisor, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(x) >= divisor:
            return f"${x / divisor:,.2f}{suffix}"
    return f"${x:,.0f}"


def _cell(block: dict, key: str, per_share: bool = False) -> str:
    value = block.get(key)
    if value is None:
        return "n/a"
    shown = f"${value:,.2f}" if per_share else _usd_short(value)
    growth = block.get(f"{key}_growth_percent")
    return f"{shown} ({growth:+.1f}%)" if growth is not None else shown


def financial_rows(fin) -> list:
    """One row per period: (label, revenue, operating income, net income, diluted EPS)."""
    rows = []
    if not isinstance(fin, dict) or "error" in fin:
        return rows
    for key, label in (("annual", "Fiscal year ended"), ("latest_quarter", "Quarter ended")):
        block = fin.get(key)
        if block:
            rows.append((
                f"{label} {block['period_end']} ({block.get('form')})",
                _cell(block, "revenue"),
                _cell(block, "operating_income"),
                _cell(block, "net_income"),
                _cell(block, "eps_diluted", per_share=True),
            ))
    return rows


def financials_text(fin) -> str:
    """The same numbers as plain lines, for the LLM prompts."""
    return "\n".join(
        f"{r[0]}: revenue {r[1]}; operating income {r[2]}; net income {r[3]}; diluted EPS {r[4]}"
        for r in financial_rows(fin)
    )