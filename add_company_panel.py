"""
add_company_panel.py

Reads the foxland trades HTML report and the portfolio_watchlist.json,
then injects an interactive company info panel at the bottom of the HTML.
The panel includes a 12-month area chart drawn from prices_history.json,
which is fetched at runtime from a configurable GitHub raw URL.

Usage:
    python add_company_panel.py <html_file> <watchlist_json> [--output <out_file>]
                                [--history-url <github_raw_url>]

    --history-url   Full raw GitHub URL to prices_history.json, e.g.:
                    https://raw.githubusercontent.com/user/repo/main/prices_history.json
                    If omitted, the chart section shows a "configure URL" placeholder.

If --output is not given, writes to <html_file_basename>_with_panel.html.
"""

import sys
import os
import re
import json
import argparse
import html as html_mod


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description = "Inject company panel into trades HTML report.")
    parser.add_argument("html_file",      help = "Path to the foxland trades HTML file")
    parser.add_argument("watchlist_json", help = "Path to portfolio_watchlist.json")
    parser.add_argument("--output",       "-o",  default = None, help = "Output HTML file path (optional)")
    parser.add_argument("--history-url",  default = "",           help = "Raw GitHub URL to prices_history.json")
    return parser.parse_args()
# end def parse_args


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PLACEHOLDER_DESCRIPTIONS_LST = [
    "No description available yet.",
    "Company description pending.",
    "Description to be added.",
    "Information not yet populated.",
    "Details coming soon.",
]

PLACEHOLDER_COMMENTS_LST = [
    "Earnings report comment not yet added.",
    "Last report analysis pending.",
    "No earnings commentary yet.",
    "Report notes to be filled in.",
    "Awaiting last earnings review.",
]

def placeholder(lst, ticker):
    """Return a deterministic placeholder from a list, based on the ticker string."""
    return lst[sum(ord(c) for c in ticker) % len(lst)]
# end def placeholder


def extract_tickers_from_html(html_content):
    """Pull the unique set of tickers from the tradesData JS array in the HTML."""
    match = re.search(r'const tradesData\s*=\s*(\[.*?\]);', html_content, re.DOTALL)
    if not match:
        return set()
    try:
        trades_lst = json.loads(match.group(1))
        return {row["ticker"] for row in trades_lst if row.get("ticker") and row["ticker"] != "UNKNOWN"}
    except (json.JSONDecodeError, KeyError):
        return set()
# end def extract_tickers_from_html


def extract_full_sale_tickers(html_content):
    """
    Identify tickers that are currently fully closed — defined as: the ticker has at least
    one 'full sale' SELL row, and no BUY row whose date is strictly after the most recent
    full sale date for that ticker.
    Returns a set of ticker strings.
    """
    match = re.search(r'const tradesData\s*=\s*(\[.*?\]);', html_content, re.DOTALL)
    if not match:
        return set()
    try:
        trades_lst = json.loads(match.group(1))
    except json.JSONDecodeError:
        return set()

    full_sale_date_dct  = {}   # ticker -> latest full-sale date string
    latest_buy_date_dct = {}   # ticker -> latest BUY date string

    for row in trades_lst:
        ticker   = row.get("ticker", "")
        action   = row.get("action", "")
        date_str = row.get("date",   "") or ""
        last_col = row.get("_last_col", "") or ""

        if not ticker or ticker == "UNKNOWN":
            continue
        if action == "BUY":
            if date_str > latest_buy_date_dct.get(ticker, ""):
                latest_buy_date_dct[ticker] = date_str
        if action == "SELL" and "full sale" in last_col.lower():
            if date_str > full_sale_date_dct.get(ticker, ""):
                full_sale_date_dct[ticker] = date_str

    full_sale_set = set()
    for ticker, sale_date in full_sale_date_dct.items():
        if latest_buy_date_dct.get(ticker, "") <= sale_date:
            full_sale_set.add(ticker)
    return full_sale_set
# end def extract_full_sale_tickers


def build_company_data_js(watchlist_lst, html_tickers_set):
    """Build a JS object literal mapping ticker -> company info dict."""
    filtered_lst = [entry for entry in watchlist_lst if entry.get("ticker") in html_tickers_set]
    filtered_lst.sort(key = lambda e: e["ticker"])

    company_dct = {}
    for entry in filtered_lst:
        ticker = entry["ticker"]
        company_dct[ticker] = {
            "company_name":        entry.get("company_name")        or f"{ticker} Inc.",
            "company_description": entry.get("company_description") or placeholder(PLACEHOLDER_DESCRIPTIONS_LST, ticker),
            "target_price_min":    entry.get("target_price_min"),
            "target_price_max":    entry.get("target_price_max"),
            "investment_risk":     entry.get("investment_risk"),
            "last_report_comment": entry.get("last_report_comment") or placeholder(PLACEHOLDER_COMMENTS_LST, ticker),
        }
    return f"const companyData = {json.dumps(company_dct, ensure_ascii = False, indent = 4)};"
# end def build_company_data_js


def build_ticker_tabs_html(watchlist_lst, html_tickers_set, full_sale_set):
    """Build the ticker button row HTML. Full-sale tickers get a distinct style."""
    tickers_lst = sorted(
        entry["ticker"] for entry in watchlist_lst if entry.get("ticker") in html_tickers_set
    )
    buttons_lst = []
    for t in tickers_lst:
        safe = html_mod.escape(t)
        if t in full_sale_set:
            label = f'{safe}<span class="sold-marker" title="Full sale — position closed">&#x2297;</span>'
            buttons_lst.append(
                f'<button class="ticker-tab ticker-sold" data-ticker="{safe}" onclick="togglePanel(\'{safe}\')">{label}</button>'
            )
        else:
            buttons_lst.append(
                f'<button class="ticker-tab" data-ticker="{safe}" onclick="togglePanel(\'{safe}\')">{safe}</button>'
            )
    return "\n        ".join(buttons_lst)
# end def build_ticker_tabs_html


# ---------------------------------------------------------------------------
# Panel CSS
# ---------------------------------------------------------------------------

PANEL_CSS = """
    /* ── Company Panel ─────────────────────────────────────────────── */
    #company-panel-wrapper {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        z-index: 1000;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
        font-size: 13px;
    }

    /* ── Ticker bar ──────────────────────────────────────────────────*/
    #ticker-bar {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
        padding: 6px 10px;
        background: #1e2d3d;
        border-top: 2px solid #4a90d9;
        align-items: center;
    }
    #ticker-bar-label {
        font-size: 11px;
        font-weight: 600;
        color: #6a8fa8;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-right: 4px;
        white-space: nowrap;
    }

    /* ── Active-position ticker buttons ──────────────────────────────*/
    .ticker-tab {
        padding: 3px 9px;
        border: 1px solid #3a5268;
        border-radius: 3px;
        background: #253647;
        color: #a8c8e0;
        font-size: 12px;
        font-weight: 600;
        font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
        cursor: pointer;
        letter-spacing: 0.04em;
        transition: background 0.15s, color 0.15s, border-color 0.15s;
        display: inline-flex;
        align-items: center;
        gap: 4px;
    }
    .ticker-tab:hover  { background: #2e4a63; color: #d0eaf8; border-color: #5ba0cc; }
    .ticker-tab.active { background: #4a90d9; color: #ffffff;  border-color: #4a90d9; }

    /* ── Full-sale (closed) ticker buttons ───────────────────────── */
    .ticker-tab.ticker-sold {
        background: transparent;
        border-color: #4a3a3a;
        color: #7a6060;
        text-decoration: line-through;
        text-decoration-color: #6a5050;
        opacity: 0.75;
    }
    .ticker-tab.ticker-sold:hover  { background: #2e2020; color: #b08080; border-color: #7a4040; opacity: 1; text-decoration: none; }
    .ticker-tab.ticker-sold.active { background: #5a3030; color: #f0c8c8; border-color: #a05050; text-decoration: none; opacity: 1; }
    .sold-marker { font-size: 11px; opacity: 0.7; color: #905858; line-height: 1; text-decoration: none; }
    .ticker-tab.ticker-sold.active .sold-marker { color: #f0a0a0; opacity: 1; }

    /* ── Close button ─────────────────────────────────────────────── */
    #panel-close-btn {
        margin-left: auto;
        padding: 3px 11px;
        border: 1px solid #4a6a2a;
        border-radius: 3px;
        background: #273a18;
        color: #90c060;
        font-size: 12px;
        font-weight: 600;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
        cursor: pointer;
        letter-spacing: 0.03em;
        white-space: nowrap;
        display: none;
        align-items: center;
        gap: 4px;
        flex-shrink: 0;
        transition: background 0.15s, color 0.15s, border-color 0.15s;
    }
    #panel-close-btn:hover   { background: #344f20; color: #b8e080; border-color: #6a9a3a; }
    #panel-close-btn.visible { display: inline-flex; }
    #panel-close-btn .close-x { font-size: 15px; font-weight: 300; line-height: 1; }

    /* ── Expanding info panel ─────────────────────────────────────── */
    #company-info-panel {
        background: #1a2535;
        border-top: 1px solid #2e4a63;
        color: #c8dde8;
        max-height: 0;
        overflow: hidden;
        transition: max-height 0.3s ease, padding 0.3s ease;
    }
    #company-info-panel.open {
        max-height: 340px;
        padding: 14px 18px 12px 18px;
        overflow-y: auto;
    }

    /* ── Full-sale banner ─────────────────────────────────────────── */
    #panel-sold-banner {
        display: none;
        align-items: center;
        gap: 8px;
        background: #2e1a1a;
        border: 1px solid #6a3030;
        border-radius: 4px;
        padding: 5px 10px;
        margin-bottom: 10px;
        font-size: 11px;
        font-weight: 700;
        color: #c07070;
        letter-spacing: 0.07em;
        text-transform: uppercase;
    }
    #panel-sold-banner.visible { display: flex; }
    #panel-sold-banner .sold-icon { font-size: 14px; }

    /* ── Panel inner grid: 3 columns (info | metrics | chart) ───── */
    #panel-inner {
        display: grid;
        grid-template-columns: 1.1fr 0.85fr 1.4fr;
        gap: 10px 20px;
        align-items: start;
    }

    .panel-section-title {
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: #4a90d9;
        margin-bottom: 4px;
    }
    #panel-company-name {
        font-size: 14px;
        font-weight: 700;
        color: #e8f4ff;
        margin-bottom: 4px;
    }
    #panel-description {
        font-size: 11px;
        color: #9ab8cc;
        line-height: 1.5;
        max-height: 72px;
        overflow-y: auto;
    }

    .panel-metrics { display: flex; flex-direction: column; gap: 4px; }
    .metric-row {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        border-bottom: 1px solid #253647;
        padding-bottom: 3px;
    }
    .metric-label { font-size: 10px; color: #6a8fa8; text-transform: uppercase; letter-spacing: 0.06em; }
    .metric-value { font-size: 11px; font-weight: 600; color: #d0eaf8; font-family: "SFMono-Regular", Consolas, monospace; }
    .metric-value.pos  { color: #4caf7d; }
    .metric-value.neg  { color: #e05c5c; }
    .metric-value.null { color: #4a6070; font-style: italic; font-weight: 400; }

    #panel-report-wrap { grid-column: 1 / -1; }
    #panel-report {
        font-size: 11px;
        color: #9ab8cc;
        line-height: 1.5;
        max-height: 50px;
        overflow-y: auto;
        font-style: italic;
    }

    /* ── Chart column ─────────────────────────────────────────────── */
    #panel-chart-col { display: flex; flex-direction: column; min-width: 0; }
    #panel-chart-title {
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: #4a90d9;
        margin-bottom: 4px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    #panel-chart-subtitle { font-size: 10px; color: #6a8fa8; font-weight: 400; text-transform: none; letter-spacing: 0; }
    #panel-chart-wrap {
        position: relative;
        width: 100%;
        height: 120px;
        background: #121d2a;
        border: 1px solid #253647;
        border-radius: 3px;
        overflow: hidden;
    }
    #panel-chart-svg {
        width: 100%;
        height: 100%;
        display: block;
    }
    #panel-chart-tooltip {
        position: absolute;
        background: #0d1720;
        border: 1px solid #4a90d9;
        border-radius: 3px;
        padding: 4px 8px;
        font-size: 11px;
        color: #d0eaf8;
        pointer-events: none;
        display: none;
        white-space: nowrap;
        font-family: "SFMono-Regular", Consolas, monospace;
        z-index: 10;
    }
    #panel-chart-loading {
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        color: #4a6070;
        font-style: italic;
    }
    #panel-chart-crosshair {
        position: absolute;
        top: 0;
        bottom: 0;
        width: 1px;
        background: rgba(74, 144, 217, 0.4);
        pointer-events: none;
        display: none;
    }

    /* Thin scrollbars */
    #panel-description::-webkit-scrollbar,
    #panel-report::-webkit-scrollbar,
    #company-info-panel::-webkit-scrollbar { width: 4px; }
    #panel-description::-webkit-scrollbar-thumb,
    #panel-report::-webkit-scrollbar-thumb,
    #company-info-panel::-webkit-scrollbar-thumb { background: #3a5268; border-radius: 2px; }

    /* ── Page spacer ──────────────────────────────────────────────── */
    #panel-page-spacer { height: 50px; }

    /* ── Mobile ───────────────────────────────────────────────────── */
    @media (max-width: 700px) {
        #company-info-panel.open { max-height: 80vh; padding: 12px 12px 10px 12px; }
        #panel-inner { grid-template-columns: 1fr; gap: 10px 0; }
        #panel-report-wrap { grid-column: 1; }
        #panel-chart-wrap { height: 100px; }
        #panel-company-name { font-size: 13px; }
        #ticker-bar { gap: 3px; padding: 5px 8px; }
        .ticker-tab { font-size: 11px; padding: 2px 7px; }
        #panel-close-btn { font-size: 11px; padding: 2px 8px; }
        #ticker-bar-label { display: none; }
    }
"""

# ---------------------------------------------------------------------------
# Panel HTML template
# ---------------------------------------------------------------------------

PANEL_HTML = """
<!-- ── Company Panel (injected by add_company_panel.py) ─────────── -->
<div id="panel-page-spacer"></div>
<div id="company-panel-wrapper">
    <div id="company-info-panel">
        <div id="panel-sold-banner">
            <span class="sold-icon">&#x2298;</span>
            <span>Position fully closed &mdash; historical data only</span>
        </div>
        <div id="panel-inner">

            <!-- Col 1: company info -->
            <div>
                <div class="panel-section-title" id="panel-ticker-label">Company</div>
                <div id="panel-company-name">&#8212;</div>
                <div id="panel-description">&#8212;</div>
            </div>

            <!-- Col 2: metrics -->
            <div class="panel-metrics">
                <div class="metric-row">
                    <span class="metric-label">Current Price</span>
                    <span class="metric-value" id="pm-current-price">&#8212;</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Target Min</span>
                    <span class="metric-value" id="pm-target-min">&#8212;</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Target Max</span>
                    <span class="metric-value" id="pm-target-max">&#8212;</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Upside to Min</span>
                    <span class="metric-value" id="pm-upside-min">&#8212;</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Upside to Max</span>
                    <span class="metric-value" id="pm-upside-max">&#8212;</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Risk</span>
                    <span class="metric-value" id="pm-risk">&#8212;</span>
                </div>
            </div>

            <!-- Col 3: 12-month chart -->
            <div id="panel-chart-col">
                <div id="panel-chart-title">
                    <span>12-Month Price</span>
                    <span id="panel-chart-subtitle"></span>
                </div>
                <div id="panel-chart-wrap">
                    <svg id="panel-chart-svg" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="none"></svg>
                    <div id="panel-chart-crosshair"></div>
                    <div id="panel-chart-tooltip"></div>
                    <div id="panel-chart-loading">Loading chart&#8230;</div>
                </div>
            </div>

            <!-- Bottom row: last report (spans all columns) -->
            <div id="panel-report-wrap">
                <div class="panel-section-title">Last Report</div>
                <div id="panel-report">&#8212;</div>
            </div>

        </div>
    </div>
    <div id="ticker-bar">
        <span id="ticker-bar-label">Companies</span>
        {TICKER_BUTTONS}
        <button id="panel-close-btn" onclick="closePanel()" title="Close panel (Esc)">
            <span class="close-x">&times;</span>Close
        </button>
    </div>
</div>
"""

# ---------------------------------------------------------------------------
# Panel JS template
# ---------------------------------------------------------------------------

PANEL_JS = """
<script>
// ── Company panel data (injected by add_company_panel.py) ─────────
{COMPANY_DATA_JS}

// ── Full-sale (closed) tickers ────────────────────────────────────
const fullSaleTickers = new Set({FULL_SALE_SET_JS});

// ── Raw GitHub URL for prices_history.json ────────────────────────
const HISTORY_URL = {HISTORY_URL_JS};

// ── Current prices from tradesData: ticker -> formatted price string
const currentPriceMap = (function() {
    const map = {};
    tradesData.forEach(row => {
        if (row.ticker && row._current_price && !map[row.ticker]) map[row.ticker] = row._current_price;
    });
    return map;
})();

// ── Cached history data (fetched once per page load) ──────────────
let historyCache = null;     // full parsed prices_history.json
let historyFetchPromise = null;

function getHistory() {
    if (historyCache !== null)    return Promise.resolve(historyCache);
    if (historyFetchPromise)      return historyFetchPromise;
    if (!HISTORY_URL)             return Promise.resolve(null);

    historyFetchPromise = fetch(HISTORY_URL)
        .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(data => { historyCache = data; return data; })
        .catch(err => { console.warn('prices_history.json fetch failed:', err); historyCache = null; return null; });
    return historyFetchPromise;
}

// ── Panel state ───────────────────────────────────────────────────
let activeTicker = null;

function togglePanel(ticker) {
    if (activeTicker === ticker) { closePanel(); return; }
    activeTicker = ticker;
    populatePanel(ticker);
    document.getElementById('company-info-panel').classList.add('open');
    document.getElementById('panel-close-btn').classList.add('visible');
    document.querySelectorAll('.ticker-tab').forEach(b => b.classList.toggle('active', b.dataset.ticker === ticker));
    updateSpacer();
}

function closePanel() {
    document.getElementById('company-info-panel').classList.remove('open');
    document.getElementById('panel-close-btn').classList.remove('visible');
    document.querySelectorAll('.ticker-tab').forEach(b => b.classList.remove('active'));
    activeTicker = null;
    updateSpacer();
}

function updateSpacer() {
    const wrapper = document.getElementById('company-panel-wrapper');
    const spacer  = document.getElementById('panel-page-spacer');
    setTimeout(() => { spacer.style.height = wrapper.offsetHeight + 'px'; }, 320);
}

// ── Metric helpers ────────────────────────────────────────────────

function fmtPrice(v) {
    if (v === null || v === undefined) return null;
    const n = parseFloat(v);
    if (isNaN(n)) return null;
    return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtUpside(currentRaw, targetRaw) {
    if (!currentRaw || targetRaw === null || targetRaw === undefined) return null;
    const cur = parseFloat(String(currentRaw).replace(/[$,]/g, ''));
    const tgt = parseFloat(targetRaw);
    if (isNaN(cur) || isNaN(tgt) || cur === 0) return null;
    const pct = ((tgt - cur) / cur) * 100;
    return { pct, text: (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%' };
}

function setMetric(id, text, cssClass) {
    const el = document.getElementById(id);
    el.textContent = text || '\u2014';
    el.className   = 'metric-value' + (cssClass ? ' ' + cssClass : '');
}

// ── Panel populate ────────────────────────────────────────────────

function populatePanel(ticker) {
    const data   = companyData[ticker] || {};
    const curRaw = currentPriceMap[ticker] || null;
    const tgtMin = data.target_price_min;
    const tgtMax = data.target_price_max;
    const isSold = fullSaleTickers.has(ticker);

    document.getElementById('panel-sold-banner').classList.toggle('visible', isSold);
    document.getElementById('panel-ticker-label').textContent = ticker + (isSold ? '\u2002\u2014\u2002CLOSED' : '');
    document.getElementById('panel-company-name').textContent = data.company_name        || ticker;
    document.getElementById('panel-description').textContent  = data.company_description || '\u2014';
    document.getElementById('panel-report').textContent       = data.last_report_comment || '\u2014';

    setMetric('pm-current-price', curRaw || 'n/a', curRaw ? '' : 'null');

    const minFmt = fmtPrice(tgtMin);
    const maxFmt = fmtPrice(tgtMax);
    setMetric('pm-target-min', minFmt || 'n/a', minFmt ? '' : 'null');
    setMetric('pm-target-max', maxFmt || 'n/a', maxFmt ? '' : 'null');

    const uMin = fmtUpside(curRaw, tgtMin);
    const uMax = fmtUpside(curRaw, tgtMax);
    setMetric('pm-upside-min', uMin ? uMin.text : 'n/a', uMin ? (uMin.pct >= 0 ? 'pos' : 'neg') : 'null');
    setMetric('pm-upside-max', uMax ? uMax.text : 'n/a', uMax ? (uMax.pct >= 0 ? 'pos' : 'neg') : 'null');

    const risk = data.investment_risk;
    setMetric('pm-risk', (risk !== null && risk !== undefined) ? String(risk) : 'n/a', risk ? '' : 'null');

    // Chart — async; show loading state immediately
    renderChartLoading();
    getHistory().then(histData => renderChart(ticker, histData));
}

// ── Chart rendering ───────────────────────────────────────────────

function renderChartLoading() {
    const svg     = document.getElementById('panel-chart-svg');
    const loading = document.getElementById('panel-chart-loading');
    const tip     = document.getElementById('panel-chart-tooltip');
    const cross   = document.getElementById('panel-chart-crosshair');
    svg.innerHTML = '';
    loading.style.display = 'flex';
    loading.textContent   = HISTORY_URL ? 'Loading chart\u2026' : 'Chart URL not configured';
    tip.style.display     = 'none';
    cross.style.display   = 'none';
    document.getElementById('panel-chart-subtitle').textContent = '';
}

function renderChart(ticker, histData) {
    const loading = document.getElementById('panel-chart-loading');
    const svg     = document.getElementById('panel-chart-svg');
    const subtitle = document.getElementById('panel-chart-subtitle');

    if (!histData) {
        loading.textContent = 'Chart unavailable';
        return;
    }

    const tickerData = histData.tickers && histData.tickers[ticker];
    if (!tickerData || !tickerData.history || tickerData.history.length < 2) {
        loading.textContent = 'No history data';
        return;
    }

    const history_lst = tickerData.history;   // already sorted asc by date
    const closes_lst  = history_lst.map(d => d.close).filter(v => v !== null);
    if (closes_lst.length < 2) { loading.textContent = 'Insufficient data'; return; }

    loading.style.display = 'none';

    const minP   = Math.min(...closes_lst);
    const maxP   = Math.max(...closes_lst);
    const rangeP = maxP - minP || 1;

    // SVG viewport constants (logical units; SVG scales via preserveAspectRatio=none)
    const W = 400, H = 100, PAD_L = 2, PAD_R = 2, PAD_T = 6, PAD_B = 4;
    const plotW = W - PAD_L - PAD_R;
    const plotH = H - PAD_T - PAD_B;
    const n     = history_lst.length;

    // Map data point index → SVG x, y
    function px(i) { return PAD_L + (i / (n - 1)) * plotW; }
    function py(v) { return PAD_T + plotH - ((v - minP) / rangeP) * plotH; }

    // Determine color: last close vs first close
    const firstClose = closes_lst[0];
    const lastClose  = closes_lst[closes_lst.length - 1];
    const isUp       = lastClose >= firstClose;
    const lineColor  = isUp ? '#4caf7d' : '#e05c5c';
    const fillStart  = isUp ? 'rgba(76,175,125,0.25)' : 'rgba(224,92,92,0.25)';
    const fillEnd    = isUp ? 'rgba(76,175,125,0.02)' : 'rgba(224,92,92,0.02)';

    // Build polyline points string and area path
    const pts_lst = history_lst.map((d, i) => `${px(i).toFixed(2)},${py(d.close).toFixed(2)}`);
    const polyPts = pts_lst.join(' ');

    // Area path: line points + bottom-right corner + bottom-left corner
    const lastX  = px(n - 1).toFixed(2);
    const firstX = px(0).toFixed(2);
    const bottom = (PAD_T + plotH).toFixed(2);
    const areaPath = `M ${pts_lst[0]} L ${pts_lst.slice(1).join(' L ')} L ${lastX},${bottom} L ${firstX},${bottom} Z`;

    // Target price horizontal lines (if available)
    const compD  = companyData[ticker] || {};
    const tgtMin = compD.target_price_min;
    const tgtMax = compD.target_price_max;
    let extraLines = '';
    if (tgtMin !== null && tgtMin !== undefined) {
        const yMin = py(parseFloat(tgtMin));
        if (yMin >= PAD_T && yMin <= PAD_T + plotH) {
            extraLines += `<line x1="${PAD_L}" y1="${yMin.toFixed(2)}" x2="${W - PAD_R}" y2="${yMin.toFixed(2)}" stroke="#f0a830" stroke-width="0.6" stroke-dasharray="3,2" opacity="0.7"/>`;
            extraLines += `<text x="${W - PAD_R - 1}" y="${(yMin - 1.5).toFixed(2)}" font-size="5.5" fill="#f0a830" text-anchor="end" opacity="0.9">min</text>`;
        }
    }
    if (tgtMax !== null && tgtMax !== undefined) {
        const yMax = py(parseFloat(tgtMax));
        if (yMax >= PAD_T && yMax <= PAD_T + plotH) {
            extraLines += `<line x1="${PAD_L}" y1="${yMax.toFixed(2)}" x2="${W - PAD_R}" y2="${yMax.toFixed(2)}" stroke="#d0a0f0" stroke-width="0.6" stroke-dasharray="3,2" opacity="0.7"/>`;
            extraLines += `<text x="${W - PAD_R - 1}" y="${(yMax - 1.5).toFixed(2)}" font-size="5.5" fill="#d0a0f0" text-anchor="end" opacity="0.9">max</text>`;
        }
    }

    // Month separator tick marks along X axis
    let monthTicks = '';
    let lastMonth  = null;
    history_lst.forEach((d, i) => {
        const month = d.date.substring(0, 7);   // "YYYY-MM"
        if (month !== lastMonth) {
            lastMonth = month;
            const x   = px(i).toFixed(2);
            const lbl = new Date(d.date + 'T12:00:00Z').toLocaleDateString('en-US', { month: 'short', timeZone: 'UTC' });
            monthTicks += `<line x1="${x}" y1="${PAD_T + plotH}" x2="${x}" y2="${PAD_T + plotH + 2.5}" stroke="#3a5268" stroke-width="0.7"/>`;
            monthTicks += `<text x="${x}" y="${H - 0.5}" font-size="5" fill="#5a7a90" text-anchor="middle">${lbl}</text>`;
        }
    });

    // Price labels: min and max on Y axis
    const priceFmt = v => '$' + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const yLabelMin = (PAD_T + plotH - 1).toFixed(2);
    const yLabelMax = (PAD_T + 5).toFixed(2);
    const priceLabels = `
        <text x="${PAD_L + 1}" y="${yLabelMin}" font-size="5" fill="#4a6070" text-anchor="start">${priceFmt(minP)}</text>
        <text x="${PAD_L + 1}" y="${yLabelMax}" font-size="5" fill="#4a6070" text-anchor="start">${priceFmt(maxP)}</text>`;

    // Gradient definition
    const gradId = 'chartGrad_' + ticker.replace(/[^A-Z]/g, '');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.innerHTML = `
        <defs>
            <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"   stop-color="${fillStart}"/>
                <stop offset="100%" stop-color="${fillEnd}"/>
            </linearGradient>
        </defs>
        <path d="${areaPath}" fill="url(#${gradId})"/>
        ${extraLines}
        ${monthTicks}
        ${priceLabels}
        <polyline points="${polyPts}" fill="none" stroke="${lineColor}" stroke-width="1.2" stroke-linejoin="round" stroke-linecap="round"/>
    `;

    // Subtitle: period + change %
    const firstDate  = history_lst[0].date;
    const lastDate   = history_lst[history_lst.length - 1].date;
    const changePct  = ((lastClose - firstClose) / firstClose * 100);
    const changeStr  = (changePct >= 0 ? '+' : '') + changePct.toFixed(1) + '%';
    subtitle.textContent = `${firstDate.slice(0, 7)} → ${lastDate.slice(0, 7)}  ${changeStr}`;
    subtitle.style.color = isUp ? '#4caf7d' : '#e05c5c';

    // ── Interactive crosshair + tooltip ──────────────────────────────
    const wrap  = document.getElementById('panel-chart-wrap');
    const tip   = document.getElementById('panel-chart-tooltip');
    const cross = document.getElementById('panel-chart-crosshair');

    // Remove previous listeners by cloning the element
    const newWrap = wrap.cloneNode(true);
    wrap.parentNode.replaceChild(newWrap, wrap);

    // Re-grab references after clone
    const wrapEl  = document.getElementById('panel-chart-wrap');
    const tipEl   = document.getElementById('panel-chart-tooltip');
    const crossEl = document.getElementById('panel-chart-crosshair');

    wrapEl.addEventListener('mousemove', e => {
        const rect   = wrapEl.getBoundingClientRect();
        const xFrac  = (e.clientX - rect.left) / rect.width;
        const idx    = Math.round(xFrac * (n - 1));
        const cIdx   = Math.max(0, Math.min(n - 1, idx));
        const entry  = history_lst[cIdx];
        const xPx    = xFrac * rect.width;

        crossEl.style.left    = xPx.toFixed(1) + 'px';
        crossEl.style.display = 'block';

        tipEl.textContent = `${entry.date}  $${entry.close.toFixed(2)}`;

        // Position tooltip: flip to left side if near right edge
        const tipW   = 140;
        const tipLeft = xPx + 8 + tipW > rect.width ? xPx - tipW - 6 : xPx + 8;
        tipEl.style.left    = tipLeft.toFixed(1) + 'px';
        tipEl.style.top     = '4px';
        tipEl.style.display = 'block';
    });

    wrapEl.addEventListener('mouseleave', () => {
        tipEl.style.display   = 'none';
        crossEl.style.display = 'none';
    });
}

// ── Keyboard + resize ─────────────────────────────────────────────
document.addEventListener('keydown', e => { if (e.key === 'Escape' && activeTicker) closePanel(); });
window.addEventListener('resize',    () => { if (activeTicker) updateSpacer(); });
window.addEventListener('load', updateSpacer);
</script>
"""

# ---------------------------------------------------------------------------
# HTML injection
# ---------------------------------------------------------------------------

def inject_panel(html_content, ticker_buttons_html, company_data_js, full_sale_set, history_url):
    """Inject CSS, panel HTML, and JS into the existing trades HTML."""
    html_content = html_content.replace("</style>", PANEL_CSS + "\n</style>", 1)

    panel_html = PANEL_HTML.replace("{TICKER_BUTTONS}", ticker_buttons_html)

    full_sale_list_js = json.dumps(sorted(full_sale_set))
    history_url_js    = json.dumps(history_url) if history_url else "null"

    panel_js = (PANEL_JS
                .replace("{COMPANY_DATA_JS}",  company_data_js)
                .replace("{FULL_SALE_SET_JS}", full_sale_list_js)
                .replace("{HISTORY_URL_JS}",   history_url_js))

    html_content = html_content.replace("</body>", panel_html + "\n" + panel_js + "\n</body>", 1)
    return html_content
# end def inject_panel


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    if not os.path.isfile(args.html_file):
        print(f"ERROR: HTML file not found: {args.html_file}", file = sys.stderr)
        sys.exit(1)
    with open(args.html_file, "r", encoding = "utf-8") as f:
        html_content = f.read()

    if not os.path.isfile(args.watchlist_json):
        print(f"ERROR: Watchlist JSON not found: {args.watchlist_json}", file = sys.stderr)
        sys.exit(1)
    with open(args.watchlist_json, "r", encoding = "utf-8") as f:
        watchlist_lst = json.load(f)

    html_tickers_set      = extract_tickers_from_html(html_content)
    full_sale_set         = extract_full_sale_tickers(html_content)
    watchlist_tickers_set = {e["ticker"] for e in watchlist_lst if e.get("ticker")}
    unmatched_set         = html_tickers_set - watchlist_tickers_set

    print(f"Tickers found in HTML:  {sorted(html_tickers_set)}")
    print(f"Full-sale (closed):     {sorted(full_sale_set)}")
    print(f"Matched with watchlist: {sorted(html_tickers_set & watchlist_tickers_set)}")
    if unmatched_set:
        print(f"WARNING: no watchlist entry for: {sorted(unmatched_set)} — stub entries will be used.")
    if args.history_url:
        print(f"History URL: {args.history_url}")
    else:
        print("WARNING: --history-url not provided — chart will show 'Chart URL not configured'.")

    combined_watchlist_lst = list(watchlist_lst)
    for t in unmatched_set:
        combined_watchlist_lst.append({
            "ticker":               t,
            "company_name":         t,
            "company_description":  placeholder(PLACEHOLDER_DESCRIPTIONS_LST, t),
            "target_price_min":     None,
            "target_price_max":     None,
            "investment_risk":      None,
            "last_report_comment":  placeholder(PLACEHOLDER_COMMENTS_LST, t),
        })

    company_data_js     = build_company_data_js(combined_watchlist_lst, html_tickers_set)
    ticker_buttons_html = build_ticker_tabs_html(combined_watchlist_lst, html_tickers_set, full_sale_set)
    modified_html       = inject_panel(html_content, ticker_buttons_html, company_data_js, full_sale_set, args.history_url or "")

    if args.output:
        out_path = args.output
    else:
        base, ext = os.path.splitext(args.html_file)
        out_path  = base + "_with_panel" + ext

    with open(out_path, "w", encoding = "utf-8") as f:
        f.write(modified_html)

    print(f"Output written to: {out_path}")
# end def main


if __name__ == "__main__":
    main()
