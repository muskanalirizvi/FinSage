"""Shows what SEC returns for a ticker, to find out why a company's data is missing.

    python -m backend.debug_sec XOM
"""

import sys
from collections import Counter

import requests

from backend.mcp_server.financial_mcp_server import FINANCIAL_METRICS, SEC_HEADERS

ticker = (sys.argv[1] if len(sys.argv) > 1 else "XOM").upper()


def get(url: str):
    response = requests.get(url, headers=SEC_HEADERS, timeout=60)
    print(f"GET ...{url.split('sec.gov')[1][:55]} -> HTTP {response.status_code}, "
          f"{len(response.content):,} bytes")
    response.raise_for_status()
    return response.json()


listing = get("https://www.sec.gov/files/company_tickers.json")
matches = [e for e in listing.values() if e["ticker"].upper() == ticker]
print("entries for this ticker in the SEC list:", matches)
if not matches:
    sys.exit()
cik = str(matches[0]["cik_str"]).zfill(10)

print("\n--- filings list ---")
sub = get(f"https://data.sec.gov/submissions/CIK{cik}.json")
print("company:", sub.get("name"), "| tickers:", sub.get("tickers"), "| industry:", sub.get("sicDescription"))
recent = sub["filings"]["recent"]
forms = Counter(recent["form"])
print(f"filings in 'recent': {len(recent['form'])}")
print("most common form types:", forms.most_common(8))
print("10-K present:", "10-K" in forms, "| 10-K405 or 10-KT:", any(f in forms for f in ("10-K405", "10-KT")),
      "| 10-Q present:", "10-Q" in forms)
print("older filing files listed:", [f["name"] for f in sub["filings"].get("files", [])][:5])
print("newest 8 forms:", list(zip(recent["form"][:8], recent["filingDate"][:8])))

print("\n--- financial data ---")
facts = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
print("entity:", facts.get("entityName"), "| taxonomies:", list(facts.get("facts", {}).keys()))
us_gaap = facts.get("facts", {}).get("us-gaap", {})
print("us-gaap tags:", len(us_gaap))
for name, (tags, unit) in FINANCIAL_METRICS.items():
    for tag in tags:
        entries = us_gaap.get(tag, {}).get("units", {}).get(unit, [])
        if entries:
            latest = sorted(entries, key=lambda e: e.get("end", ""))[-2:]
            print(f"  {name:17} {tag}: {len(entries)} entries; latest "
                  f"{[(e.get('start'), e.get('end'), e.get('form')) for e in latest]}")
        else:
            print(f"  {name:17} {tag}: none")