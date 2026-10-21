# FinSage evaluation

Run on 2026-10-21 04:34 UTC: 13 tickers, one after another, with the free-tier models and tools.

| Ticker | Result | Secs | Passes | 1st flagged | Kept | Risks | Dropped | Headline fixed | SEC table | News | Backup | Failed tools |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | ok | 32 | 2 | 2/9 | 7 | 3 | 0 | no | yes | 6 | 0 | - |
| MSFT | ok | 30 | 2 | 2/7 | 8 | 2 | 0 | no | yes | 6 | 0 | - |
| NVDA | ok | 28 | 3 | 2/7 | 5 | 1 | 1 | no | yes | 6 | 0 | - |
| TSLA | ok | 27 | 2 | 2/7 | 7 | 3 | 0 | no | yes | 6 | 0 | - |
| AMZN | ok | 31 | 3 | 1/7 | 5 | 2 | 1 | no | yes | 6 | 0 | - |
| GOOGL | ok | 23 | 2 | 4/8 | 4 | 0 | 0 | no | yes | 6 | 0 | - |
| META | ok | 27 | 2 | 4/8 | 8 | 4 | 0 | no | yes | 6 | 0 | - |
| JPM | ok | 24 | 1 | 0/6 | 5 | 1 | 0 | no | yes | 6 | 0 | - |
| KO | ok | 18 | 1 | 0/8 | 7 | 3 | 0 | no | yes | 6 | 0 | - |
| XOM | ok | 24 | 1 | 0/6 | 5 | 1 | 0 | no | yes | 6 | 0 | get_sec_filing |
| JNJ | ok | 23 | 1 | 0/8 | 7 | 3 | 0 | no | yes | 6 | 0 | - |
| WMT | ok | 27 | 3 | 1/6 | 5 | 1 | 0 | no | yes | 6 | 0 | - |
| ZZZZ | ok | 20 | 0 | 0/0 | 0 | 0 | 0 | no | no | 6 | 0 | get_stock_data, get_financials, get_sec_filing |

## Summary

- Runs completed: 13 of 13
- Time per run: median 27s, slowest 32s
- Claims flagged on the first draft: 18 of 87 (21%)
- Runs that needed at least one rewrite: 8 of 13
- Claims dropped from the final briefs (still failing after rewrites): 2
- Briefs with no risks listed: 2 of 13
- Briefs where the headline had to be replaced by a data-built one: 0 of 13
- Briefs with the SEC financials table: 12 of 13
- Runs where a backup model had to step in: 0 of 13
- Every claim shown in a brief passed verification; claims that did not were removed.

## Why claims were flagged on the first draft

| Reason | Claims |
|---|---|
| judged speculative by the verifier model | 16 |
| number not found in its source | 5 |
| source id written in the claim | 4 |
| Q3/FY label instead of end date | 1 |
