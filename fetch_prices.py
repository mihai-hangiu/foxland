"""
fetch_prices.py
Reads tickers from tickers.json, fetches current prices from Yahoo Finance
(including pre/after market when available), and writes prices.json.
No API key required. Runs in GitHub Actions.
"""

import json
import time
import requests
from datetime import datetime, timezone, timedelta

TICKERS_FILE = "tickers.json"
PRICES_FILE  = "prices.json"
DELAY_SEC    = 0.5        # polite delay between requests to avoid rate limiting
TIMEOUT_SEC  = 10

ROMANIAN_TZ  = timezone(timedelta(hours = 3))   # EEST (summer); change to 2 for EET winter

HEADERS = {
    "User-Agent"      : "Mozilla/5.0 (compatible; price-fetcher/1.0)",
    "Accept"          : "application/json",
    "Accept-Language" : "en-US,en;q=0.9",
}

def fetch_yahoo_quote(ticker):
    """Fetch quote data for a single ticker from Yahoo Finance v8 chart endpoint."""
    url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
    resp = requests.get(url, headers = HEADERS, timeout = TIMEOUT_SEC)
    resp.raise_for_status()
    data = resp.json()

    meta = data["chart"]["result"][0]["meta"]

    regular_price    = meta.get("regularMarketPrice")
    prev_close       = meta.get("chartPreviousClose") or meta.get("previousClose")
    pre_price        = meta.get("preMarketPrice")
    post_price       = meta.get("postMarketPrice")
    market_state     = meta.get("marketState", "UNKNOWN")   # PRE, REGULAR, POST, CLOSED
    currency         = meta.get("currency", "USD")

    # Compute change vs previous close — use the most relevant current price
    if market_state == "PRE" and pre_price:
        current_price = pre_price
    elif market_state in ("POST", "POSTPOST") and post_price:
        current_price = post_price
    else:
        current_price = regular_price

    change     = round(current_price - prev_close, 4) if (current_price and prev_close) else None
    change_pct = round((change / prev_close) * 100, 4) if (change and prev_close)       else None

    return {
        "ticker"       : ticker,
        "market_state" : market_state,
        "currency"     : currency,
        "regular"      : round(regular_price, 4) if regular_price else None,
        "pre"          : round(pre_price,     4) if pre_price     else None,
        "post"         : round(post_price,    4) if post_price    else None,
        "prev_close"   : round(prev_close,    4) if prev_close    else None,
        "change"       : change,
        "change_pct"   : change_pct,
    }
# end def fetch_yahoo_quote

def main():
    # Load tickers
    with open(TICKERS_FILE, "r") as f:
        tickers_lst = json.load(f)

    print(f"Fetching prices for {len(tickers_lst)} tickers...")

    prices_lst  = []
    errors_lst  = []

    for ticker in tickers_lst:
        try:
            quote = fetch_yahoo_quote(ticker)
            prices_lst.append(quote)
            state = quote["market_state"]
            price = quote["pre"] or quote["regular"] or quote["post"]
            pct   = quote["change_pct"]
            print(f"  {ticker:8s}  {state:10s}  {price:>10.4f}  {f'{pct:+.2f}%' if pct else 'N/A':>8s}")
        except Exception as e:
            print(f"  {ticker:8s}  ERROR: {e}")
            errors_lst.append({"ticker": ticker, "error": str(e)})

        time.sleep(DELAY_SEC)

    # Timestamp in Romanian time
    now_ro = datetime.now(tz = ROMANIAN_TZ)

    output_dct = {
        "fetched_at"    : now_ro.strftime("%Y-%m-%d %H:%M:%S"),
        "fetched_at_tz" : "EEST (UTC+3)",
        "prices"        : prices_lst,
        "errors"        : errors_lst,
    }

    with open(PRICES_FILE, "w") as f:
        json.dump(output_dct, f, indent = 2)

    print(f"\nSaved {len(prices_lst)} prices to {PRICES_FILE}  ({now_ro.strftime('%Y-%m-%d %H:%M:%S')} EEST)")
# end def main

if __name__ == "__main__":
    main()
