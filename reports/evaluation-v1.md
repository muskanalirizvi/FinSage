# FinSage evaluation

Run on 2026-10-07 19:02 UTC: 13 tickers, one after another, with the free-tier models and tools.

| Ticker | Result | Secs | Passes | 1st flagged | Kept | Risks | Dropped | Headline fixed | SEC table | News | Backup | Failed tools |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | ok | 28 | 3 | 1/7 | 6 | 2 | 1 | yes | yes | 5 | 0 | - |
| MSFT | ok | 24 | 3 | 3/7 | 4 | 2 | 3 | yes | yes | 5 | 0 | - |
| NVDA | ok | 19 | 2 | 2/6 | 5 | 1 | 0 | no | yes | 1 | 0 | - |
| TSLA | ok | 38 | 3 | 2/5 | 3 | 0 | 2 | yes | yes | 5 | 0 | - |
| AMZN | ok | 39 | 3 | 4/7 | 3 | 1 | 3 | no | yes | 5 | 0 | - |
| GOOGL | ok | 37 | 3 | 3/8 | 7 | 3 | 1 | yes | yes | 5 | 0 | - |
| META | ok | 22 | 2 | 1/7 | 8 | 4 | 0 | no | yes | 5 | 0 | - |
| JPM | ok | 24 | 2 | 1/6 | 5 | 1 | 0 | no | yes | 5 | 0 | - |
| KO | ok | 41 | 3 | 1/5 | 4 | 0 | 0 | no | yes | 3 | 0 | - |
| XOM | ok | 20 | 2 | 3/7 | 6 | 2 | 0 | no | no | 5 | 0 | get_financials, get_sec_filing |
| JNJ | ok | 36 | 3 | 2/7 | 5 | 1 | 2 | yes | yes | 5 | 0 | - |
| WMT | ok | 27 | 2 | 2/8 | 13 | 3 | 0 | no | yes | 5 | 0 | - |
| ZZZZ | ok | 46 | 0 | 0/0 | 0 | 0 | 0 | no | no | 1 | 0 | get_stock_data, get_financials, get_sec_filing |

## Summary

- Runs completed: 13 of 13
- Time per run: median 28s, slowest 46s
- Claims flagged on the first draft: 25 of 80 (31%)
- Runs that needed at least one rewrite: 12 of 13
- Claims dropped from the final briefs (still failing after rewrites): 12
- Briefs with no risks listed: 3 of 13
- Briefs where the headline had to be replaced by a data-built one: 5 of 13
- Briefs with the SEC financials table: 11 of 13
- Runs where a backup model had to step in: 0 of 13
- Every claim shown in a brief passed verification; claims that did not were removed.

## Why claims were flagged on the first draft

| Reason | Claims |
|---|---|
| judged speculative by the verifier model | 14 |
| opinion word | 9 |
| number not found in its source | 5 |
| Q3/FY label instead of end date | 4 |
| judged unsupported by the verifier model | 2 |
| cause-and-effect wording | 1 |
| vague claim | 1 |
