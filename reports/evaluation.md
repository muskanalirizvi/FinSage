# FinSage evaluation

Run on 2026-10-20 20:22 UTC: 6 tickers, one after another, with the free-tier models and tools.

| Ticker | Result | Secs | Passes | 1st flagged | Kept | Risks | Dropped | Headline fixed | SEC table | News | Backup | Failed tools |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TSLA | ok | 30 | 2 | 4/7 | 6 | 2 | 0 | no | yes | 6 | 0 | - |
| AMZN | ok | 25 | 2 | 3/8 | 5 | 2 | 0 | no | yes | 6 | 0 | - |
| META | ok | 35 | 3 | 2/7 | 5 | 1 | 1 | no | yes | 6 | 0 | - |
| JPM | ok | 27 | 2 | 1/8 | 6 | 2 | 0 | no | yes | 6 | 0 | - |
| XOM | ok | 23 | 1 | 0/6 | 5 | 1 | 0 | no | yes | 6 | 0 | get_sec_filing |
| WMT | ok | 28 | 2 | 3/8 | 4 | 0 | 0 | no | yes | 6 | 0 | - |

## Summary

- Runs completed: 6 of 6
- Time per run: median 28s, slowest 35s
- Claims flagged on the first draft: 13 of 44 (30%)
- Runs that needed at least one rewrite: 5 of 6
- Claims dropped from the final briefs (still failing after rewrites): 1
- Briefs with no risks listed: 1 of 6
- Briefs where the headline had to be replaced by a data-built one: 0 of 6
- Briefs with the SEC financials table: 6 of 6
- Runs where a backup model had to step in: 0 of 6
- Every claim shown in a brief passed verification; claims that did not were removed.

## Why claims were flagged on the first draft

| Reason | Claims |
|---|---|
| judged speculative by the verifier model | 11 |
| Q3/FY label instead of end date | 2 |
