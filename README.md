# Foxland Trade PDF Processor

Tools for processing trade confirmation PDFs and generating interactive HTML reports
for the Foxland investment portfolio.

## What This Does

Each time a trade is executed through TradeVille or XTB, a PDF confirmation is saved
with details about the transaction: ticker, price, number of shares, portfolio allocation,
target prices, investment thesis parameters, and risk assessment.

This project automates two things:

1. **Organizes the PDFs** — renames files from their original names
   (e.g., `Tranzacție #1 18.02.pdf`) into a consistent, sortable format
   (`2026-02-18_ERO_buy_30.pdf`).

2. **Generates an HTML report** — extracts all trade data into a single interactive
   table with current market prices, upside calculations, and sortable columns.
   The report is self-contained (one `.html` file, no dependencies) and can be
   opened in any browser.

## Quick Start

```bash
pip install pymupdf yfinance

# Step 1: Process PDFs — extracts data, renames files, outputs JSON
python process_trade_pdfs.py "C:\path\to\pdf\folder"

# Step 2: Generate HTML report from the extracted data
python gen_report.py "C:\path\to\pdf\folder"
```

Step 1 produces three output files in the same folder:
- `trades_output.txt` — tab-separated, ready for Excel paste
- `trades_data.json` — structured data consumed by Step 2
- Renamed PDF files (originals that don't yet follow the naming convention)

Step 2 produces:
- `trades-2026.html` (or `trades-2024-2026.html` if trades span
  multiple years)

## The HTML Report

The report shows all trades in a single table, sorted by date (newest first).
Columns include ticker, date, shares, price, portfolio weight, accumulation and
sell targets, current market price (fetched live from Yahoo Finance), upside to
target midpoint, risk rating, position value, and investment term.

Key features:
- Click **Date** or **Ticker** column headers to sort
- BUY trades in green, SELL trades in red
- Avg. Upside shows how far the current price is from the sell target midpoint
- Position values displayed as rounded thousands (e.g., `45k`)
- Alternating row colors for readability

## PDF Format Expected

The scripts parse Romanian-language trade confirmations. The structured trade line
at the end of the first page is the primary data source and typically looks like:

> la ora 18:56:25, prin TradeVille, am cumpărat 20 de acțiuni (net) în IESC
> (acumulare), la prețul $378 și reprezintă acum 7,09% din portofoliu. [...]
> acumulare sub $400 și vânzare peste $550-620. [...] termen mediu (18-24 luni).
> Riscul operațiunii 6/10. Poziția este evaluată la $45.384.

The body of the PDF (investment thesis, analysis) is ignored — only the structured
trade parameters are extracted.

## File Naming Convention

**Before**: `Tranzacție #1 18.02.pdf`, `15.03 MSFT vanzare.pdf`

**After**: `2026-02-18_IESC_buy_378.pdf`, `2026-03-15_MSFT_sell_420.pdf`

Format: `YYYY-MM-DD_TICKER_buy/sell_PRICE.pdf` (price rounded to nearest integer).
Files already following this convention are left untouched.

## Troubleshooting

If the script can't extract a ticker from a PDF, run with `--debug`:

```bash
python process_trade_pdfs.py folder/ --debug
```

This dumps the raw text extracted from the first page of each problematic PDF,
which helps diagnose regex mismatches — usually caused by unusual formatting or
PyMuPDF rendering diacritics as middle-dot characters.
