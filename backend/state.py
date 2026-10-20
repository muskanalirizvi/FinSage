from typing import TypedDict


class FinSageState(TypedDict, total=False):
    ticker: str
    evidence: dict               # data straight from the tools (ground truth for the Verifier)
    research_notes: str          # Researcher's short summary
    analysis: str                # Analyst's cross-check
    report: str                  # final Markdown research brief
    report_data: dict            # the brief as structured claims (for the Verifier)
    sources: dict                # source id -> label, e.g. "news1" -> article title
    verification: dict           # Verifier's per-claim results
    feedback: str                # what the Verifier wants the Writer to fix (empty = nothing)
    revisions: int               # how many times the Writer has rewritten the draft
    verification_history: list   # claims flagged on each verification pass
    best_draft: dict             # the draft with the fewest flagged claims so far