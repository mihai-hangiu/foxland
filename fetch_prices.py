"""
fetch_prices.py
Reads tickers from tickers.json, fetches current prices from Yahoo Finance
(including pre/after market when available), and writes prices.json.
No API key required. Runs in GitHub Actions.
"""

import json
import requests
from datetime import datetime, timezone, timedelta

TICKERS_FILE = "tickers.json"
PRICES_FILE  = "prices.json"
TIMEOUT_SEC  = 10

ROMANIAN_TZ  = timezone(timedelta(hours = 3))   # EEST (summer); change to 2 for EET winter

HEADERS = {
    "User-Agent"      : "Mozilla/5.0 (compatible; price-fetcher/1.0)",
    "Accept"          : "application/json",
    "Accept-Language" : "en-US,en;q=0.9",
}

def parse_quote(q):
    """Parse a single quote dict from Yahoo Finance v7 response into our output format."""
    ticker        = q.get("symbol", "")
    regular_price = q.get("regularMarketPrice")
    prev_close    = q.get("regularMarketPreviousClose")
    pre_price     = q.get("preMarketPrice")
    post_price    = q.get("postMarketPrice")
    market_state  = q.get("marketState", "UNKNOWN")   # PRE, REGULAR, POST, POSTPOST, CLOSED
    currency      = q.get("currency", "USD")

    # Use the most relevant price for change calculation
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
# end def parse_quote

def fetch_all_quotes(tickers_lst):
    """Fetch all tickers in a single batch request to Yahoo Finance v7 quote endpoint."""
    symbols = ",".join(tickers_lst)
    fields  = "regularMarketPrice,regularMarketPreviousClose,preMarketPrice,postMarketPrice,marketState,currency"
    url     = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols}&fields={fields}"
    resp    = requests.get(url, headers = HEADERS, timeout = TIMEOUT_SEC)
    resp.raise_for_status()
    data    = resp.json()
    return data["quoteResponse"]["result"]   # list of quote dicts
# end def fetch_all_quotes

def main():
    # Load tickers
    with open(TICKERS_FILE, "r") as f:
        tickers_lst = json.load(f)

    print(f"Fetching prices for {len(tickers_lst)} tickers in a single batch request...")

    prices_lst = []
    errors_lst = []

    try:
        quotes_lst    = fetch_all_quotes(tickers_lst)
        returned_dct  = {q["symbol"]: q for q in quotes_lst}   # index by symbol for easy lookup

        for ticker in tickers_lst:
            if ticker not in returned_dct:
                print(f"  {ticker:8s}  NOT IN RESPONSE")
                errors_lst.append({"ticker": ticker, "error": "not returned by Yahoo"})
                continue

            try:
                quote = parse_quote(returned_dct[ticker])
                prices_lst.append(quote)
                state = quote["market_state"]
                price = quote["pre"] or quote["regular"] or quote["post"]
                pct   = quote["change_pct"]
                print(f"  {ticker:8s}  {state:10s}  {price:>10.4f}  {f'{pct:+.2f}%' if pct else 'N/A':>8s}")
            except Exception as e:
                print(f"  {ticker:8s}  PARSE ERROR: {e}")
                errors_lst.append({"ticker": ticker, "error": str(e)})

    except Exception as e:
        print(f"Batch request failed: {e}")
        # Mark all tickers as errors if the whole request fails
        errors_lst = [{"ticker": t, "error": str(e)} for t in tickers_lst]

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
