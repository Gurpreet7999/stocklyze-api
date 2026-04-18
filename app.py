"""
Stocklyze — Railway backend entry point
FastAPI + CORS + live Yahoo Finance + quant analysis engine
Fundamentals: Yahoo Finance (primary) → Screener.in (fallback)
"""

import os
import re
import sys
import math
from datetime import datetime

import httpx
import numpy as np
import requests as sync_requests
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.append(os.path.dirname(__file__))
import _utils as u


# ── Numpy → native Python sanitiser ─────────────────────────
def convert_numpy(obj):
    if isinstance(obj, dict):
        return {k: convert_numpy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_numpy(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


# ── Screener.in scraper ──────────────────────────────────────
_SCREENER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def scrape_screener(symbol: str) -> dict:
    """
    Scrape key fundamental ratios from Screener.in.
    Returns an empty dict on any failure — caller must treat this as optional.
    All returned values are raw strings; use clean_number() before storing.
    """
    try:
        url = f"https://www.screener.in/company/{symbol}/consolidated/"
        r   = sync_requests.get(url, headers=_SCREENER_HEADERS, timeout=12)
        if r.status_code == 404:
            url = f"https://www.screener.in/company/{symbol}/"
            r   = sync_requests.get(url, headers=_SCREENER_HEADERS, timeout=10)
        if r.status_code != 200:
            return {}

        soup = BeautifulSoup(r.text, "html.parser")

        def _get(label: str):
            try:
                for li in soup.find_all("li"):
                    name_span = li.find("span", class_="name")
                    val_span  = li.find("span", class_="number")
                    if name_span and val_span:
                        if label.lower() in name_span.get_text(strip=True).lower():
                            return val_span.get_text(strip=True)
                td = soup.find("td", string=re.compile(label, re.IGNORECASE))
                if td:
                    sibling = td.find_next_sibling("td")
                    if sibling:
                        return sibling.get_text(strip=True)
            except Exception:
                pass
            return None

        return {
            "pe":  _get("Stock P/E"),
            "mc":  _get("Market Cap"),
            "roe": _get("Return on equity"),
            "de":  _get("Debt to equity"),
            "pm":  _get("Net profit"),
            "rg":  _get("Sales growth"),
            "pb":  _get("Price to Book"),
        }

    except Exception:
        return {}


def clean_number(val) -> float:
    """Convert a Screener.in display value to a plain float."""
    if not val:
        return 0.0
    val = (
        str(val)
        .replace(",", "")
        .replace("Cr", "")
        .replace("%", "")
        .replace("₹", "")
        .replace("Rs.", "")
        .strip()
    )
    val = re.sub(r"[^\d.\-].*$", "", val)
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _apply_screener_fallback(fd: dict, symbol: str) -> tuple:
    """
    Fetch Screener.in data and fill ONLY fields that are missing/zero in fd.
    Returns (updated_fd, data_source_label).
    data_source is "mixed" only when at least one field was actually filled
    from Screener; "yahoo" when Yahoo had everything.
    """
    scraped = scrape_screener(symbol)
    if not scraped:
        return fd, "yahoo"

    filled = False

    if not fd.get("pe"):
        v = clean_number(scraped.get("pe"))
        if v > 0:
            fd["pe"] = v; filled = True

    if not fd.get("mc"):
        v = clean_number(scraped.get("mc"))
        if v > 0:
            fd["mc"] = v * 1e7; filled = True  # Screener Cr -> rupees

    if not fd.get("return_on_equity"):
        v = clean_number(scraped.get("roe"))
        if v != 0:
            fd["return_on_equity"] = v / 100.0; filled = True

    if not fd.get("profit_margins"):
        v = clean_number(scraped.get("pm"))
        if v != 0:
            fd["profit_margins"] = v / 100.0; filled = True

    if not fd.get("revenue_growth"):
        v = clean_number(scraped.get("rg"))
        if v != 0:
            fd["revenue_growth"] = v / 100.0; filled = True

    if not fd.get("debt_to_equity"):
        v = clean_number(scraped.get("de"))
        if v != 0:
            fd["debt_to_equity"] = v * 100.0; filled = True

    if not fd.get("pb"):
        v = clean_number(scraped.get("pb"))
        if v > 0:
            fd["pb"] = v; filled = True

    return fd, ("mixed" if filled else "yahoo")


# ── App ───────────────────────────────────────────────────────
app = FastAPI(title="Stocklyze API", version="6.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

YF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://finance.yahoo.com/",
}


# ── /api/health ──────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {
        "status":  "ok",
        "service": "Stocklyze API v6.1",
        "groq":    bool(os.environ.get("GROQ_API_KEY", "")),
        "ts":      datetime.utcnow().isoformat() + "Z",
    }


# ── /api/search ──────────────────────────────────────────────
@app.get("/api/search")
async def search(q: str = ""):
    q = q.strip()
    if len(q) < 2:
        return []

    results = []
    try:
        url = (
            "https://query2.finance.yahoo.com/v1/finance/search"
            f"?q={q}&newsCount=0&quotesCount=12&enableFuzzyQuery=true"
        )
        async with httpx.AsyncClient(headers=YF_HEADERS, timeout=8) as client:
            r = await client.get(url)
            if r.status_code == 200:
                for qt in r.json().get("quotes", []):
                    sym = qt.get("symbol", "")
                    if not (sym.endswith(".NS") or sym.endswith(".BO")):
                        continue
                    clean = sym.replace(".NS", "").replace(".BO", "")
                    results.append({
                        "sym":      clean,
                        "name":     qt.get("longname") or qt.get("shortname") or clean,
                        "exchange": "NSE" if sym.endswith(".NS") else "BSE",
                        "sector":   qt.get("industry", ""),
                    })
    except Exception:
        pass

    POPULAR = [
        "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "BHARTIARTL", "SBIN",
        "INFY", "HINDUNILVR", "ITC", "LT", "BAJFINANCE", "KOTAKBANK",
        "AXISBANK", "MARUTI", "SUNPHARMA", "TATAMOTORS", "NTPC", "TITAN",
        "POWERGRID", "WIPRO", "ULTRACEMCO", "HCLTECH", "NESTLEIND", "TECHM",
        "ADANIENT", "COALINDIA", "ONGC", "JSWSTEEL", "TATASTEEL", "BAJAJFINSV",
        "ZOMATO", "HAL", "BEL", "IRCTC", "RVNL", "RECLTD", "PFC",
        "M&M", "TVSMOTOR", "BAJAJ-AUTO", "PAYTM", "NYKAA", "DMART",
    ]
    ql = q.lower()
    for sym in POPULAR:
        if ql in sym.lower() and not any(r["sym"] == sym for r in results):
            results.append({"sym": sym, "name": sym, "exchange": "NSE", "sector": ""})

    return results[:12]


# ── /api/indices ─────────────────────────────────────────────
@app.get("/api/indices")
async def indices():
    INDEX_SYMS = [
        ("^NSEI",    "NIFTY 50"),
        ("^BSESN",   "SENSEX"),
        ("^NSEBANK", "BANK NIFTY"),
    ]
    out = []
    try:
        symbols_str = ",".join(s for s, _ in INDEX_SYMS)
        url = (
            "https://query1.finance.yahoo.com/v7/finance/quote"
            f"?symbols={symbols_str}"
            "&fields=regularMarketPrice,regularMarketChange,regularMarketChangePercent"
        )
        async with httpx.AsyncClient(headers=YF_HEADERS, timeout=8) as client:
            r = await client.get(url)
            if r.status_code == 200:
                quotes   = r.json().get("quoteResponse", {}).get("result", [])
                name_map = {s: n for s, n in INDEX_SYMS}
                for qt in quotes:
                    sym = qt.get("symbol", "")
                    out.append({
                        "name":   name_map.get(sym, sym),
                        "price":  round(qt.get("regularMarketPrice",         0), 2),
                        "change": round(qt.get("regularMarketChange",        0), 2),
                        "pct":    round(qt.get("regularMarketChangePercent", 0), 2),
                    })
    except Exception:
        pass

    if not out:
        out = [
            {"name": "NIFTY 50",   "price": 22450, "change": 0, "pct": 0},
            {"name": "SENSEX",     "price": 73900, "change": 0, "pct": 0},
            {"name": "BANK NIFTY", "price": 48200, "change": 0, "pct": 0},
        ]
    return out


# ── /api/analyse ─────────────────────────────────────────────
@app.get("/api/analyse")
async def analyse(sym: str = ""):
    sym = sym.upper().strip()
    if not sym:
        return {"error": "symbol required"}

    # ── Step 1: Fetch OHLCV (1-year daily) ───────────────────
    ohlcv_data  = None
    meta        = {}
    used_suffix = ".NS"

    for suffix in [".NS", ".BO"]:
        ticker = sym + suffix
        url    = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            "?interval=1d&range=1y&includePrePost=false"
        )
        try:
            async with httpx.AsyncClient(headers=YF_HEADERS, timeout=15) as client:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                data   = r.json()
                result = data.get("chart", {}).get("result")
                if not result:
                    continue
                ohlcv_data  = result[0]
                meta        = ohlcv_data.get("meta", {})
                used_suffix = suffix
                break
        except Exception:
            continue

    if ohlcv_data is None:
        return {
            "error": (
                f"Could not fetch data for '{sym}'. "
                "Verify the NSE ticker symbol. "
                "Examples: RELIANCE, TCS, HDFCBANK, ZOMATO"
            )
        }

    # ── Step 2: Build OHLCV series ────────────────────────────
    timestamps = ohlcv_data.get("timestamp", [])
    quote      = ohlcv_data.get("indicators", {}).get("quote", [{}])[0]
    opens  = quote.get("open",   [])
    highs  = quote.get("high",   [])
    lows   = quote.get("low",    [])
    closes = quote.get("close",  [])
    vols   = quote.get("volume", [])

    series = []
    for i, ts in enumerate(timestamps):
        try:
            c = closes[i]
            if c is None or c <= 0:
                continue
            series.append({
                "time":   datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"),
                "open":   round(float(opens[i] or c), 2),
                "high":   round(float(highs[i] or c), 2),
                "low":    round(float(lows[i]  or c), 2),
                "close":  round(float(c),             2),
                "volume": int(vols[i] or 0),
            })
        except Exception:
            continue

    if not series:
        return {"error": f"No valid price data returned for '{sym}'."}

    # ── Step 3: Fetch fundamentals (Yahoo primary) ────────────
    fd = {
        "name": meta.get("longName") or meta.get("shortName") or sym,
        "sector": "", "industry": "", "description": "", "exchange": "",
        "mc": 0, "pe": 0, "pb": 0, "eps": 0, "beta": 1.0,
        "div_yield": 0, "revenue_growth": 0, "earnings_growth": 0,
        "profit_margins": 0, "return_on_equity": 0, "return_on_assets": 0,
        "op_margins": 0, "debt_to_equity": 0,
        "held_institutions": 0, "held_insiders": 0,
        "target_price": 0, "analyst_count": 0,
    }
    fundamentals_available = False
    data_source            = "yahoo"

    for qs_ver in ["v11", "v10"]:
        try:
            modules = "financialData,defaultKeyStatistics,summaryDetail,assetProfile,price"
            qs_url  = (
                f"https://query1.finance.yahoo.com/{qs_ver}/finance/quoteSummary"
                f"/{sym}{used_suffix}?modules={modules}&corsDomain=finance.yahoo.com"
            )
            async with httpx.AsyncClient(headers=YF_HEADERS, timeout=12) as client:
                rs = await client.get(qs_url)
                if rs.status_code == 200:
                    qs_result = rs.json().get("quoteSummary", {}).get("result", [])
                    if qs_result:
                        parsed = u._parse_fundamentals(qs_result[0])
                        fd.update(parsed)
                        key_fields = [
                            parsed.get("pe", 0), parsed.get("mc", 0),
                            parsed.get("revenue_growth", 0), parsed.get("profit_margins", 0),
                        ]
                        fundamentals_available = (
                            sum(1 for v in key_fields if v and float(v) != 0.0) >= 2
                        )
                        break
        except Exception:
            continue

    # ── Step 3b: Screener.in fallback ─────────────────────────
    # Fills ONLY fields that are still zero after Yahoo.
    # If Yahoo returned full data, all conditions are false → no-op.
    # scrape_screener() uses the synchronous `requests` library and runs
    # in FastAPI's default thread pool — acceptable for a single analysis call.
    try:
        fd, data_source = _apply_screener_fallback(fd, sym)

        # Re-evaluate after fallback enrichment
        if not fundamentals_available:
            enriched_fields = [
                fd.get("pe", 0), fd.get("mc", 0),
                fd.get("revenue_growth", 0), fd.get("profit_margins", 0),
            ]
            fundamentals_available = (
                sum(1 for v in enriched_fields if v and float(v) != 0.0) >= 2
            )
    except Exception:
        pass  # fallback failure is non-fatal

    # ── Step 4: Price fields ──────────────────────────────────
    price  = float(meta.get("regularMarketPrice", series[-1]["close"]))
    prev   = float(meta.get("chartPreviousClose", price))
    change = round(price - prev, 2)
    pct    = round((price - prev) / prev * 100, 2) if prev else 0.0

    h52 = float(meta.get("fiftyTwoWeekHigh", price))
    l52 = float(meta.get("fiftyTwoWeekLow",  price))
    mc  = float(fd.get("mc", 0) or 0)

    def fmt_cap(v):
        if not v:
            return "N/A"
        v = float(v)
        if v >= 1e12: return f"₹{v/1e12:.2f}L Cr"
        if v >= 1e9:  return f"₹{v/1e9:.2f}K Cr"
        if v >= 1e7:  return f"₹{v/1e7:.2f} Cr"
        return f"₹{v:,.0f}"

    # ── Step 5: Run quant analysis engine ────────────────────
    analysis = {}
    if len(series) >= 20:
        try:
            analysis = u.analyse_stock(fd, series, h52=h52, l52=l52)
        except Exception:
            pass

    # Engine re-assesses fundamentals internally — use its result
    fundamentals_available = analysis.get("fd_available", fundamentals_available)

    # ── Step 6: Groq AI summary (optional) ───────────────────
    groq_text = None
    groq_key  = os.environ.get("GROQ_API_KEY", "")
    if groq_key and analysis:
        try:
            groq_payload = {
                **fd,
                "sym":          sym,
                "price":        price,
                "h52":          h52,
                "l52":          l52,
                "mc_fmt":       fmt_cap(mc),
                "rg":           round(fd.get("revenue_growth",   0) * 100, 1),
                "pm":           round(fd.get("profit_margins",   0) * 100, 1),
                "roe":          round(fd.get("return_on_equity", 0) * 100, 1),
                "inst":         round(fd.get("held_institutions",0) * 100, 1),
                "beta":         fd.get("beta", 1.0),
                "spe":          u.SECTOR_PE.get(fd.get("sector", ""), 22),
                "pe":           fd.get("pe", 0),
                "trend":        analysis.get("trend",        "—"),
                "momentum":     analysis.get("momentum",     "—"),
                "confidence":   analysis.get("confidence",   "—"),
                "action_tag":   analysis.get("action_tag",   "—"),
                "key_insights": analysis.get("key_insights", []),
                "risk_flags":   analysis.get("risk_flags",   []),
            }
            groq_text = u.groq_analysis(groq_payload)
        except Exception:
            pass

    # ── Step 7: Assemble final response ──────────────────────
    return convert_numpy({
        # ── Identity ──────────────────────────────────────────
        "sym":         sym,
        "name":        fd.get("name") or sym,
        "sector":      fd.get("sector", ""),
        "industry":    fd.get("industry", ""),
        "description": fd.get("description", ""),
        "exchange":    "NSE" if used_suffix == ".NS" else "BSE",

        # ── Price ─────────────────────────────────────────────
        "price":  round(price, 2),
        "change": change,
        "pct":    pct,
        "open":   round(float(meta.get("regularMarketOpen",    price)), 2),
        "high":   round(float(meta.get("regularMarketDayHigh", price)), 2),
        "low":    round(float(meta.get("regularMarketDayLow",  price)), 2),
        "vol":    int(meta.get("regularMarketVolume", 0)),
        "h52":    round(h52, 2),
        "l52":    round(l52, 2),
        "ma50":   round(float(meta.get("fiftyDayAverage",      0)), 2),
        "ma200":  round(float(meta.get("twoHundredDayAverage", 0)), 2),

        # ── Fundamentals ──────────────────────────────────────
        "mc":           mc,
        "mc_fmt":       fmt_cap(mc),
        "pe":           round(float(fd.get("pe",  0)), 2),
        "spe":          float(u.SECTOR_PE.get(fd.get("sector", ""), 22)),
        "pb":           round(float(fd.get("pb",  0)), 2),
        "eps":          round(float(fd.get("eps", 0)), 2),
        "beta":         round(float(fd.get("beta", 1.0)), 2),
        "div_yield":    round(float(fd.get("div_yield",        0)) * 100, 2),
        "rg":           round(float(fd.get("revenue_growth",   0)) * 100, 1),
        "eg":           round(float(fd.get("earnings_growth",  0)) * 100, 1),
        "pm":           round(float(fd.get("profit_margins",   0)) * 100, 1),
        "op_margin":    round(float(fd.get("op_margins",       0)) * 100, 1),
        "roe":          round(float(fd.get("return_on_equity", 0)) * 100, 1),
        "roa":          round(float(fd.get("return_on_assets", 0)) * 100, 1),
        "de":           round(float(fd.get("debt_to_equity",   0)) / 100, 3),
        "inst":         round(float(fd.get("held_institutions",0)) * 100, 1),
        "insiders":     round(float(fd.get("held_insiders",    0)) * 100, 1),
        "target_price": round(float(fd.get("target_price",     0)), 2),
        "analyst_count":int(fd.get("analyst_count", 0)),
        "fundamentals_available": bool(fundamentals_available),
        "data_source":            data_source,

        # ── Chart series ──────────────────────────────────────
        "series": series,

        # ── New structured analysis output ────────────────────
        "trend":               analysis.get("trend",               "Insufficient Data"),
        "momentum":            analysis.get("momentum",            "Insufficient Data"),
        "volatility_position": analysis.get("volatility_position", "—"),
        "confidence":          analysis.get("confidence",          "Low (0%)"),
        "confidence_pct":      float(analysis.get("confidence_pct", 0)),
        "action_tag":          analysis.get("action_tag",          "Watchlist"),
        "key_insights":        analysis.get("key_insights",        []),
        "risk_flags":          analysis.get("risk_flags",          []),
        "analysis_summary":    analysis.get("analysis_summary",    ""),
        "fd_quality":          analysis.get("fd_quality",          "Data Unavailable"),
        "momentum_signals":    analysis.get("momentum_signals",    []),
        "atr_pct":             float(analysis.get("atr_pct",        0)),
        "pos_52w_pct":         float(analysis.get("pos_52w_pct",    0)),

        # ── Legacy fields (frontend compatibility) ─────────────
        "score":        int(analysis.get("score",     0)),
        "verdict":      analysis.get("verdict",   "HOLD"),
        "breakdown":    analysis.get("breakdown",  {"bh": 0, "val": 0, "tech": 0, "inst": 0}),
        "findings":     analysis.get("findings",   []),
        "forecasts":    analysis.get("forecasts",  []),

        # ── Technical indicators (direct, for UI display) ──────
        "rsi":          float(analysis.get("rsi",    50)),
        "macd":         analysis.get("macd",         {"macd": 0, "signal": 0, "hist": 0}),
        "adx":          float(analysis.get("adx",    25)),
        "bb":           analysis.get("bb",           {"upper": 0, "mid": 0, "lower": 0, "pct": 50, "bw": 0}),
        "stoch":        analysis.get("stoch",        {"k": 50, "d": 50}),
        "ema20":        float(analysis.get("ema20",  0)),
        "ema50":        float(analysis.get("ema50",  0)),
        "ema200":       float(analysis.get("ema200", 0)),
        "ema_signal":   analysis.get("ema_signal",   "Neutral"),
        "rsi_signal":   analysis.get("rsi_signal",   "Neutral"),
        "macd_signal":  analysis.get("macd_signal",  "Neutral"),
        "adx_strength": analysis.get("adx_strength", "Moderate"),
        "stoch_signal": analysis.get("stoch_signal", "Neutral"),
        "above_50":     bool(analysis.get("above_50",     False)),
        "above_200":    bool(analysis.get("above_200",    False)),
        "golden_cross": bool(analysis.get("golden_cross", False)),

        # ── AI ────────────────────────────────────────────────
        "groq_text":    groq_text,

        # ── Metadata ──────────────────────────────────────────
        "analysed_at":  datetime.utcnow().isoformat() + "Z",
    })
