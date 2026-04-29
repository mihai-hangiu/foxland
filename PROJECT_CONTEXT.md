# PROJECT_CONTEXT.md — Trade PDF Processor

## Purpose

Script that processes PDF trade confirmation files (from TradeVille / XTB) stored in a folder.
It extracts trade data, renames files to a standardized format, and produces tab-separated
output ready for Excel paste.

## Files

- `process_trade_pdfs.py` — single-file script, no other modules

## Dependencies

- Python 3.10+
- `pymupdf` (imported as `fitz`) — PDF text extraction
- Standard library: `sys`, `os`, `re`

Install: `pip install pymupdf`

## Usage

```
python process_trade_pdfs.py <folder_with_pdfs> [--debug]
```

- `--debug`: when a ticker cannot be extracted, dumps the last 600 chars of the PDF's first
  page text to stderr for troubleshooting.

## What the Script Does

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
   - Files already matching the final pattern (`YYYY-MM-DD_...`) are left untouched
   - Rename is skipped with a visible `*** WARNING ***` when date, action, or price
     cannot be determined
   - PermissionError (file locked on Windows) is caught with a warning
5. **Outputs** data in two formats:
   - **Console** (stdout): full detail, tab-separated, columns:
     `Date | Ticker | Action | Shares | Price | Portfolio_Pct | Accumulate_Below |
     Sell_Above_Min | Sell_Above_Max | Risk | Position_Value | Term_or_Sell_Info`
   - **File** (`trades_output.txt` in the same folder): different column order for Excel,
     tab-separated, columns:
     `Ticker | Date | Shares | Price | [blank: Total] | Portfolio_Pct | [blank] |
     Accumulate_Below | Sell_Above_Min | Sell_Above_Max | Term`
   - Both outputs sorted descending by date (newest first)
   - For SELL lines in the file output, the `Sell_Above_Max` cell contains
     sell type + return (e.g., `full sale, +120%`), and Term is left blank

## File Naming Convention

**Input filenames** (examples):
- `Tranzacție #1 18.02.pdf` — DD.MM anywhere in name
- `15.03 MSFT vanzare.pdf` — DD.MM at start
- `2026-02-04_CRDO_buy_100.pdf` — already in final format

**Output filename pattern**: `2026-MM-DD_TICKER_buy/sell_PRICE.pdf`
- Year is hardcoded to 2026
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

- Year is hardcoded to 2026 (used when building date from DD.MM filenames)
- Only reads the first page of each PDF
- Regex-based extraction — unusual text formatting may cause extraction failures
  (use `--debug` to troubleshoot)
- `parse_price` heuristic for 3-digit-after-dot → thousands separator may
  misidentify some edge-case prices
