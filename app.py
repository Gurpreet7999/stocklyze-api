"""
Stocklyze — Railway backend entry point
FastAPI + CORS + live Yahoo Finance data
"""

import os
import math
import sys
from datetime import datetime

import httpx
import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ── Import shared scoring utilities ─────────────────────────
sys.path.append(os.path.dirname(__file__))
import _utils as u

# ── Numpy → Python type sanitiser ───────────────────────────
def convert_numpy(obj):
    """
    Recursively convert all numpy scalar/bool types to native Python.
    FastAPI's jsonable_encoder cannot serialise np.float64, np.bool_, etc.
    Apply to the entire response dict before returning.
    """
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


# ── App setup ────────────────────────────────────────────────
app = FastAPI(title="Stocklyze API", version="5.0")

# CRITICAL FIX: CORSMiddleware was completely missing before.
# Without this, the browser blocks every request from Vercel.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten to your Vercel URL after confirming it works
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

# Yahoo Finance request headers — mimic a real browser
YF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com/",
}


# ── /api/health ──────────────────────────────────────────────
@app.get("/api/health")
def health():
    """Quick liveness check — ping this from frontend on load
    to wake Railway if it went idle."""
    return {
        "status": "ok",
        "service": "Stocklyze API v5",
        "groq": bool(os.environ.get("GROQ_API_KEY", "")),
        "ts": datetime.utcnow().isoformat() + "Z",
    }


# ── /api/search ──────────────────────────────────────────────
@app.get("/api/search")
async def search(q: str = ""):
    """
    Live stock search via Yahoo Finance autocomplete.
    Returns NSE/BSE tickers only.
    """
    q = q.strip()
    if len(q) < 2:
        return []

    results = []
    try:
        url = (
            f"https://query2.finance.yahoo.com/v1/finance/search"
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

    # Local fuzzy fallback so search never returns empty for popular tickers
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
            results.append({
                "sym":      sym,
                "name":     sym,
                "exchange": "NSE",
                "sector":   "",
            })

    return results[:12]


# ── /api/indices ─────────────────────────────────────────────
@app.get("/api/indices")
async def indices():
    """
    Live NIFTY 50, SENSEX, BANK NIFTY prices.
    Falls back to static values if Yahoo Finance is unreachable.
    """
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
                quotes = r.json().get("quoteResponse", {}).get("result", [])
                name_map = {s: n for s, n in INDEX_SYMS}
                for qt in quotes:
                    sym = qt.get("symbol", "")
                    out.append({
                        "name":   name_map.get(sym, sym),
                        "price":  round(qt.get("regularMarketPrice", 0), 2),
                        "change": round(qt.get("regularMarketChange", 0), 2),
                        "pct":    round(qt.get("regularMarketChangePercent", 0), 2),
                    })
    except Exception:
        pass

    if not out:
        # Static fallback — ticker visible but stale
        out = [
            {"name": "NIFTY 50",   "price": 22450, "change": 0, "pct": 0},
            {"name": "SENSEX",     "price": 73900, "change": 0, "pct": 0},
            {"name": "BANK NIFTY", "price": 48200, "change": 0, "pct": 0},
        ]
    return out


# ── /api/analyse ─────────────────────────────────────────────
@app.get("/api/analyse")
async def analyse(sym: str = ""):
    """
    Full stock analysis:
    1. Fetch 1-year OHLCV history from Yahoo Finance
    2. Fetch fundamentals via quoteSummary
    3. Run 4-layer scoring from _utils.score_stock()
    4. Optionally run Groq AI summary
    Returns everything the frontend needs in one response.
    """
    sym = sym.upper().strip()
    if not sym:
        return {"error": "symbol required"}

    ohlcv_data = None
    meta = {}
    used_suffix = ".NS"

    # Try NSE first, then BSE
    for suffix in [".NS", ".BO"]:
        ticker = sym + suffix
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            "?interval=1d&range=1y&includePrePost=false"
        )
        try:
            async with httpx.AsyncClient(headers=YF_HEADERS, timeout=15) as client:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                data = r.json()
                result = data.get("chart", {}).get("result")
                if not result:
                    continue
                ohlcv_data = result[0]
                meta = ohlcv_data.get("meta", {})
                used_suffix = suffix
                break
        except Exception:
            continue

    if ohlcv_data is None:
        return {
            "error": (
                f"Could not fetch data for '{sym}'. "
                "Check the NSE ticker symbol and try again. "
                "Examples: RELIANCE, TCS, HDFCBANK, ZOMATO"
            )
        }

    # ── Build OHLCV series ────────────────────────────────────
    timestamps = ohlcv_data.get("timestamp", [])
    quote = ohlcv_data.get("indicators", {}).get("quote", [{}])[0]
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
                "open":   round(float(opens[i]  or c), 2),
                "high":   round(float(highs[i]  or c), 2),
                "low":    round(float(lows[i]   or c), 2),
                "close":  round(float(c),             2),
                "volume": int(vols[i] or 0),
            })
        except Exception:
            continue

    if not series:
        return {"error": f"No valid price data returned for '{sym}'."}

    # ── Fetch fundamentals via quoteSummary ───────────────────
    # Use v11 — more reliable than v10 for Indian NSE/BSE tickers.
    # We track whether fundamentals actually populated so the frontend
    # can show a "data unavailable" notice rather than showing zeroes.
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

    for qs_ver in ["v11", "v10"]:
        try:
            modules = (
                "financialData,defaultKeyStatistics,"
                "summaryDetail,assetProfile,price"
            )
            qs_url = (
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
                        # Check if we got meaningful data
                        key_fields = [
                            parsed.get("pe", 0), parsed.get("mc", 0),
                            parsed.get("revenue_growth", 0), parsed.get("profit_margins", 0),
                        ]
                        fundamentals_available = sum(1 for v in key_fields if v and float(v) != 0.0) >= 2
                        break  # success — stop trying versions
        except Exception:
            continue

    # ── Price fields from meta ───────────────────────────────
    price = meta.get("regularMarketPrice", series[-1]["close"])
    prev  = meta.get("chartPreviousClose", price)
    change = round(price - prev, 2)
    pct    = round((price - prev) / prev * 100, 2) if prev else 0.0

    def fmt_cap(v):
        if not v:
            return "N/A"
        v = float(v)
        if v >= 1e12: return f"₹{v/1e12:.2f}L Cr"
        if v >= 1e9:  return f"₹{v/1e9:.2f}K Cr"
        if v >= 1e7:  return f"₹{v/1e7:.2f} Cr"
        return f"₹{v:,.0f}"

    mc = fd.get("mc", 0) or 0

    # ── Run 4-layer scoring ──────────────────────────────────
    scored = {}
    if len(series) >= 20:
        try:
            scored = u.score_stock(fd, series)
        except Exception:
            pass

    # ── Groq AI summary (optional — only if key is set) ──────
    groq_text = None
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if groq_key and scored:
        try:
            groq_payload = {
                **fd,
                "sym":       sym,
                "price":     price,
                "h52":       meta.get("fiftyTwoWeekHigh", price),
                "l52":       meta.get("fiftyTwoWeekLow",  price),
                "mc_fmt":    fmt_cap(mc),
                "rg":        round(fd.get("revenue_growth", 0) * 100, 1),
                "pm":        round(fd.get("profit_margins",  0) * 100, 1),
                "roe":       round(fd.get("return_on_equity", 0) * 100, 1),
                "inst":      round(fd.get("held_institutions", 0) * 100, 1),
                "beta":      fd.get("beta", 1.0),
                "rsi":       scored.get("rsi", 50),
                "ema_signal": scored.get("ema_signal", "Neutral"),
                "score":     scored.get("score", 0),
                "verdict":   scored.get("verdict", "HOLD"),
                "findings":  scored.get("findings", []),
                "spe":       u.SECTOR_PE.get(fd.get("sector", ""), 22),
                "pe":        fd.get("pe", 0),
            }
            groq_text = u.groq_analysis(groq_payload)
        except Exception:
            pass

    # ── Assemble final response ──────────────────────────────
    return convert_numpy({
        # Identity
        "sym":       sym,
        "name":      fd.get("name") or sym,
        "sector":    fd.get("sector", ""),
        "industry":  fd.get("industry", ""),
        "description": fd.get("description", ""),
        "exchange":  "NSE" if used_suffix == ".NS" else "BSE",

        # Price
        "price":     round(price, 2),
        "change":    change,
        "pct":       pct,
        "open":      round(meta.get("regularMarketOpen",    price), 2),
        "high":      round(meta.get("regularMarketDayHigh", price), 2),
        "low":       round(meta.get("regularMarketDayLow",  price), 2),
        "vol":       meta.get("regularMarketVolume", 0),
        "h52":       round(meta.get("fiftyTwoWeekHigh", price), 2),
        "l52":       round(meta.get("fiftyTwoWeekLow",  price), 2),
        "ma50":      round(meta.get("fiftyDayAverage",           0), 2),
        "ma200":     round(meta.get("twoHundredDayAverage",      0), 2),

        # Fundamentals
        "mc":        mc,
        "mc_fmt":    fmt_cap(mc),
        "pe":        round(fd.get("pe", 0), 2),
        "spe":       u.SECTOR_PE.get(fd.get("sector", ""), 22),
        "pb":        round(fd.get("pb", 0), 2),
        "eps":       round(fd.get("eps", 0), 2),
        "beta":      round(fd.get("beta", 1.0), 2),
        "div_yield": round(fd.get("div_yield", 0) * 100, 2),
        "rg":        round(fd.get("revenue_growth",   0) * 100, 1),
        "eg":        round(fd.get("earnings_growth",  0) * 100, 1),
        "pm":        round(fd.get("profit_margins",   0) * 100, 1),
        "op_margin": round(fd.get("op_margins",       0) * 100, 1),
        "roe":       round(fd.get("return_on_equity", 0) * 100, 1),
        "roa":       round(fd.get("return_on_assets", 0) * 100, 1),
        "de":        round(fd.get("debt_to_equity", 0) / 100, 3),
        "inst":      round(fd.get("held_institutions", 0) * 100, 1),
        "insiders":  round(fd.get("held_insiders",     0) * 100, 1),
        "target_price":  round(fd.get("target_price", 0), 2),
        "analyst_count": fd.get("analyst_count", 0),

        # Chart data
        "series":    series,

        # Scoring (from _utils.score_stock)
        "score":     scored.get("score",     0),
        "verdict":   scored.get("verdict",   "HOLD"),
        "breakdown": scored.get("breakdown", {"bh": 0, "val": 0, "tech": 0, "inst": 0}),
        "findings":  scored.get("findings",  []),
        "forecasts": scored.get("forecasts", []),

        # Technicals
        "rsi":          scored.get("rsi",          50),
        "macd":         scored.get("macd",          {"macd": 0, "signal": 0, "hist": 0}),
        "adx":          scored.get("adx",           25),
        "bb":           scored.get("bb",            {"upper": 0, "mid": 0, "lower": 0, "pct": 50, "bw": 0}),
        "stoch":        scored.get("stoch",         {"k": 50, "d": 50}),
        "ema20":        scored.get("ema20",         0),
        "ema50":        scored.get("ema50",         0),
        "ema200":       scored.get("ema200",        0),
        "ema_signal":   scored.get("ema_signal",    "Neutral"),
        "rsi_signal":   scored.get("rsi_signal",    "Neutral"),
        "macd_signal":  scored.get("macd_signal",   "Neutral"),
        "adx_strength": scored.get("adx_strength",  "Moderate"),
        "stoch_signal": scored.get("stoch_signal",  "Neutral"),
        "above_50":     scored.get("above_50",      False),
        "above_200":    scored.get("above_200",     False),
        "golden_cross": scored.get("golden_cross",  False),

        # AI
        "groq_text":    groq_text,

        # Metadata
        "analysed_at": datetime.utcnow().isoformat() + "Z",
        "fundamentals_available": fundamentals_available,
    })
