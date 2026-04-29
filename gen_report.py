#!/usr/bin/env python3
"""
Generate an HTML report from trades_data.json.
Reads the JSON produced by process_trade_pdfs.py and creates a styled HTML table
with alternating row colors, sortable by Date and Ticker columns.

Features:
- Sortable columns (Date desc/asc, Ticker asc/desc) via click
- Position Value rounded to nearest thousand and displayed as Nk
- Current price fetched from Yahoo Finance for each ticker
- Upside % column: distance from current price to midpoint of sell range

Usage: python gen_report.py <folder_with_json>
       python gen_report.py trades_data.json

Dependencies: yfinance
"""

import sys
import os
import json
from html import escape
from datetime import datetime

try:
    import yfinance as yf
except ImportError:
    print("Error: yfinance is required. Install with: pip install yfinance")
    sys.exit(1)


def format_pct(val):
    """Format a percentage value with % suffix. Returns empty string if no value."""
    if val == "" or val is None:
        return ""
    return f"{val}%"
# end def format_pct


def format_position_value(val):
    """Format position value: round to nearest thousand, display as Nk. E.g. 16770.27 -> '17k'."""
    if val == "" or val is None:
        return ""
    try:
        num = float(val)
    except (ValueError, TypeError):
        return str(val)
    rounded_k = round(num / 1000)
    return f"{rounded_k}k"
# end def format_position_value


def format_no_decimals(val):
    """Format a numeric value without decimals. E.g. 65.0 -> '65', 180.0 -> '180'."""
    if val == "" or val is None:
        return ""
    try:
        num = float(val)
    except (ValueError, TypeError):
        return str(val)
    return str(int(round(num)))
# end def format_no_decimals


def build_last_column(trade_dct):
    """Build the Term_or_Sell_Info column value depending on action type."""
    if trade_dct.get("action") == "SELL":
        parts_lst = []
        if trade_dct.get("sell_type"):
            parts_lst.append(trade_dct["sell_type"])
        if trade_dct.get("return_pct"):
            parts_lst.append(trade_dct["return_pct"])
        return ", ".join(parts_lst) if parts_lst else ""
    else:
        return trade_dct.get("term", "")
# end def build_last_column


def fetch_current_prices(tickers_lst):
    """Fetch current prices for a list of tickers using yfinance. Returns {ticker: price}."""
    prices_dct = {}
    if not tickers_lst:
        return prices_dct

    # Deduplicate
    unique_tickers_lst = list(set(tickers_lst))
    tickers_str = " ".join(unique_tickers_lst)

    print(f"Fetching current prices for: {', '.join(sorted(unique_tickers_lst))}...")

    try:
        data = yf.download(tickers_str, period="5d", progress=False, threads=True)
        if data.empty:
            print("  Warning: yfinance returned no data.")
            return prices_dct

        # yfinance returns different structures for single vs multiple tickers
        if len(unique_tickers_lst) == 1:
            ticker = unique_tickers_lst[0]
            if "Close" in data.columns:
                last_close = data["Close"].dropna().iloc[-1]
                prices_dct[ticker] = round(float(last_close), 2)
        else:
            if "Close" in data.columns:
                close_data = data["Close"]
                for ticker in unique_tickers_lst:
                    if ticker in close_data.columns:
                        series = close_data[ticker].dropna()
                        if not series.empty:
                            prices_dct[ticker] = round(float(series.iloc[-1]), 2)
    except Exception as e:
        print(f"  Warning: yfinance error: {e}")

    found   = len(prices_dct)
    missing = len(unique_tickers_lst) - found
    print(f"  Got prices for {found} ticker(s)." + (f" Missing: {missing}." if missing else ""))

    return prices_dct
# end def fetch_current_prices


def compute_upside(current_price, sell_min, sell_max):
    """
    Compute upside %: how much price must rise from current to reach the midpoint
    of the sell range [sell_min, sell_max].
    Returns formatted string like '+45%' or '-12%', or '' if data is missing.
    """
    if not current_price or current_price <= 0:
        return ""
    try:
        s_min = float(sell_min) if sell_min != "" else None
        s_max = float(sell_max) if sell_max != "" else None
    except (ValueError, TypeError):
        return ""

    if s_min is None and s_max is None:
        return ""
    elif s_min is not None and s_max is not None:
        midpoint = (s_min + s_max) / 2
    elif s_min is not None:
        midpoint = s_min
    else:
        midpoint = s_max

    pct  = ((midpoint - current_price) / current_price) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.0f}%"
# end def compute_upside


def generate_html(trades_lst, prices_dct, price_date_str, year_label):
    """Generate a complete HTML document with a styled, sortable trade summary table."""

    # Pre-compute formatted / derived fields
    for t in trades_lst:
        t["_portfolio_pct_fmt"]  = format_pct(t.get("portfolio_pct", ""))
        t["_last_col"]           = build_last_column(t)
        t["_position_value_fmt"] = format_position_value(t.get("position_value", ""))

        ticker        = t.get("ticker", "")
        current_price = prices_dct.get(ticker)
        t["_current_price"] = f"{current_price:.2f}" if current_price else ""
        t["_upside"]        = compute_upside(current_price, t.get("sell_above_min", ""), t.get("sell_above_max", "")) if t.get("action") != "SELL" else ""

        # Format sell thresholds without decimals
        t["_sell_above_min_fmt"] = format_no_decimals(t.get("sell_above_min", ""))
        t["_sell_above_max_fmt"] = format_no_decimals(t.get("sell_above_max", ""))
        t["_accumulate_below_fmt"] = format_no_decimals(t.get("accumulate_below", ""))

    # Column definitions: (header_label, data_key, sortable_id_or_None, right_align)
    columns_lst = [
        ("Date",                      "date",                  "date",   False),
        ("Ticker",                    "ticker",                "ticker", False),
        ("Action",                    "action",                None,     False),
        ("Shares",                    "shares",                None,     True),
        ("Price $",                   "price",                 None,     True),
        ("Portfolio %",               "_portfolio_pct_fmt",    None,     True),
        ("Accum. Below $",            "_accumulate_below_fmt", None,     True),
        ("Sell Above Min $",          "_sell_above_min_fmt",   None,     True),
        ("Sell Above Max $",          "_sell_above_max_fmt",   None,     True),
        (f"Price $ {price_date_str}", "_current_price",        None,     True),
        ("Avg. Upside",               "_upside",               None,     True),
        ("Risk",                      "risk",                  None,     False),
        ("Position Value",            "_position_value_fmt",   None,     True),
        ("Term / Sell Info",          "_last_col",             None,     False),
    ]

    # Serialize trades data for JavaScript sorting
    js_keys_lst  = [key for _, key, _, _ in columns_lst]
    js_align_lst = ["right" if align else "left" for _, _, _, align in columns_lst]
    js_data_lst  = []
    for t in trades_lst:
        row_dct = {}
        for key in js_keys_lst:
            row_dct[key] = str(t.get(key, ""))
        row_dct["action"] = t.get("action", "")
        js_data_lst.append(row_dct)

    js_data_json  = json.dumps(js_data_lst, ensure_ascii=False)
    js_keys_json  = json.dumps(js_keys_lst, ensure_ascii=False)
    js_align_json = json.dumps(js_align_lst, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trade Summary Report {year_label}</title>
<style>
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
        margin: 30px;
        background: #fff;
        color: #222;
    }}
    h1 {{
        font-size: 22px;
        font-weight: 600;
        margin-bottom: 20px;
    }}
    table {{
        border-collapse: collapse;
        width: 100%;
        font-size: 13px;
    }}
    th {{
        background: #2c3e50;
        color: #fff;
        padding: 8px 10px;
        text-align: left;
        font-weight: 600;
        white-space: nowrap;
    }}
    th.sortable {{
        cursor: pointer;
        user-select: none;
    }}
    th.sortable:hover {{
        background: #3d5166;
    }}
    th .sort-arrow {{
        margin-left: 4px;
        font-size: 10px;
        opacity: 0.5;
    }}
    th .sort-arrow.active {{
        opacity: 1;
    }}
    td {{
        padding: 6px 10px;
        border-bottom: 1px solid #e0e0e0;
        white-space: nowrap;
    }}
    tr.row-even {{ background: #ffffff; }}
    tr.row-odd  {{ background: #f5f5f5; }}
    tr:hover td {{ background: #e8f0fe; }}

    td.action-buy  {{ color: #1a7f37; font-weight: 600; }}
    td.action-sell {{ color: #cf222e; font-weight: 600; }}
    td.upside-pos  {{ color: #1a7f37; }}
    td.upside-neg  {{ color: #cf222e; }}

    .footer {{
        margin-top: 16px;
        font-size: 12px;
        color: #888;
    }}
</style>
</head>
<body>
<h1>Trade Summary Report {year_label}</h1>
<p>{len(trades_lst)} trade(s). Click <b>Date</b> or <b>Ticker</b> to sort.</p>
<table id="tradesTable">
<thead>
<tr>
"""

    # Header row
    for col_name, _, sort_id, right_align in columns_lst:
        align_style = ' style="text-align:right"' if right_align else ''
        if sort_id:
            html += f'  <th class="sortable" data-sort="{sort_id}"{align_style}>{escape(col_name)} <span class="sort-arrow" id="arrow-{sort_id}">&#9660;</span></th>\n'
        else:
            html += f'  <th{align_style}>{escape(col_name)}</th>\n'

    html += """</tr>
</thead>
<tbody id="tradesBody">
</tbody>
</table>
<p class="footer">Generated by gen_report.py from trades_data.json</p>

<script>
const tradesData = """ + js_data_json + """;
const keys = """ + js_keys_json + """;
const aligns = """ + js_align_json + """;

// Sort state: { column, ascending }
let sortState = { column: 'date', ascending: false };

function renderTable(data) {
    const tbody = document.getElementById('tradesBody');
    tbody.innerHTML = '';
    data.forEach((row, idx) => {
        const tr = document.createElement('tr');
        tr.className = idx % 2 === 0 ? 'row-even' : 'row-odd';

        keys.forEach((key, colIdx) => {
            const td = document.createElement('td');
            td.textContent = row[key] || '';

            // Right-align numeric columns
            if (aligns[colIdx] === 'right') {
                td.style.textAlign = 'right';
            }

            if (key === 'action') {
                if (row[key] === 'BUY')  td.className = 'action-buy';
                if (row[key] === 'SELL') td.className = 'action-sell';
            }
            if (key === '_upside' && row[key]) {
                if (row[key].startsWith('+')) td.className = 'upside-pos';
                if (row[key].startsWith('-')) td.className = 'upside-neg';
                if (aligns[colIdx] === 'right') td.style.textAlign = 'right';
            }

            tr.appendChild(td);
        });

        tbody.appendChild(tr);
    });
}

function sortTable(column) {
    // Toggle direction: Date defaults desc-first, Ticker defaults asc-first
    if (sortState.column === column) {
        sortState.ascending = !sortState.ascending;
    } else {
        sortState.column = column;
        sortState.ascending = (column === 'ticker');
    }

    const sorted = [...tradesData].sort((a, b) => {
        let va = a[column] || '';
        let vb = b[column] || '';
        if (va === 'UNKNOWN') return 1;
        if (vb === 'UNKNOWN') return -1;
        let cmp = va.localeCompare(vb);
        return sortState.ascending ? cmp : -cmp;
    });

    // Update sort arrows
    document.querySelectorAll('.sort-arrow').forEach(el => {
        el.classList.remove('active');
        el.textContent = '\\u25BC';
    });
    const arrow = document.getElementById('arrow-' + column);
    if (arrow) {
        arrow.classList.add('active');
        arrow.textContent = sortState.ascending ? '\\u25B2' : '\\u25BC';
    }

    renderTable(sorted);
}

// Click handlers
document.querySelectorAll('th.sortable').forEach(th => {
    th.addEventListener('click', () => sortTable(th.dataset.sort));
});

// Initial render sorted by date descending (no toggle)
renderInitial();

function renderInitial() {
    const sorted = [...tradesData].sort((a, b) => {
        let va = a['date'] || '';
        let vb = b['date'] || '';
        if (va === 'UNKNOWN') return 1;
        if (vb === 'UNKNOWN') return -1;
        return vb.localeCompare(va);  // descending
    });
    // Set arrow active on date
    const arrow = document.getElementById('arrow-date');
    if (arrow) {
        arrow.classList.add('active');
        arrow.textContent = '\u25BC';
    }
    renderTable(sorted);
}
</script>

</body>
</html>
"""

    return html
# end def generate_html


def main():
    if len(sys.argv) < 2:
        print("Usage: python gen_report.py <folder_or_json_file>")
        sys.exit(1)

    arg = sys.argv[1]

    # Accept either a folder (looks for trades_data.json inside) or a direct JSON path
    if os.path.isdir(arg):
        json_path = os.path.join(arg, "trades_data.json")
    else:
        json_path = arg

    if not os.path.isfile(json_path):
        print(f"Error: '{json_path}' not found.")
        sys.exit(1)

    # Read JSON
    with open(json_path, "r", encoding="utf-8") as f:
        trades_lst = json.load(f)

    print(f"Loaded {len(trades_lst)} trade(s) from '{json_path}'.")

    # Fetch current prices for all tickers
    all_tickers_lst = [t["ticker"] for t in trades_lst if t.get("ticker")]
    prices_dct      = fetch_current_prices(all_tickers_lst)

    # Date label for the price column header (today's date as "d-MMM")
    now = datetime.now()
    try:
        price_date_str = now.strftime("%-d-%b")     # Linux/Mac: 29-Apr
    except ValueError:
        price_date_str = now.strftime("%d-%b").lstrip("0")  # Windows fallback

    # Compute year label from trade dates (e.g. "2026" or "2024-2026")
    years_lst = []
    for t in trades_lst:
        date_str = t.get("date", "")
        if date_str and date_str != "UNKNOWN" and len(date_str) >= 4:
            try:
                years_lst.append(int(date_str[:4]))
            except ValueError:
                pass

    if years_lst:
        min_year = min(years_lst)
        max_year = max(years_lst)
        year_label = str(min_year) if min_year == max_year else f"{min_year}-{max_year}"
    else:
        year_label = "unknown"

    # Generate HTML
    html_content = generate_html(trades_lst, prices_dct, price_date_str, year_label)

    # Write HTML next to the JSON file: foxland-trades-YEAR.html
    output_dir  = os.path.dirname(json_path) or "."
    output_path = os.path.join(output_dir, f"foxland-trades-{year_label}.html")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"HTML report saved to: {output_path}")
# end def main


if __name__ == "__main__":
    main()
