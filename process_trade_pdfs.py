#!/usr/bin/env python3
"""
Process PDF trade confirmation files from a given folder.
- Reads the first page of each PDF
- Extracts trade info (ticker, price, action, etc.)
- Renames files to DATE_TICKER_buy/sell_PRICE.pdf format
- Prints tab-separated data for direct paste into Excel
"""

import sys
import os
import re
import json
import fitz  # PyMuPDF


def extract_trade_info(text):
    """Extract all relevant fields from the first page text."""
    info_dct = {}

    # Normalize whitespace: replace newlines, tabs, multiple spaces with single space
    # This handles PDF line-break artifacts
    text_norm = re.sub(r'\s+', ' ', text)

    # PDF extraction often renders Romanian diacritics (ț, ș, ă, â, î) as · (middle dot)
    # We use character classes that match both the real diacritic and · everywhere

    # Detect BUY / SELL
    text_lower = text_norm.lower()
    if re.search(r'am\s+cump[aă·]rat', text_lower):
        info_dct["action"] = "BUY"
    elif re.search(r'am\s+(v[aâ·]ndut|lichidat)', text_lower):
        info_dct["action"] = "SELL"
    else:
        info_dct["action"] = "UNKNOWN"

    # Ticker + shares extraction strategy:
    # 1. First try the STRUCTURED trade line (after "am cumpărat/vândut") — most reliable
    # 2. Fall back to generic patterns if structured line not found
    # The structured line may have parenthetical words: "acțiuni (net) în TICKER"
    # Tickers are ALWAYS uppercase letters only (e.g., IESC, ERO, POWL)

    # Priority 1: structured line "am cumpărat/vândut N de acțiuni [(...)] în TICKER"
    m = re.search(
        r'am\s+(?:cump[aă·]rat|v[aâ·]ndut|lichidat)\s+'
        r'(\d+)\s+(?:de\s+)?ac[tț·]iuni'
        r'(?:\s*\([^)]*\))?\s+'       # optional parenthetical like (net), (acumulare)
        r'[iî·]n\s+([A-Z]{2,10})',
        text_norm
    )
    if m:
        info_dct["shares"] = int(m.group(1))
        info_dct["ticker"] = m.group(2)

    # Priority 2: generic "N de acțiuni [(...)] în TICKER"
    if not info_dct.get("ticker"):
        for m in re.finditer(
            r'(\d+)\s+(?:de\s+)?ac[tț·]iuni'
            r'(?:\s*\([^)]*\))?\s+'
            r'[iî·]n\s+([A-Z]{2,10})',
            text_norm
        ):
            info_dct["shares"] = int(m.group(1))
            info_dct["ticker"] = m.group(2)
            break

    # Fallback: uppercase word after "în" that looks like a ticker
    if not info_dct.get("ticker"):
        m = re.search(
            r'ac[tț·]iuni(?:\s*\([^)]*\))?\s+[iî·]n\s+([A-Z]{2,10})',
            text_norm
        )
        if m:
            info_dct["ticker"] = m.group(1)

    # Fallback: "în TICKER (" pattern
    if not info_dct.get("ticker"):
        m = re.search(
            r'[iî·]n\s+([A-Z]{2,10})\s*\(',
            text_norm
        )
        if m:
            info_dct["ticker"] = m.group(1)

    # Shares: standalone pattern if not found above
    if not info_dct.get("shares"):
        m = re.search(
            r'(\d+)\s+(?:de\s+)?ac[tț·]iuni',
            text_norm, re.IGNORECASE
        )
        if m:
            info_dct["shares"] = int(m.group(1))

    # Price per share - handles multiple formats:
    #   "la prețul $30,20"
    #   "la prețul de aprox. $454"
    #   "la pre·ul de aprox. $454 (vezi anexe)"
    m = re.search(
        r'la\s+pre[tț·]ul\s+(?:de\s+)?(?:aprox\.?\s+)?\$?\s*([\d.,]+)',
        text_norm, re.IGNORECASE
    )
    if m:
        info_dct["price"] = parse_price(m.group(1))

    # Portfolio percentage - "1,69% din portofoliu"
    m = re.search(
        r'([\d.,]+)\s*%\s*din\s+portofoliu',
        text_norm, re.IGNORECASE
    )
    if m:
        info_dct["portfolio_pct"] = parse_price(m.group(1))

    # Accumulation threshold - "acumulare sub $35"
    m = re.search(
        r'acumulare\s+sub\s+\$?\s*([\d.,]+)',
        text_norm, re.IGNORECASE
    )
    if m:
        info_dct["accumulate_below"] = parse_price(m.group(1))

    # Sell threshold - "vânzare peste $65-75" / "v·nzare peste $65-75"
    m = re.search(
        r'v[aâ·]nzare\s+peste\s+\$?\s*([\d.,]+)\s*[-–]\s*\$?\s*([\d.,]+)',
        text_norm, re.IGNORECASE
    )
    if m:
        info_dct["sell_above_min"] = parse_price(m.group(1))
        info_dct["sell_above_max"] = parse_price(m.group(2))
    else:
        m = re.search(
            r'v[aâ·]nzare\s+peste\s+\$?\s*([\d.,]+)',
            text_norm, re.IGNORECASE
        )
        if m:
            info_dct["sell_above_min"] = parse_price(m.group(1))
            info_dct["sell_above_max"] = ""

    # Investment term - "termen mediu (18-24 luni)"
    m = re.search(
        r'termen\s+\w+\s+\((\d+\s*[-–]\s*\d+)\s+luni\)',
        text_norm, re.IGNORECASE
    )
    if m:
        info_dct["term"] = m.group(1).replace("–", "-").replace(" ", "")

    # Risk level - "Riscul operațiunii 7/10" / "Riscul opera·iunii 7/10"
    m = re.search(
        r'riscul\s+opera[tț·]iunii\s+(\d+)\s*/\s*(\d+)',
        text_norm, re.IGNORECASE
    )
    if m:
        info_dct["risk"] = f"{m.group(1)}/{m.group(2)}"

    # Position value - "Poziția este evaluată la $10.626" / "Pozi·ia este evaluat· la $10.626"
    m = re.search(
        r'pozi[tț·]ia\s+este\s+evaluat[aă·]\s+la\s+\$?\s*([\d.,]+)',
        text_norm, re.IGNORECASE
    )
    if m:
        info_dct["position_value"] = parse_price(m.group(1))

    # --- SELL-specific fields ---

    # Sell type: "vânzare completă" / "vânzare parțială" / "v·nzare complet·"
    m = re.search(
        r'v[aâ·]nzare\s+(complet[aă·]|par[tț·]ial[aă·])',
        text_norm, re.IGNORECASE
    )
    if m:
        raw = m.group(1).lower()
        if raw.startswith("complet"):
            info_dct["sell_type"] = "full sale"
        else:
            info_dct["sell_type"] = "partial sale"

    # Return percentage: "randament +120%" or "randament -15%"
    m = re.search(
        r'randament\s+([+-]?\s*[\d.,]+)\s*%',
        text_norm, re.IGNORECASE
    )
    if m:
        val = m.group(1).replace(" ", "")
        info_dct["return_pct"] = val + "%"

    return info_dct


def parse_price(val_str):
    """
    Convert a price from Romanian/mixed format to a float.
    Examples: '30,20' -> 30.20, '10.626' -> 10626, '1.513,20' -> 1513.20
    Rule: if the last separator is a comma, it's a Romanian decimal.
    """
    val_str = val_str.strip()
    # Strip trailing sentence punctuation
    val_str = val_str.rstrip(".,")
    if not val_str:
        return ""

    last_comma = val_str.rfind(",")
    last_dot = val_str.rfind(".")

    if last_comma > last_dot:
        # Comma is decimal separator (Romanian: 1.513,20)
        val_str = val_str.replace(".", "").replace(",", ".")
    elif last_dot > last_comma:
        # Dot might be decimal (US format) or thousands separator
        after_dot = val_str[last_dot + 1:]
        if last_comma == -1 and len(after_dot) == 3 and after_dot.isdigit():
            # Thousands separator: 10.626 -> 10626
            val_str = val_str.replace(".", "")
        else:
            val_str = val_str.replace(",", "")
    else:
        # No separators or both missing
        val_str = val_str.replace(",", "").replace(".", "")

    try:
        return float(val_str)
    except ValueError:
        return val_str


def extract_date_from_filename(filename):
    """
    Extract day and month from the filename.
    Accepts: '20.02 ...' (DD.MM format) or '2026-01-10...' (YYYY-MM-DD).
    Returns (day, month, warning) as zero-padded strings + optional warning.
    """
    # Try full YYYY-MM-DD format first (already validated)
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', filename)
    if m:
        return m.group(3), m.group(2), None

    # Find ALL DD.MM candidates in the filename
    # Use word-boundary-like logic: DD.MM should not be part of a longer number
    candidates_lst = []
    for m in re.finditer(r'(?<!\d)(\d{1,2})\.(\d{1,2})(?!\d)', filename):
        day_val = int(m.group(1))
        month_val = int(m.group(2))
        # Validate: day 1-31, month 1-12
        if 1 <= day_val <= 31 and 1 <= month_val <= 12:
            candidates_lst.append((m.group(1).zfill(2), m.group(2).zfill(2)))

    if len(candidates_lst) == 1:
        day, month = candidates_lst[0]
        return day, month, None
    elif len(candidates_lst) > 1:
        # Multiple valid dates found — ambiguous
        pairs = [f"{d}.{m}" for d, m in candidates_lst]
        warning = f"multiple date candidates found: {', '.join(pairs)}"
        return None, None, warning

    return None, None, "no valid date (DD.MM) found in filename"


def has_full_date_prefix(filename):
    """Check if the filename already starts with YYYY-MM-DD format."""
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', filename)
    if not m:
        return False
    # Validate the existing date
    month_val = int(m.group(2))
    day_val = int(m.group(3))
    return 1 <= month_val <= 12 and 1 <= day_val <= 31


def format_price_for_filename(price):
    """Format price for filename: rounded to nearest integer."""
    if isinstance(price, (int, float)):
        return str(round(price))
    return str(price)


def format_pct(val):
    """Format a percentage value with % suffix. Returns empty string if no value."""
    if val == "" or val is None:
        return ""
    return f"{val}%"


def process_folder(folder_path, debug=False):
    """Process all PDF files in the given folder."""
    if not os.path.isdir(folder_path):
        print(f"Error: '{folder_path}' is not a valid folder.")
        sys.exit(1)

    files_lst = sorted([
        f for f in os.listdir(folder_path)
        if f.lower().endswith(".pdf")
    ])

    if not files_lst:
        print(f"No PDF files found in '{folder_path}'.")
        sys.exit(0)

    print(f"Found {len(files_lst)} PDF file(s) in '{folder_path}'.\n", file=sys.stderr)

    # Collect all trade data, then sort and output
    all_trades_lst = []

    for filename in files_lst:
        filepath = os.path.join(folder_path, filename)

        try:
            doc = fitz.open(filepath)
        except Exception as e:
            print(f"# Error opening '{filename}': {e}", file=sys.stderr)
            continue

        # Read first page only
        if len(doc) == 0:
            print(f"# '{filename}' has no pages.", file=sys.stderr)
            doc.close()
            continue

        page = doc[0]
        text = page.get_text()
        doc.close()
        del doc  # Ensure file handle is fully released (important on Windows)

        # Extract trade info from text
        info_dct = extract_trade_info(text)

        if not info_dct.get("ticker"):
            print(f"# '{filename}': could not extract ticker.", file=sys.stderr)
            if debug:
                # Dump last ~600 chars of first page (where trade info usually is)
                snippet = text.strip()[-600:]
                print(f"# --- DEBUG text (last 600 chars) for '{filename}' ---",
                      file=sys.stderr)
                print(f"# {repr(snippet)}", file=sys.stderr)
                print(f"# --- END DEBUG ---", file=sys.stderr)
            continue

        # Build date string from filename
        day, month, date_warning = extract_date_from_filename(filename)
        if day and month:
            date_str = f"2026-{month}-{day}"
        else:
            date_str = "UNKNOWN"

        # Validate extracted fields before renaming
        rename_warnings_lst = []
        if date_str == "UNKNOWN":
            rename_warnings_lst.append(
                f"DATE: {date_warning or 'could not determine date'}"
            )
        if info_dct.get("action") == "UNKNOWN":
            rename_warnings_lst.append("ACTION: could not determine buy/sell")
        if not info_dct.get("price"):
            rename_warnings_lst.append("PRICE: could not extract price")

        # Rename file if it doesn't already match the final pattern (YYYY-MM-DD_...)
        if has_full_date_prefix(filename):
            print(f"# Already named: '{filename}' (skipping rename, data extracted)",
                  file=sys.stderr)
        elif rename_warnings_lst:
            # Do NOT rename — show visible warning instead
            print(f"\n  *** WARNING: Skipping rename for '{filename}' ***",
                  file=sys.stderr)
            for w in rename_warnings_lst:
                print(f"  ***   {w}", file=sys.stderr)
            print(f"  *** Please rename this file manually. ***\n",
                  file=sys.stderr)
        else:
            price_str = format_price_for_filename(info_dct.get("price", ""))
            action = info_dct.get("action", "UNKNOWN").lower()
            ticker = info_dct.get("ticker", "UNKNOWN")
            new_name = f"{date_str}_{ticker}_{action}_{price_str}.pdf"
            new_path = os.path.join(folder_path, new_name)

            # Avoid overwriting existing files
            if os.path.exists(new_path):
                print(f"# '{filename}': '{new_name}' already exists, skipping rename.",
                      file=sys.stderr)
            else:
                try:
                    os.rename(filepath, new_path)
                    print(f"# Renamed: '{filename}' -> '{new_name}'", file=sys.stderr)
                except PermissionError:
                    print(f"\n  *** WARNING: Cannot rename '{filename}' - file is locked by another process. ***",
                          file=sys.stderr)
                    print(f"  ***          Close the file and try again.                                    ***\n",
                          file=sys.stderr)
                except OSError as e:
                    print(f"\n  *** WARNING: Cannot rename '{filename}': {e} ***\n",
                          file=sys.stderr)

        # Build last column: term for BUY, sell type + return for SELL
        if info_dct.get("action") == "SELL":
            sell_parts_lst = []
            if info_dct.get("sell_type"):
                sell_parts_lst.append(info_dct["sell_type"])
            if info_dct.get("return_pct"):
                sell_parts_lst.append(info_dct["return_pct"])
            last_col = ", ".join(sell_parts_lst) if sell_parts_lst else ""
        else:
            last_col = info_dct.get("term", "")

        # Store extracted data for output
        info_dct["_date_str"] = date_str
        info_dct["_last_col"] = last_col
        all_trades_lst.append(info_dct)

    # Sort trades descending by date (newest first), UNKNOWN goes to end
    all_trades_lst.sort(
        key=lambda d: d["_date_str"] if d["_date_str"] != "UNKNOWN" else "0000-00-00",
        reverse=True
    )

    # --- Console output (original format) ---
    console_header_lst = [
        "Date", "Ticker", "Action", "Shares", "Price",
        "Portfolio_Pct", "Accumulate_Below",
        "Sell_Above_Min", "Sell_Above_Max",
        "Risk", "Position_Value", "Term_or_Sell_Info"
    ]
    print("\t".join(console_header_lst))

    for t in all_trades_lst:
        row_lst = [
            t["_date_str"],
            t.get("ticker", ""),
            t.get("action", ""),
            str(t.get("shares", "")),
            str(t.get("price", "")),
            format_pct(t.get("portfolio_pct", "")),
            str(t.get("accumulate_below", "")),
            str(t.get("sell_above_min", "")),
            str(t.get("sell_above_max", "")),
            t.get("risk", ""),
            str(t.get("position_value", "")),
            t["_last_col"]
        ]
        print("\t".join(row_lst))

    # --- File output (different column order for Excel) ---
    # Columns: Ticker, Date, Shares, Price, [blank for total], Portfolio_Pct,
    #          [blank], Accumulate_Below, Sell_Above_Min, Sell_Above_Max, Term
    # For SELL lines: sell info goes in the Sell_Above_Max cell
    file_header_lst = [
        "Ticker", "Date", "Shares", "Price", "Total",
        "Portfolio_Pct", "", "Accumulate_Below",
        "Sell_Above_Min", "Sell_Above_Max", "Term"
    ]

    file_lines_lst = ["\t".join(file_header_lst)]
    for t in all_trades_lst:
        is_sell = (t.get("action") == "SELL")

        # For SELL: put sell info (type + return) in Sell_Above_Max column
        if is_sell:
            sell_above_max_cell = t["_last_col"]
        else:
            sell_above_max_cell = str(t.get("sell_above_max", ""))

        file_row_lst = [
            t.get("ticker", ""),
            t["_date_str"],
            str(t.get("shares", "")),
            str(t.get("price", "")),
            "",                                          # blank for total
            format_pct(t.get("portfolio_pct", "")),
            "",                                          # blank
            str(t.get("accumulate_below", "")),
            str(t.get("sell_above_min", "")),
            sell_above_max_cell,
            t.get("term", "") if not is_sell else ""
        ]
        file_lines_lst.append("\t".join(file_row_lst))

    output_path = os.path.join(folder_path, "trades_output.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        for line in file_lines_lst:
            f.write(line + "\n")

    # --- JSON output (all extracted data, clean keys) ---
    json_trades_lst = []
    for t in all_trades_lst:
        trade_dct = {
            "date":             t.get("_date_str", ""),
            "ticker":           t.get("ticker", ""),
            "action":           t.get("action", ""),
            "shares":           t.get("shares", ""),
            "price":            t.get("price", ""),
            "portfolio_pct":    t.get("portfolio_pct", ""),
            "accumulate_below": t.get("accumulate_below", ""),
            "sell_above_min":   t.get("sell_above_min", ""),
            "sell_above_max":   t.get("sell_above_max", ""),
            "risk":             t.get("risk", ""),
            "position_value":   t.get("position_value", ""),
            "term":             t.get("term", ""),
            "sell_type":        t.get("sell_type", ""),
            "return_pct":       t.get("return_pct", ""),
        }
        json_trades_lst.append(trade_dct)

    json_path = os.path.join(folder_path, "trades_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_trades_lst, f, indent=2, ensure_ascii=False)

    print(f"\n# Output saved to: {output_path}", file=sys.stderr)
    print(f"# JSON saved to:   {json_path}", file=sys.stderr)
    print(f"# {len(all_trades_lst)} trade(s) extracted, sorted by date (newest first).",
          file=sys.stderr)
    print("# Copy lines from the .txt file and paste into Excel (tab-separated).",
          file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python process_trade_pdfs.py <folder_with_pdfs> [--debug]")
        sys.exit(1)

    debug = "--debug" in sys.argv
    folder = [a for a in sys.argv[1:] if not a.startswith("--")][0]
    process_folder(folder, debug=debug)
