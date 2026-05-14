"""
fetch_price_history.py

Fetches 12-month daily close price history for all tickers in tickers.json
using the Yahoo Finance v8/finance/chart endpoint (same crumb/session approach
as fetch_prices.py). Merges new data into prices_history.json — already-known
dates are never overwritten, only new trading days are appended.

No API key required. Runs in GitHub Actions.

Output format — prices_history.json:
{
  "updated_at": "2026-05-14 09:00:00",
  "updated_at_tz": "EEST (UTC+3)",
  "tickers": {
    "AAPL": {
      "currency": "USD",
      "history": [
        {"date": "2025-05-14", "open": 189.12, "high": 191.50, "low": 188.00, "close": 190.25, "volume": 55000000},
        ...
      ]
    },
    ...
  },
  "errors": [
    {"ticker": "XYZ", "error": "not returned by Yahoo"}
  ]
}

History arrays are sorted ascending by date. Dates are YYYY-MM-DD strings (market local date).
"""

import json
import os
import requests
from datetime import datetime, timezone, timedelta

TICKERS_FILE  = "tickers.json"
HISTORY_FILE  = "prices_history.json"
TIMEOUT_SEC   = 15
HISTORY_DAYS  = 365   # fetch last 12 months on every run; merge logic deduplicates

ROMANIAN_TZ   = timezone(timedelta(hours = 3))   # EEST (summer); change to 2 for EET winter

HEADERS = {
    "User-Agent"      : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept"          : "application/json, text/plain, */*",
    "Accept-Language" : "en-US,en;q=0.9",
    "Referer"         : "https://finance.yahoo.com/",
    "Origin"          : "https://finance.yahoo.com",
}


# ---------------------------------------------------------------------------
# Yahoo Finance session + crumb (identical pattern to fetch_prices.py)
# ---------------------------------------------------------------------------

def get_crumb_and_session():
    """Obtain a Yahoo Finance crumb token and session cookies.
    Yahoo requires a crumb (CSRF-like token) for chart API calls.
    Flow: hit the main page first to get cookies, then fetch crumb."""
    session = requests.Session()
    session.headers.update(HEADERS)

    # Step 1: hit Yahoo Finance to get session cookies
    session.get("https://finance.yahoo.com/quote/AAPL/", timeout = TIMEOUT_SEC)

    # Step 2: fetch crumb using the session cookies obtained above
    crumb_resp = session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout = TIMEOUT_SEC)
    crumb_resp.raise_for_status()
    crumb = crumb_resp.text.strip()

    if not crumb or "<" in crumb:   # HTML response means we got an error/redirect page
        raise ValueError(f"Invalid crumb received: {crumb[:80]}")

    return session, crumb
# end def get_crumb_and_session


# ---------------------------------------------------------------------------
# History fetch — one request per ticker (chart endpoint has no batch mode)
# ---------------------------------------------------------------------------

def fetch_ticker_history(ticker, session, crumb):
    """
    Fetch daily OHLCV data for the last HISTORY_DAYS days via Yahoo v8/finance/chart.
    Returns a list of dicts: [{"date": "YYYY-MM-DD", "open": ..., "high": ...,
                                "low": ..., "close": ..., "volume": ...}, ...]
    Sorted ascending by date. Only includes days where close price is not None.
    """
    now_ts    = int(datetime.now(tz = timezone.utc).timestamp())
    start_ts  = now_ts - HISTORY_DAYS * 86400

    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?period1={start_ts}&period2={now_ts}&interval=1d&events=history&crumb={crumb}"
    )
    resp = session.get(url, timeout = TIMEOUT_SEC)
    resp.raise_for_status()
    data = resp.json()

    result    = data["chart"]["result"]
    if not result:
        raise ValueError("Empty chart result from Yahoo")

    chart     = result[0]
    meta      = chart.get("meta", {})
    currency  = meta.get("currency", "USD")
    timestamps_lst = chart.get("timestamp", [])
    indicators     = chart.get("indicators", {})
    quote_lst      = indicators.get("quote", [{}])
    quote          = quote_lst[0] if quote_lst else {}

    opens_lst   = quote.get("open",   [])
    highs_lst   = quote.get("high",   [])
    lows_lst    = quote.get("low",    [])
    closes_lst  = quote.get("close",  [])
    volumes_lst = quote.get("volume", [])

    history_lst = []
    for i, ts in enumerate(timestamps_lst):
        close = closes_lst[i] if i < len(closes_lst) else None
        if close is None:
            continue   # skip days with no data (e.g. partial last day)

        date_str = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
        open_v   = opens_lst[i]   if i < len(opens_lst)   else None
        high_v   = highs_lst[i]   if i < len(highs_lst)   else None
        low_v    = lows_lst[i]    if i < len(lows_lst)    else None
        vol_v    = volumes_lst[i] if i < len(volumes_lst) else None

        history_lst.append({
            "date"   : date_str,
            "open"   : round(open_v,  4) if open_v  is not None else None,
            "high"   : round(high_v,  4) if high_v  is not None else None,
            "low"    : round(low_v,   4) if low_v   is not None else None,
            "close"  : round(close,   4),
            "volume" : int(vol_v)        if vol_v   is not None else None,
        })

    history_lst.sort(key = lambda d: d["date"])
    return currency, history_lst
# end def fetch_ticker_history


# ---------------------------------------------------------------------------
# Merge — new data is appended; existing dates are never overwritten
# ---------------------------------------------------------------------------

def merge_history(existing_lst, new_lst):
    """
    Merge new_lst into existing_lst. Existing dates win (never overwritten).
    Returns a new list sorted ascending by date.
    """
    existing_dct = {entry["date"]: entry for entry in existing_lst}
    for entry in new_lst:
        if entry["date"] not in existing_dct:
            existing_dct[entry["date"]] = entry
    merged_lst = sorted(existing_dct.values(), key = lambda d: d["date"])
    return merged_lst
# end def merge_history


# ---------------------------------------------------------------------------
# Trim to rolling 12-month window so the file doesn't grow indefinitely
# ---------------------------------------------------------------------------

def trim_to_12_months(history_lst):
    """Remove entries older than 366 days from the most recent date in the list."""
    if not history_lst:
        return history_lst
    latest_date = datetime.strptime(history_lst[-1]["date"], "%Y-%m-%d")
    cutoff      = latest_date - timedelta(days = 366)
    return [e for e in history_lst if datetime.strptime(e["date"], "%Y-%m-%d") >= cutoff]
# end def trim_to_12_months


# ---------------------------------------------------------------------------
# Load / save prices_history.json
# ---------------------------------------------------------------------------

def load_existing_history():
    """Load prices_history.json if it exists, return empty skeleton otherwise."""
    if os.path.isfile(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding = "utf-8") as f:
            return json.load(f)
    return {"updated_at": None, "updated_at_tz": "EEST (UTC+3)", "tickers": {}, "errors": []}
# end def load_existing_history


def save_history(data_dct):
    with open(HISTORY_FILE, "w", encoding = "utf-8") as f:
        json.dump(data_dct, f, indent = 2)
# end def save_history


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open(TICKERS_FILE, "r", encoding = "utf-8") as f:
        tickers_lst = json.load(f)

    print(f"Fetching 12-month daily history for {len(tickers_lst)} tickers...")

    existing_dct = load_existing_history()
    tickers_dct  = existing_dct.get("tickers", {})   # preserve existing data
    errors_lst   = []

    try:
        print("Obtaining Yahoo Finance session and crumb...")
        session, crumb = get_crumb_and_session()
        print(f"Crumb obtained: {crumb[:10]}...")
    except Exception as e:
        print(f"FATAL: could not obtain crumb — {e}")
        return   # abort without touching the file if we can't authenticate

    for ticker in tickers_lst:
        try:
            currency, new_history_lst = fetch_ticker_history(ticker, session, crumb)

            existing_entry  = tickers_dct.get(ticker, {})
            existing_hist   = existing_entry.get("history", [])
            merged_lst      = merge_history(existing_hist, new_history_lst)
            trimmed_lst     = trim_to_12_months(merged_lst)

            tickers_dct[ticker] = {"currency": currency, "history": trimmed_lst}

            added    = len(trimmed_lst) - len(existing_hist)
            last_dt  = trimmed_lst[-1]["date"] if trimmed_lst else "—"
            last_px  = trimmed_lst[-1]["close"] if trimmed_lst else "—"
            print(f"  {ticker:8s}  {len(trimmed_lst):3d} days  last={last_dt}  close={last_px:>10}  +{max(added, 0)} new")

        except Exception as e:
            print(f"  {ticker:8s}  ERROR: {e}")
            errors_lst.append({"ticker": ticker, "error": str(e)})

    now_ro     = datetime.now(tz = ROMANIAN_TZ)
    output_dct = {
        "updated_at"    : now_ro.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at_tz" : "EEST (UTC+3)",
        "tickers"       : tickers_dct,
        "errors"        : errors_lst,
    }

    save_history(output_dct)
    print(f"\nSaved history for {len(tickers_dct)} tickers to {HISTORY_FILE}  ({now_ro.strftime('%Y-%m-%d %H:%M:%S')} EEST)")
    if errors_lst:
        print(f"Errors ({len(errors_lst)}): {[e['ticker'] for e in errors_lst]}")
# end def main


if __name__ == "__main__":
    main()
