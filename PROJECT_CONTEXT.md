# PROJECT_CONTEXT.md — Trade PDF Processor + HTML Report

## Purpose

Two-script pipeline that processes PDF trade confirmation files (from TradeVille / XTB),
extracts trade data, and generates an interactive HTML report with current market prices.

## Files

- `process_trade_pdfs.py` — PDF reader, data extractor, file renamer
- `gen_report.py` — HTML report generator (reads JSON, fetches live prices)

## Dependencies

- Python 3.10+
- `pymupdf` (imported as `fitz`) — PDF text extraction
- `yfinance` — current stock price fetching (used by gen_report.py)
- Standard library: `sys`, `os`, `re`, `json`, `html`, `datetime`

Install: `pip install pymupdf yfinance`

## Usage

```
# Step 1: Process PDFs → produces trades_output.txt + trades_data.json
python process_trade_pdfs.py <folder_with_pdfs> [--debug]

# Step 2: Generate HTML report → produces foxland-trades-YEAR.html
python gen_report.py <folder_with_json>
```

## process_trade_pdfs.py

### What It Does

1. **Scans** the given folder for all `.pdf` files (sorted alphabetically).
2. **Reads** the first page of each PDF using PyMuPDF.
3. **Extracts** trade fields from Romanian-language text (with diacritics or middle-dot
   substitutes from PDF rendering):
   - Ticker, action (BUY/SELL), number of shares, price per share
   - Portfolio percentage, accumulation threshold, sell thresholds (min + max)
   - Investment term (for BUY), sell type + return percentage (for SELL)
   - Risk level, position value
4. **Renames** files to `YYYY-MM-DD_TICKER_buy/sell_PRICE.pdf` format:
   - Price in filename is rounded to nearest integer
   - `buy`/`sell` in lowercase
   - Files already starting with `YYYY-MM-DD` are left untouched (data still extracted)
   - Rename is skipped with a visible `*** WARNING ***` when date, action, or price
     cannot be determined
   - PermissionError (file locked on Windows) is caught with a warning
5. **Outputs** data in three formats:
   - **Console** (stdout): full detail, tab-separated
   - **File** (`trades_output.txt`): different column order for Excel paste
   - **JSON** (`trades_data.json`): all fields with native types, consumed by gen_report.py
   - All outputs sorted descending by date (newest first)

### `--debug` Flag

When a ticker cannot be extracted, dumps the last 600 chars of the PDF's first page text
to stderr for troubleshooting regex mismatches.

## gen_report.py

### What It Does

1. **Reads** `trades_data.json` from the specified folder.
2. **Fetches** current stock prices for all tickers via Yahoo Finance (`yfinance`).
3. **Generates** `foxland-trades-YEAR.html` — an interactive HTML report.

### HTML Report Features

- **Sortable columns**: click Date (desc first) or Ticker (asc first) to toggle sort
- **Alternating row colors**: white / light gray, with blue hover highlight
- **Action coloring**: BUY in green, SELL in red
- **Position Value**: rounded to nearest thousand, displayed as `Nk` (e.g., `17k`)
- **Sell Above Min/Max and Accum. Below**: displayed without decimals
- **Right-aligned numeric columns**: Shares, Price $, Portfolio %, Accum. Below $,
  Sell Above Min $, Sell Above Max $, Price $ date, Avg. Upside, Position Value
- **Current price column**: header shows `Price $ DD-MMM` (today's date)
- **Avg. Upside column**: percentage from current price to midpoint of sell range;
  green for positive, red for negative; blank for SELL rows
- **Last column**: shows investment term for BUY rows (e.g., `18-24`),
  sell type + return for SELL rows (e.g., `full sale, +120%`)

### Report Filename

`foxland-trades-YEAR.html` where YEAR is derived from trade dates:
- `foxland-trades-2026.html` if all trades are from 2026
- `foxland-trades-2024-2026.html` if trades span 2024 to 2026

The year also appears in the HTML title: "Trade Summary Report 2026".

## File Naming Convention

**Input filenames** (examples):
- `Tranzacție #1 18.02.pdf` — DD.MM anywhere in name
- `15.03 MSFT vanzare.pdf` — DD.MM at start
- `2026-02-04_CRDO_buy_100.pdf` — already in final format (skip rename)

**Output filename pattern**: `2026-MM-DD_TICKER_buy/sell_PRICE.pdf`
- Year is hardcoded to 2026 in process_trade_pdfs.py
- Date extracted from original filename (DD.MM pattern)
- Price rounded to nearest integer

## PDF Text Patterns Recognized

The script parses Romanian-language trade confirmations. Key patterns (with diacritic
and middle-dot variants):

| Field              | Text pattern                                                |
|--------------------|-------------------------------------------------------------|
| Action BUY         | `am cumpărat` / `am cump·rat`                              |
| Action SELL        | `am vândut` / `am v·ndut` / `am lichidat`                   |
| Ticker + shares    | `N de acțiuni în TICKER` (multiple fallback patterns)       |
| Price              | `la prețul [de] [aprox.] $PRICE`                            |
| Portfolio %        | `N% din portofoliu`                                         |
| Accumulate below   | `acumulare sub $N`                                          |
| Sell above         | `vânzare peste $MIN-MAX`                                    |
| Term               | `termen mediu/lung (N-M luni)`                              |
| Risk               | `Riscul operațiunii N/10`                                   |
| Position value     | `Poziția este evaluată la $N`                               |
| Sell type          | `vânzare completă` / `vânzare parțială`                     |
| Return %           | `randament +N%` / `randament -N%`                           |

## Romanian Diacritics Handling

PyMuPDF sometimes renders Romanian diacritics (`ț`, `ș`, `ă`, `â`, `î`) as `·`
(U+00B7 middle dot) when the font doesn't embed them. All regex patterns include `·`
as an alternative in character classes (e.g., `ac[tț·]iuni`, `pre[tț·]ul`).

## Price Parsing (`parse_price`)

Handles Romanian/mixed number formats:
- `30,20` → 30.20 (comma as decimal, Romanian style)
- `1.513,20` → 1513.20 (dot as thousands, comma as decimal)
- `10.626` → 10626 (dot as thousands, no decimal — detected by 3-digit rule)
- Trailing sentence punctuation is stripped before parsing

## Date Extraction from Filename

- Searches for `DD.MM` pattern anywhere in the filename (not just at start)
- Validates: day 1-31, month 1-12
- Rejects ambiguous filenames with multiple valid DD.MM candidates
- Files already starting with `YYYY-MM-DD` are recognized and left alone

## Coding Conventions

- `_lst` suffix for lists, `_dct` suffix for dicts, `_tpl` suffix for tuples
- `# end def function_name` at end of long functions
- Aligned `=` signs on related consecutive assignments
- Max line length ~200 chars
- Spaces around `=` in keyword arguments
- Comments and code in English
- Romanian text in regex patterns only (matching PDF content)

## Known Limitations

- Year is hardcoded to 2026 in process_trade_pdfs.py (used when building date from DD.MM filenames)
- Only reads the first page of each PDF
- Regex-based extraction — unusual text formatting may cause extraction failures
  (use `--debug` to troubleshoot)
- `parse_price` heuristic for 3-digit-after-dot → thousands separator may
  misidentify some edge-case prices
- yfinance may fail for delisted tickers or during market outages; report still
  generates with empty price/upside cells
