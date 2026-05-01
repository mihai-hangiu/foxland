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
    "User-Agent"      : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept"          : "application/json, text/plain, */*",
    "Accept-Language" : "en-US,en;q=0.9",
    "Referer"         : "https://finance.yahoo.com/",
    "Origin"          : "https://finance.yahoo.com",
}

def get_crumb_and_session():
    """Obtain a Yahoo Finance crumb token and session cookies.
    Yahoo requires a crumb (CSRF-like token) since late 2023 for quote API calls.
    Flow: hit the consent/cookie endpoint first, then fetch the crumb."""
    session = requests.Session()
    session.headers.update(HEADERS)

    # Step 1: hit Yahoo Finance to get cookies (including session cookie)
    consent_url = "https://finance.yahoo.com/quote/AAPL/"
    session.get(consent_url, timeout = TIMEOUT_SEC)

    # Step 2: fetch crumb using the session cookies obtained above
    crumb_url  = "https://query1.finance.yahoo.com/v1/test/getcrumb"
    crumb_resp = session.get(crumb_url, timeout = TIMEOUT_SEC)
    crumb_resp.raise_for_status()
    crumb = crumb_resp.text.strip()

    if not crumb or "<" in crumb:   # sanity check — HTML means we got a redirect/error page
        raise ValueError(f"Invalid crumb received: {crumb[:80]}")

    return session, crumb
# end def get_crumb_and_session

def parse_quote(q):
    """Parse a single quote dict from Yahoo Finance v8 response into our output format."""
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

def fetch_all_quotes(tickers_lst, session, crumb):
    """Fetch all tickers in a single batch request to Yahoo Finance v8 quote endpoint."""
    symbols = ",".join(tickers_lst)
    fields  = "regularMarketPrice,regularMarketPreviousClose,preMarketPrice,postMarketPrice,marketState,currency"
    url     = f"https://query2.finance.yahoo.com/v8/finance/quote?symbols={symbols}&fields={fields}&crumb={crumb}"
    resp    = session.get(url, timeout = TIMEOUT_SEC)
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
        print("Obtaining Yahoo Finance session and crumb...")
        session, crumb = get_crumb_and_session()
        print(f"Crumb obtained: {crumb[:10]}...")

        quotes_lst   = fetch_all_quotes(tickers_lst, session, crumb)
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
