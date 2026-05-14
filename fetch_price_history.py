"""
fetch_price_history.py

Fetches 12-month daily close price history for all tickers in tickers.json.
Uses yfinance as primary method, with a direct v7/finance/download CSV request
as fallback (no crumb required). Merges new data into prices_history.json —
existing dates are never overwritten, only new trading days are appended.

No API key required. Runs in GitHub Actions.

Output format — prices_history.json:
{
  "updated_at": "2026-05-14 09:00:00",
  "updated_at_tz": "EEST (UTC+3)",
  "tickers": {
    "AAPL": {
      "currency": "USD",
      "history": [
        {"date": "2025-05-14", "close": 190.25},
        ...
      ]
    }
  },
  "errors": [{"ticker": "XYZ", "error": "..."}]
}

History arrays are sorted ascending by date (YYYY-MM-DD strings).
"""

import csv
import io
import json
import os
import time
import requests
import yfinance as yf
from datetime import datetime, timezone, timedelta

TICKERS_FILE  = "tickers.json"
HISTORY_FILE  = "prices_history.json"
HISTORY_DAYS  = 365
TIMEOUT_SEC   = 20
ROMANIAN_TZ   = timezone(timedelta(hours = 3))   # EEST (summer); change to 2 for EET winter

HEADERS = {
    "User-Agent"      : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept"          : "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language" : "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Method 1: yfinance
# ---------------------------------------------------------------------------

def fetch_via_yfinance(ticker):
    """
    Fetch daily history via yfinance. Returns (currency, history_lst) or raises.
    history_lst: [{"date": "YYYY-MM-DD", "close": float}, ...]
    """
    tk   = yf.Ticker(ticker)
    hist = tk.history(period = "1y", interval = "1d", auto_adjust = True)

    if hist.empty:
        raise ValueError("yfinance returned empty DataFrame")

    currency    = "USD"   # yfinance doesn't always expose currency easily; default USD
    history_lst = []
    for ts, row in hist.iterrows():
        date_str = ts.strftime("%Y-%m-%d")
        close    = row.get("Close")
        if close is None or (hasattr(close, "__float__") is False):
            continue
        history_lst.append({"date": date_str, "close": round(float(close), 4)})

    history_lst.sort(key = lambda d: d["date"])
    return currency, history_lst
# end def fetch_via_yfinance


# ---------------------------------------------------------------------------
# Method 2: v7/finance/download CSV (no crumb required)
# ---------------------------------------------------------------------------

def fetch_via_v7_csv(ticker):
    """
    Fetch daily history via Yahoo Finance v7/finance/download endpoint (CSV format).
    This endpoint does not require a crumb token. Returns (currency, history_lst) or raises.
    """
    now_ts   = int(datetime.now(tz = timezone.utc).timestamp())
    start_ts = now_ts - HISTORY_DAYS * 86400

    url  = (f"https://query1.finance.yahoo.com/v7/finance/download/{ticker}"
            f"?period1={start_ts}&period2={now_ts}&interval=1d&events=history")
    resp = requests.get(url, headers = HEADERS, timeout = TIMEOUT_SEC)
    resp.raise_for_status()

    # Response is CSV: Date,Open,High,Low,Close,Adj Close,Volume
    reader      = csv.DictReader(io.StringIO(resp.text))
    history_lst = []
    for row in reader:
        date_str = row.get("Date", "").strip()
        close_s  = row.get("Close", "").strip()
        if not date_str or not close_s or close_s.lower() == "null":
            continue
        try:
            history_lst.append({"date": date_str, "close": round(float(close_s), 4)})
        except ValueError:
            continue

    if not history_lst:
        raise ValueError("v7 CSV returned no rows")

    history_lst.sort(key = lambda d: d["date"])
    return "USD", history_lst
# end def fetch_via_v7_csv


# ---------------------------------------------------------------------------
# Method 3: v8/finance/chart with manual cookie (no crumb, just cookie)
# ---------------------------------------------------------------------------

def fetch_via_v8_chart(ticker, session):
    """
    Fetch via v8/finance/chart using only session cookies (no crumb).
    Some Yahoo endpoints accept requests with a valid cookie but without crumb
    when the crumb field is omitted entirely. Returns (currency, history_lst) or raises.
    """
    now_ts   = int(datetime.now(tz = timezone.utc).timestamp())
    start_ts = now_ts - HISTORY_DAYS * 86400

    url  = (f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
            f"?period1={start_ts}&period2={now_ts}&interval=1d&events=history")
    resp = session.get(url, timeout = TIMEOUT_SEC)
    resp.raise_for_status()
    data = resp.json()

    result = data.get("chart", {}).get("result")
    if not result:
        raise ValueError("v8 chart returned empty result")

    chart          = result[0]
    currency       = chart.get("meta", {}).get("currency", "USD")
    timestamps_lst = chart.get("timestamp", [])
    closes_lst     = chart.get("indicators", {}).get("quote", [{}])[0].get("close", [])

    history_lst = []
    for i, ts in enumerate(timestamps_lst):
        close = closes_lst[i] if i < len(closes_lst) else None
        if close is None:
            continue
        history_lst.append({"date": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"), "close": round(close, 4)})

    if not history_lst:
        raise ValueError("v8 chart returned no close prices")

    history_lst.sort(key = lambda d: d["date"])
    return currency, history_lst
# end def fetch_via_v8_chart


# ---------------------------------------------------------------------------
# Fetch with fallback chain
# ---------------------------------------------------------------------------

def fetch_ticker_history(ticker, session):
    """
    Try yfinance → v7 CSV → v8 chart (no crumb) in order.
    Returns (currency, history_lst) or raises if all methods fail.
    """
    errors_lst = []

    for method_name, method_fn in [
        ("yfinance",  lambda: fetch_via_yfinance(ticker)),
        ("v7-csv",    lambda: fetch_via_v7_csv(ticker)),
        ("v8-nocrum", lambda: fetch_via_v8_chart(ticker, session)),
    ]:
        try:
            currency, history_lst = method_fn()
            if history_lst:
                print(f"    [{method_name}] OK  {len(history_lst)} days")
                return currency, history_lst
            errors_lst.append(f"{method_name}: empty result")
        except Exception as e:
            errors_lst.append(f"{method_name}: {e}")

    raise ValueError(" | ".join(errors_lst))
# end def fetch_ticker_history


# ---------------------------------------------------------------------------
# Merge + trim
# ---------------------------------------------------------------------------

def merge_history(existing_lst, new_lst):
    """Merge new entries into existing; existing dates are never overwritten. Returns sorted list."""
    existing_dct = {entry["date"]: entry for entry in existing_lst}
    for entry in new_lst:
        if entry["date"] not in existing_dct:
            existing_dct[entry["date"]] = entry
    return sorted(existing_dct.values(), key = lambda d: d["date"])
# end def merge_history


def trim_to_12_months(history_lst):
    """Remove entries older than 366 days relative to the most recent date in the list."""
    if not history_lst:
        return history_lst
    latest  = datetime.strptime(history_lst[-1]["date"], "%Y-%m-%d")
    cutoff  = latest - timedelta(days = 366)
    return [e for e in history_lst if datetime.strptime(e["date"], "%Y-%m-%d") >= cutoff]
# end def trim_to_12_months


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_existing_history():
    if os.path.isfile(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding = "utf-8") as f:
            return json.load(f)
    return {"updated_at": None, "updated_at_tz": "EEST (UTC+3)", "tickers": {}, "errors": []}
# end def load_existing_history


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open(TICKERS_FILE, "r", encoding = "utf-8") as f:
        tickers_lst = json.load(f)

    print(f"Fetching 12-month daily history for {len(tickers_lst)} tickers...")

    existing_dct = load_existing_history()
    tickers_dct  = existing_dct.get("tickers", {})
    errors_lst   = []

    # Shared requests session with cookies (used by v8 fallback)
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get("https://finance.yahoo.com/quote/AAPL/", timeout = TIMEOUT_SEC)   # seed cookies

    for ticker in tickers_lst:
        print(f"  {ticker:8s} ...", flush = True)
        try:
            currency, new_history_lst = fetch_ticker_history(ticker, session)

            existing_hist = tickers_dct.get(ticker, {}).get("history", [])
            merged_lst    = merge_history(existing_hist, new_history_lst)
            trimmed_lst   = trim_to_12_months(merged_lst)

            tickers_dct[ticker] = {"currency": currency, "history": trimmed_lst}

            added   = len(trimmed_lst) - len(existing_hist)
            last_dt = trimmed_lst[-1]["date"]  if trimmed_lst else "—"
            last_px = trimmed_lst[-1]["close"] if trimmed_lst else "—"
            print(f"    {len(trimmed_lst):3d} days  last={last_dt}  close={last_px}  +{max(added, 0)} new")

        except Exception as e:
            print(f"    ERROR: {e}")
            errors_lst.append({"ticker": ticker, "error": str(e)})

        time.sleep(0.3)   # be polite — avoid rate limiting between tickers

    now_ro     = datetime.now(tz = ROMANIAN_TZ)
    output_dct = {
        "updated_at"    : now_ro.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at_tz" : "EEST (UTC+3)",
        "tickers"       : tickers_dct,
        "errors"        : errors_lst,
    }

    with open(HISTORY_FILE, "w", encoding = "utf-8") as f:
        json.dump(output_dct, f, indent = 2)

    ok_count  = len(tickers_dct)
    err_count = len(errors_lst)
    print(f"\nSaved history for {ok_count} tickers to {HISTORY_FILE}  ({now_ro.strftime('%Y-%m-%d %H:%M:%S')} EEST)")
    if errors_lst:
        print(f"Errors ({err_count}): {[e['ticker'] for e in errors_lst]}")
# end def main


if __name__ == "__main__":
    main()
