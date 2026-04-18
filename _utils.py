"""
Stocklyze — Shared Analysis Engine
Quant-grade, multi-layer analysis replacing naive scoring system.
All public functions are JSON-safe (native Python types only).
"""

import os
import math
import json
import numpy as np
import requests as req

# ── Groq / LLM config ────────────────────────────────────────
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MDL = "llama-3.3-70b-versatile"

# ── Sector P/E benchmarks (used for valuation context) ───────
SECTOR_PE = {
    "Technology": 25.0, "Financial Services": 18.5, "Consumer Cyclical": 33.0,
    "Consumer Defensive": 40.0, "Energy": 11.0, "Industrials": 22.0,
    "Healthcare": 30.0, "Basic Materials": 14.0, "Communication Services": 20.0,
    "Utilities": 16.0, "Real Estate": 24.0,
}

# ═════════════════════════════════════════════════════════════
#  UTILITIES
# ═════════════════════════════════════════════════════════════

def safe(v, d=0.0):
    """Return float(v) or d if v is NaN/Inf/unconvertible."""
    try:
        f = float(v)
        return d if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return d


def _parse_fundamentals(r):
    """
    Parse Yahoo Finance quoteSummary result dict into a flat
    fundamentals dict. Returns native Python types only.
    """
    fd  = r.get("financialData",        {}) or {}
    ks  = r.get("defaultKeyStatistics", {}) or {}
    sd  = r.get("summaryDetail",        {}) or {}
    ap  = r.get("assetProfile",         {}) or {}
    pr  = r.get("price",                {}) or {}

    def g(d, k):
        v = d.get(k)
        if v is None:
            return 0.0
        if isinstance(v, dict):
            return safe(v.get("raw", 0))
        return safe(v)

    return {
        "name":             pr.get("longName") or pr.get("shortName", ""),
        "sector":           ap.get("sector", ""),
        "industry":         ap.get("industry", ""),
        "description":      (ap.get("longBusinessSummary", "") or "")[:600],
        "exchange":         pr.get("exchangeName", "NSE"),
        "mc":               g(pr, "marketCap"),
        "pe":               g(sd, "trailingPE") or g(ks, "forwardPE"),
        "pb":               g(ks, "priceToBook") or g(sd, "priceToBook"),
        "eps":              g(ks, "trailingEps"),
        "beta":             g(sd, "beta") or g(ks, "beta") or 1.0,
        "div_yield":        g(sd, "dividendYield"),
        "revenue_growth":   g(fd, "revenueGrowth"),
        "earnings_growth":  g(ks, "earningsQuarterlyGrowth"),
        "profit_margins":   g(fd, "profitMargins"),
        "return_on_equity": g(fd, "returnOnEquity"),
        "return_on_assets": g(fd, "returnOnAssets"),
        "op_margins":       g(fd, "operatingMargins"),
        "debt_to_equity":   g(fd, "debtToEquity"),
        "held_institutions":g(ks, "heldPercentInstitutions"),
        "held_insiders":    g(ks, "heldPercentInsiders"),
        "target_price":     g(fd, "targetMeanPrice"),
        "analyst_count":    int(g(ks, "numberOfAnalystOpinions")),
    }


# ═════════════════════════════════════════════════════════════
#  RAW INDICATOR CALCULATORS  (unchanged — numerically correct)
# ═════════════════════════════════════════════════════════════

def calc_rsi(c, n=14):
    """Wilder-smoothed RSI. Returns 50 if insufficient data."""
    if len(c) < n + 2:
        return 50.0
    d = np.diff(c.astype(float))
    gains  = np.where(d > 0, d, 0.0)
    losses = np.where(d < 0, -d, 0.0)
    ag, al = gains[:n].mean(), losses[:n].mean()
    for i in range(n, len(d)):
        ag = (ag * (n - 1) + gains[i])  / n
        al = (al * (n - 1) + losses[i]) / n
    rsi = 100 - (100 / (1 + ag / al)) if al > 1e-10 else 100.0
    return round(float(rsi), 2)


def calc_ema(c, n):
    """Exponential moving average over array c with period n."""
    if len(c) < n:
        return float(c[-1]) if len(c) else 0.0
    k = 2 / (n + 1)
    v = float(np.mean(c[:n]))
    for x in c[n:]:
        v = float(x) * k + v * (1 - k)
    return round(v, 2)


def calc_macd(c):
    """MACD (12,26,9). Returns dict with macd, signal, hist."""
    if len(c) < 35:
        return {"macd": 0.0, "signal": 0.0, "hist": 0.0}

    def ema_arr(arr, n):
        k = 2 / (n + 1)
        v = float(np.mean(arr[:n]))
        out = [v]
        for x in arr[n:]:
            v = float(x) * k + v * (1 - k)
            out.append(v)
        return np.array(out)

    e12 = ema_arr(c, 12)
    e26 = ema_arr(c, 26)
    ml  = e12[-len(e26):] - e26
    sig = ema_arr(ml, 9)
    return {
        "macd":   round(float(ml[-1]), 3),
        "signal": round(float(sig[-1]), 3),
        "hist":   round(float(ml[-1] - sig[-1]), 3),
    }


def calc_adx(h, l, c, n=14):
    """Average Directional Index. Returns 25.0 if insufficient data."""
    if len(c) < n * 2 + 2:
        return 25.0
    tr, dp, dm = [], [], []
    for i in range(1, len(c)):
        tr.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
        u  = h[i] - h[i-1]
        d_ = l[i-1] - l[i]
        dp.append(u  if u > d_ and u > 0 else 0.0)
        dm.append(d_ if d_ > u and d_ > 0 else 0.0)
    tr  = np.array(tr,  dtype=float)
    dp  = np.array(dp,  dtype=float)
    dm_ = np.array(dm,  dtype=float)

    def smooth(a):
        s = [a[:n].sum()]
        for i in range(n, len(a)):
            s.append(s[-1] - s[-1]/n + a[i])
        return np.array(s)

    st  = smooth(tr)
    sd  = smooth(dp)
    sm2 = smooth(dm_)
    dip = 100 * sd  / np.maximum(st, 1e-10)
    dim = 100 * sm2 / np.maximum(st, 1e-10)
    dx  = 100 * np.abs(dip - dim) / np.maximum(dip + dim, 1e-10)
    return round(float(dx[-n:].mean()), 2)


def calc_atr(h, l, c, n=14):
    """Average True Range (absolute value, not %). Returns 0 if insufficient."""
    if len(c) < n + 1:
        return 0.0
    tr = []
    for i in range(1, len(c)):
        tr.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    tr = np.array(tr, dtype=float)
    if len(tr) < n:
        return float(tr.mean())
    atr = tr[:n].mean()
    for i in range(n, len(tr)):
        atr = (atr * (n-1) + tr[i]) / n
    return round(float(atr), 2)


def calc_bb(c, n=20, k=2):
    """Bollinger Bands. Returns band levels and %B position."""
    if len(c) < n:
        v = float(c[-1]) if len(c) else 0.0
        return {"upper": v, "mid": v, "lower": v, "pct": 50.0, "bw": 0.0}
    s   = c[-n:]
    mid = float(s.mean())
    std = float(s.std())
    upper  = mid + k * std
    lower  = mid - k * std
    cur    = float(c[-1])
    pct    = (cur - lower) / (upper - lower) * 100 if (upper - lower) > 0 else 50.0
    bw     = (upper - lower) / mid * 100 if mid > 0 else 0.0
    return {
        "upper": round(upper, 2),
        "mid":   round(mid,   2),
        "lower": round(lower, 2),
        "pct":   round(pct,   1),
        "bw":    round(bw,    2),
    }


def calc_stoch(h, l, c, k=14):
    """Stochastic %K/%D. Returns 50/50 if insufficient data."""
    if len(c) < k:
        return {"k": 50.0, "d": 50.0}
    hh = h[-k:].max()
    ll = l[-k:].min()
    kv = (float(c[-1]) - ll) / (hh - ll) * 100 if (hh - ll) > 0 else 50.0
    return {"k": round(kv, 2), "d": round(kv, 2)}


# ═════════════════════════════════════════════════════════════
#  LAYER 1 — TREND STRUCTURE
#  The single most important filter. Everything else is noise
#  if price is not in an established trend.
# ═════════════════════════════════════════════════════════════

def classify_trend(closes, highs, lows):
    """
    Classify the primary trend using EMA structure + price position.
    Returns:
        trend_label  : str
        trend_score  : int  (0–4, used as multiplier for other layers)
        trend_detail : dict (raw values for frontend display)
    """
    cur    = float(closes[-1])
    ema20  = calc_ema(closes, 20)
    ema50  = calc_ema(closes, 50)
    ema200 = calc_ema(closes, 200) if len(closes) >= 200 else calc_ema(closes, len(closes))

    above_200 = cur > ema200
    above_50  = cur > ema50
    above_20  = cur > ema20
    golden    = ema50 > ema200

    # Higher-high / higher-low structure over last 20 bars
    recent_h = highs[-20:]
    recent_l = lows[-20:]
    hh_count = int(sum(1 for i in range(1, len(recent_h)) if recent_h[i] > recent_h[i-1]))
    hl_count = int(sum(1 for i in range(1, len(recent_l)) if recent_l[i] > recent_l[i-1]))
    upstruc  = (hh_count + hl_count) / (2 * max(len(recent_h)-1, 1))

    # Slope of 50-EMA over last 10 bars
    ema50_arr = np.array([calc_ema(closes[:i+1], min(50, i+1)) for i in range(max(0, len(closes)-10), len(closes))])
    ema50_slope = float(np.polyfit(np.arange(len(ema50_arr)), ema50_arr, 1)[0]) if len(ema50_arr) >= 3 else 0.0
    slope_pct   = ema50_slope / max(cur, 1) * 100  # daily slope as % of price

    # ── Classification rules ──────────────────────────────────
    if above_200 and above_50 and golden and slope_pct > 0.05 and upstruc > 0.55:
        label = "Strong Uptrend"
        score = 4
    elif above_200 and above_50 and slope_pct >= 0:
        label = "Moderate Uptrend"
        score = 3
    elif above_200 and not above_50:
        label = "Weak Uptrend"
        score = 2
    elif not above_200 and above_50:
        label = "Sideways / Mixed"
        score = 1
    elif not above_200 and not above_50 and slope_pct < -0.05:
        label = "Moderate Downtrend"
        score = 0
    else:
        label = "Sideways / Mixed"
        score = 1

    # Strong downtrend override: price far below both EMAs
    dist_from_200 = (cur - ema200) / max(ema200, 1) * 100
    if dist_from_200 < -15 and not above_50:
        label = "Strong Downtrend"
        score = 0

    return {
        "trend":        label,
        "trend_score":  score,
        "ema20":        round(ema20,  2),
        "ema50":        round(ema50,  2),
        "ema200":       round(ema200, 2),
        "above_200":    bool(above_200),
        "above_50":     bool(above_50),
        "golden_cross": bool(golden),
        "slope_pct":    round(slope_pct, 4),
        "upstruc_pct":  round(upstruc * 100, 1),
    }


# ═════════════════════════════════════════════════════════════
#  LAYER 2 — MOMENTUM QUALITY
#  Only register signals when multiple indicators agree.
#  ADX < 20 → market is choppy → suppress momentum claims.
# ═════════════════════════════════════════════════════════════

def classify_momentum(closes, highs, lows, adx):
    """
    Returns:
        momentum_label   : str
        momentum_score   : int (0–3)
        momentum_detail  : dict
        momentum_signals : list[str]  — only confirmed signals
    """
    rsi  = calc_rsi(closes)
    macd = calc_macd(closes)
    hist = macd["hist"]

    # ADX < 20: flat market → do not interpret directional signals
    trending = adx >= 20

    bullish_votes = 0
    bearish_votes = 0
    signals       = []

    # RSI zones
    if rsi >= 55 and rsi <= 72:
        bullish_votes += 1
        signals.append(f"RSI {rsi:.0f} — bullish momentum zone")
    elif rsi < 35:
        bullish_votes += 1
        signals.append(f"RSI {rsi:.0f} — oversold, potential reversal setup")
    elif rsi > 75:
        bearish_votes += 1
        signals.append(f"RSI {rsi:.0f} — overbought, elevated risk of pullback")
    elif rsi < 40:
        bearish_votes += 1
        signals.append(f"RSI {rsi:.0f} — weak momentum, bearish bias")
    # RSI 40–55 → neutral, no vote

    # MACD histogram direction
    if trending:
        if hist > 0:
            bullish_votes += 1
            if hist > abs(macd["signal"]) * 0.1:
                signals.append("MACD histogram positive — bullish momentum accelerating")
            else:
                signals.append("MACD histogram marginally positive")
        else:
            bearish_votes += 1
            signals.append("MACD histogram negative — bearish pressure")
    else:
        signals.append("ADX below 20 — trend too weak to validate MACD signal")

    # MACD line vs signal line
    if trending and macd["macd"] > macd["signal"] and macd["macd"] > 0:
        bullish_votes += 1
        signals.append("MACD above signal line in positive territory — confirmed bullish")
    elif trending and macd["macd"] < macd["signal"] and macd["macd"] < 0:
        bearish_votes += 1
        signals.append("MACD below signal in negative territory — confirmed bearish")

    # ── Classify by agreement ─────────────────────────────────
    net = bullish_votes - bearish_votes
    if not trending:
        label = "Weak / Indeterminate"
        score = 1
    elif bullish_votes >= 2 and bearish_votes == 0:
        label = "Strong Bullish"
        score = 3
    elif net >= 1:
        label = "Mild Bullish"
        score = 2
    elif net <= -2:
        label = "Strong Bearish"
        score = 0
    elif net == -1:
        label = "Mild Bearish"
        score = 1
    else:
        label = "Neutral / Mixed"
        score = 1

    return {
        "momentum":        label,
        "momentum_score":  score,
        "rsi":             round(float(rsi),  2),
        "macd":            macd,
        "adx":             round(float(adx),  2),
        "adx_trending":    bool(trending),
        "signals":         signals,
        "bullish_votes":   bullish_votes,
        "bearish_votes":   bearish_votes,
    }


# ═════════════════════════════════════════════════════════════
#  LAYER 3 — VOLATILITY & POSITION CONTEXT
#  Where is the price relative to its range?
#  Combines 52-week positioning with ATR-based volatility.
# ═════════════════════════════════════════════════════════════

def classify_volatility_position(closes, highs, lows, h52, l52):
    """
    Returns:
        vol_label  : str
        vol_score  : int (0–3)
        vol_detail : dict
    """
    cur = float(closes[-1])
    atr = calc_atr(highs, lows, closes)
    bb  = calc_bb(closes)

    # ATR as % of price (normalised volatility)
    atr_pct = atr / cur * 100 if cur > 0 else 0.0

    # 52-week range positioning
    range_52 = max(h52 - l52, 1.0)
    pos_52   = (cur - l52) / range_52 * 100  # 0=at low, 100=at high
    dist_from_high_pct = (h52 - cur) / h52 * 100 if h52 > 0 else 0.0

    # Bollinger band width (market tension)
    bb_pct = bb["pct"]  # 0=at lower band, 100=at upper band

    # ── Classification ────────────────────────────────────────
    if pos_52 >= 80 and dist_from_high_pct < 5:
        label = "Near 52-Week High"
        score = 2  # Neutral — could be breakout OR exhaustion
    elif pos_52 >= 55:
        label = "Upper Half of Range"
        score = 3
    elif pos_52 >= 35:
        label = "Mid Range"
        score = 2
    elif pos_52 >= 15:
        label = "Lower Half of Range"
        score = 1
    else:
        label = "Near 52-Week Low"
        score = 1  # Neutral — distressed OR opportunity

    # Flag exhausted moves: near high AND overbought BB
    if pos_52 >= 85 and bb_pct >= 85:
        label = "Near High — Possibly Exhausted"
        score = 1

    # Flag base-building: near low AND low volatility (quiet accumulation)
    if pos_52 <= 20 and atr_pct < 1.5:
        label = "Near Low — Low Volatility Base"
        score = 2

    return {
        "volatility_position": label,
        "vol_score":           score,
        "pos_52w_pct":         round(pos_52, 1),
        "dist_from_high_pct":  round(dist_from_high_pct, 1),
        "atr":                 round(atr,     2),
        "atr_pct":             round(atr_pct, 2),
        "bb":                  bb,
    }


# ═════════════════════════════════════════════════════════════
#  LAYER 4 — FUNDAMENTAL QUALITY (OPTIONAL)
#  Do not fake data. Score only what exists.
#  Returns a confidence modifier, not a score.
# ═════════════════════════════════════════════════════════════

def assess_fundamentals(fd):
    """
    Returns:
        fd_available   : bool
        fd_score       : int (0–4, additive confidence bonus)
        fd_insights    : list[str]
        fd_risks       : list[str]
        fd_quality     : str (label)
    """
    key_fields = [
        fd.get("pe", 0), fd.get("mc", 0),
        fd.get("revenue_growth", 0), fd.get("profit_margins", 0),
        fd.get("return_on_equity", 0),
    ]
    populated = sum(1 for v in key_fields if v and abs(float(v)) > 1e-6)
    fd_available = populated >= 2

    if not fd_available:
        return {
            "fd_available":  False,
            "fd_score":      0,
            "fd_insights":   [],
            "fd_risks":      ["Fundamental data not available — analysis is technical-only"],
            "fd_quality":    "Data Unavailable",
        }

    insights = []
    risks    = []
    score    = 0

    rg  = safe(fd.get("revenue_growth",   0)) * 100
    pm  = safe(fd.get("profit_margins",   0)) * 100
    roe = safe(fd.get("return_on_equity", 0)) * 100
    de  = safe(fd.get("debt_to_equity",   0)) / 100
    pe  = safe(fd.get("pe",               0))
    sector = fd.get("sector", "") or ""
    spe = SECTOR_PE.get(sector, 22)

    # Revenue growth
    if rg > 15:
        score += 1
        insights.append(f"Strong revenue growth {rg:.1f}% YoY")
    elif rg > 0:
        insights.append(f"Revenue growth {rg:.1f}% YoY — moderate")
    else:
        risks.append(f"Revenue declining {rg:.1f}% YoY")

    # Profitability
    if pm > 15:
        score += 1
        insights.append(f"Strong net margin {pm:.1f}%")
    elif pm > 5:
        insights.append(f"Adequate net margin {pm:.1f}%")
    elif pm < 0:
        risks.append(f"Negative net margin {pm:.1f}% — loss-making")

    # ROE
    if roe > 18:
        score += 1
        insights.append(f"Excellent ROE {roe:.1f}% — efficient capital use")
    elif roe < 8 and roe != 0:
        risks.append(f"Weak ROE {roe:.1f}%")

    # Debt
    if de < 0.3:
        score += 1
        insights.append(f"Low Debt/Equity {de:.2f} — strong balance sheet")
    elif de > 2.0:
        risks.append(f"High Debt/Equity {de:.2f} — leverage risk")

    # Valuation vs sector
    if 0 < pe < spe * 0.8:
        insights.append(f"Attractive valuation P/E {pe:.1f}x vs sector {spe:.0f}x")
    elif pe > spe * 1.4:
        risks.append(f"Expensive: P/E {pe:.1f}x vs sector avg {spe:.0f}x")

    # Institutional ownership
    inst = safe(fd.get("held_institutions", 0)) * 100
    if inst > 40:
        insights.append(f"High institutional ownership {inst:.1f}%")
    elif inst < 5 and inst > 0:
        risks.append(f"Low institutional interest {inst:.1f}%")

    # Quality label
    if score >= 3:
        quality = "Strong Fundamentals"
    elif score >= 2:
        quality = "Decent Fundamentals"
    elif score >= 1:
        quality = "Mixed Fundamentals"
    else:
        quality = "Weak Fundamentals"

    return {
        "fd_available":  True,
        "fd_score":      score,
        "fd_insights":   insights,
        "fd_risks":      risks,
        "fd_quality":    quality,
    }


# ═════════════════════════════════════════════════════════════
#  MASTER ENGINE — analyse_stock()
#  Replaces score_stock(). Combines all 4 layers with
#  multi-confirmation logic. Returns structured analyst output.
# ═════════════════════════════════════════════════════════════

def analyse_stock(fd, series, h52=0, l52=0):
    """
    Main analysis function.

    Args:
        fd     : fundamentals dict from _parse_fundamentals()
        series : list of OHLCV dicts (must have ≥20 items)
        h52    : float, 52-week high (from meta, more accurate than series)
        l52    : float, 52-week low

    Returns a single dict that is 100% JSON-serialisable (native Python types).
    """
    closes = np.array([d["close"]  for d in series], dtype=float)
    highs  = np.array([d["high"]   for d in series], dtype=float)
    lows   = np.array([d["low"]    for d in series], dtype=float)
    cur    = float(closes[-1]) if len(closes) else 0.0

    # Use series max/min as fallback if meta 52-week values are missing
    h52 = float(h52) if h52 and h52 > 0 else float(highs.max())
    l52 = float(l52) if l52 and l52 > 0 else float(lows.min())

    # ── Run all 4 layers ─────────────────────────────────────
    trend_out = classify_trend(closes, highs, lows)
    adx       = calc_adx(highs, lows, closes)
    mom_out   = classify_momentum(closes, highs, lows, adx)
    vol_out   = classify_volatility_position(closes, highs, lows, h52, l52)
    fd_out    = assess_fundamentals(fd)

    trend_score = trend_out["trend_score"]   # 0–4
    mom_score   = mom_out["momentum_score"]  # 0–3
    vol_score   = vol_out["vol_score"]       # 0–3
    fd_score    = fd_out["fd_score"]         # 0–4

    # ── RULE 1: Hard gate — price below 200 EMA ──────────────
    # Cannot be a strong candidate in a long-term downtrend.
    below_200_gate = not trend_out["above_200"]

    # ── RULE 2: Flat market gate — ADX < 20 ──────────────────
    flat_market = not mom_out["adx_trending"]

    # ── Confidence engine ─────────────────────────────────────
    # Base confidence from trend (most important layer)
    # Then modified up/down by momentum and fundamentals
    # Caps applied for data gaps and conflicting signals
    layer_sum = trend_score + mom_score + vol_score
    max_possible = 10  # 4+3+3

    raw_conf = layer_sum / max_possible  # 0.0 – 1.0

    # Boost from strong fundamentals
    if fd_out["fd_available"] and fd_score >= 3:
        raw_conf = min(1.0, raw_conf + 0.10)
    elif fd_out["fd_available"] and fd_score >= 2:
        raw_conf = min(1.0, raw_conf + 0.05)

    # Cap: no fundamentals → max 70% confidence
    if not fd_out["fd_available"]:
        raw_conf = min(raw_conf, 0.70)

    # Penalty: conflicting momentum votes
    if mom_out["bullish_votes"] > 0 and mom_out["bearish_votes"] > 0:
        raw_conf -= 0.08

    # Penalty: flat market
    if flat_market:
        raw_conf -= 0.10

    # Penalty: hard downtrend gate
    if below_200_gate:
        raw_conf -= 0.15

    raw_conf = max(0.0, min(1.0, raw_conf))
    confidence_pct = round(raw_conf * 100, 0)

    # Confidence label
    if confidence_pct >= 72:
        confidence_label = "High"
    elif confidence_pct >= 50:
        confidence_label = "Moderate"
    elif confidence_pct >= 32:
        confidence_label = "Low"
    else:
        confidence_label = "Very Low"

    # ── ACTION TAG ────────────────────────────────────────────
    # Rules (strict):
    # Strong Candidate: multi-layer confirmation, no hard gates
    # Watchlist: mixed signals OR fundamental data missing
    # Avoid for Now: weak/down trend OR very low confidence
    if (
        trend_score >= 3 and
        mom_score   >= 2 and
        not below_200_gate and
        not flat_market and
        confidence_pct >= 65
    ):
        if fd_out["fd_available"] and fd_score >= 2:
            action_tag = "Strong Candidate"
        else:
            action_tag = "Watchlist"   # good technicals but no fundamental confirmation
    elif (
        trend_score <= 1 or
        below_200_gate or
        (mom_score == 0 and trend_score <= 1) or
        confidence_pct < 32
    ):
        action_tag = "Avoid for Now"
    else:
        action_tag = "Watchlist"

    # ── Key insights (analyst-voice, not raw numbers) ─────────
    key_insights = []
    risk_flags   = []

    # Trend insights
    trend_label = trend_out["trend"]
    if "Uptrend" in trend_label:
        key_insights.append(f"Primary trend is {trend_label.lower()} — price structure supports continuation")
        if trend_out["golden_cross"]:
            key_insights.append("Golden Cross confirmed (50 EMA > 200 EMA) — structural bull signal")
    elif "Downtrend" in trend_label:
        risk_flags.append(f"Price in {trend_label.lower()} — EMA structure is bearish")
    else:
        key_insights.append("Price in a sideways phase — no clear directional edge")
        risk_flags.append("Breakout above resistance or breakdown below support will set direction")

    # Momentum insights
    if "Strong Bullish" in mom_out["momentum"]:
        key_insights.append("RSI and MACD agree on upward momentum — signal quality is high")
    elif "Bullish" in mom_out["momentum"]:
        key_insights.append("Momentum is broadly positive though not all indicators confirm")
    elif "Bearish" in mom_out["momentum"]:
        risk_flags.append("Multiple momentum indicators bearish — not an ideal entry point")
    elif flat_market:
        risk_flags.append("Market is in a low-trend state (ADX<20) — signals are unreliable")

    # Volatility / position insights
    vpos = vol_out["volatility_position"]
    p52  = vol_out["pos_52w_pct"]
    if "Near 52-Week High" in vpos and "Exhausted" not in vpos:
        key_insights.append(f"Stock trading near 52-week high ({p52:.0f}% of range) — potential breakout zone")
    elif "Exhausted" in vpos:
        risk_flags.append(f"Near 52-week high AND overbought on Bollinger Bands — elevated pullback risk")
    elif "Lower Half" in vpos or "Near Low" in vpos:
        key_insights.append(f"Stock in lower range ({p52:.0f}% of 52-week range) — watch for base formation")

    # ATR context
    atr_pct = vol_out["atr_pct"]
    if atr_pct > 3.0:
        risk_flags.append(f"High daily volatility (ATR {atr_pct:.1f}% of price) — size positions carefully")
    elif atr_pct < 0.8:
        key_insights.append("Low daily volatility — compressed range may precede a directional move")

    # Hard gate warning
    if below_200_gate:
        risk_flags.append("Price below 200 EMA — long-term trend is not in favour of buyers")

    # Fundamental layer
    key_insights.extend(fd_out["fd_insights"][:2])
    risk_flags.extend(fd_out["fd_risks"][:2])

    # ── Analysis summary (one-paragraph, analyst voice) ───────
    parts = []
    parts.append(
        f"{fd.get('name', 'This stock')} is in a {trend_label.lower()} with "
        f"{mom_out['momentum'].lower()} momentum and "
        f"{confidence_label.lower()} confidence ({confidence_pct:.0f}%)."
    )
    if action_tag == "Strong Candidate":
        parts.append(
            "Multiple layers confirm — trend, momentum, and fundamentals align. "
            "The setup warrants closer attention pending risk management."
        )
    elif action_tag == "Watchlist":
        parts.append(
            "Some positive factors exist but confirmation is incomplete. "
            "Monitor for improving structure before conviction increases."
        )
    else:
        parts.append(
            "Current structure does not support a favourable risk/reward setup. "
            "Absence of a clean trend makes timing difficult."
        )
    if not fd_out["fd_available"]:
        parts.append(
            "Note: fundamental data was not available; confidence is capped and "
            "the assessment is based on price structure only."
        )

    analysis_summary = " ".join(parts)

    # ── Forecasts (conservative, volatility-based ranges) ─────
    forecasts = _build_forecasts(closes, cur)

    # ── Legacy compatibility fields ───────────────────────────
    # The frontend reads these keys. Keep them populated so the
    # existing UI renders without changes.
    stch     = calc_stoch(highs, lows, closes)
    bb       = vol_out["bb"]
    rsi_val  = mom_out["rsi"]
    macd_val = mom_out["macd"]
    adx_val  = mom_out["adx"]

    # Score mapped from confidence (legacy "score" field)
    legacy_score = int(round(confidence_pct))

    # Legacy verdict mapped from action tag
    if action_tag == "Strong Candidate":
        legacy_verdict = "CAUTIOUS BUY"
    elif action_tag == "Watchlist":
        legacy_verdict = "HOLD"
    else:
        legacy_verdict = "REDUCE"

    # Legacy findings from key_insights + risk_flags
    legacy_findings = []
    for ins in key_insights[:4]:
        legacy_findings.append({"t": "p", "tx": ins})
    for rsk in risk_flags[:4]:
        legacy_findings.append({"t": "n", "tx": rsk})

    # Legacy breakdown (maps layers to old bh/val/tech/inst keys)
    legacy_breakdown = {
        "bh":   int(round(trend_score / 4 * 30)),
        "val":  int(round((fd_score   / 4 * 25) if fd_out["fd_available"] else 0)),
        "tech": int(round(mom_score   / 3 * 25)),
        "inst": int(round(vol_score   / 3 * 20)),
    }

    return {
        # ── New structured output ──────────────────────────────
        "trend":               trend_out["trend"],
        "momentum":            mom_out["momentum"],
        "volatility_position": vol_out["volatility_position"],
        "confidence":          f"{confidence_label} ({confidence_pct:.0f}%)",
        "confidence_pct":      float(confidence_pct),
        "action_tag":          action_tag,
        "key_insights":        key_insights[:5],
        "risk_flags":          risk_flags[:4],
        "analysis_summary":    analysis_summary,
        "fd_quality":          fd_out["fd_quality"],
        "fd_available":        fd_out["fd_available"],  # propagated up from here too

        # ── Trend detail ───────────────────────────────────────
        "ema20":               trend_out["ema20"],
        "ema50":               trend_out["ema50"],
        "ema200":              trend_out["ema200"],
        "above_50":            trend_out["above_50"],
        "above_200":           trend_out["above_200"],
        "golden_cross":        trend_out["golden_cross"],
        "ema_signal":          "Bullish" if trend_out["above_50"] else "Bearish",

        # ── Momentum detail ────────────────────────────────────
        "rsi":                 rsi_val,
        "rsi_signal":          ("Oversold"   if rsi_val < 35  else
                                "Overbought" if rsi_val > 72  else "Neutral"),
        "macd":                macd_val,
        "macd_signal":         "Bullish" if macd_val["hist"] > 0 else "Bearish",
        "adx":                 adx_val,
        "adx_strength":        ("Strong"   if adx_val > 25 else
                                "Moderate" if adx_val > 20 else "Weak"),
        "momentum_signals":    mom_out["signals"],

        # ── Volatility detail ──────────────────────────────────
        "bb":                  bb,
        "stoch":               stch,
        "stoch_signal":        ("Oversold"   if stch["k"] < 20  else
                                "Overbought" if stch["k"] > 80  else "Neutral"),
        "atr_pct":             vol_out["atr_pct"],
        "pos_52w_pct":         vol_out["pos_52w_pct"],

        # ── Forecasts ──────────────────────────────────────────
        "forecasts":           forecasts,

        # ── Legacy fields (frontend compatibility) ─────────────
        "score":               legacy_score,
        "verdict":             legacy_verdict,
        "breakdown":           legacy_breakdown,
        "findings":            legacy_findings,
    }


def _build_forecasts(closes, cur):
    """
    Conservative statistical price ranges.
    Uses capped linear drift + realised volatility.
    Never produces negative prices or >5× current price.
    """
    forecasts = []
    if len(closes) < 60 or cur <= 0:
        return forecasts

    y     = closes[-60:]
    x     = np.arange(len(y), dtype=float)
    n_pts = len(y)
    sx, sy = x.sum(), y.sum()
    denom  = n_pts * (x**2).sum() - sx**2
    slope  = ((n_pts * (x*y).sum() - sx*sy) / denom) if denom != 0 else 0.0

    # Daily drift capped at ±0.35%/day (~90%/year — very generous upper bound)
    dd_raw = float(slope) / cur * 100
    dd     = max(-0.35, min(0.35, dd_raw))

    # Realised volatility (30-day, clipped to remove split artefacts)
    if len(closes) > 31:
        rets    = np.diff(closes[-31:]) / closes[-31:-1]
        rets    = np.clip(rets, -0.12, 0.12)
        ann_vol = float(np.std(rets)) * math.sqrt(252)
        ann_vol = min(ann_vol, 0.75)
    else:
        ann_vol = 0.28

    for lbl, days in [("1 Month", 22), ("3 Months", 66), ("6 Months", 130), ("12 Months", 252)]:
        base       = cur * (1 + dd / 100 * days)
        period_vol = ann_vol * math.sqrt(days / 252)
        margin     = cur * period_vol * 0.5

        bull_p = base + margin
        bear_p = base - margin
        floor  = cur * 0.10
        ceil   = cur * 5.0

        base   = float(max(floor, min(ceil, base)))
        bull_p = float(max(floor, min(ceil, bull_p)))
        bear_p = float(max(floor,           bear_p))

        forecasts.append({
            "period": lbl,
            "days":   days,
            "base":   round(base,   2),
            "bull":   round(bull_p, 2),
            "bear":   round(bear_p, 2),
            "chg":    round((base - cur) / cur * 100, 2),
        })

    return forecasts


# ── LEGACY SHIM ──────────────────────────────────────────────
# Keeps any code that still calls score_stock() working.
def score_stock(fd, series):
    """Shim: delegates to analyse_stock()."""
    return analyse_stock(fd, series)


# ═════════════════════════════════════════════════════════════
#  GROQ AI SUMMARY
# ═════════════════════════════════════════════════════════════

def groq_analysis(data):
    """
    Generate a 400-500 word analyst-style research note via Groq.
    data must contain the keys used in the prompt below.
    Returns None if GROQ_KEY is not set or call fails.
    """
    if not GROQ_KEY:
        return None

    insights_text = "\n".join(
        f"{i+1}. {s}" for i, s in enumerate(data.get("key_insights", [])[:5])
    )
    risks_text = "\n".join(
        f"{i+1}. {s}" for i, s in enumerate(data.get("risk_flags", [])[:3])
    )

    prompt = f"""You are a senior equity research analyst at a top Indian brokerage.

Stock: {data.get('name', '')} ({data.get('sym', '')}) | Sector: {data.get('sector', '—')}
Price: ₹{data.get('price', 0)} | 52W Range: ₹{data.get('l52', 0)} – ₹{data.get('h52', 0)}
Market Cap: {data.get('mc_fmt', 'N/A')} | P/E: {data.get('pe', 0)}x (Sector avg: {data.get('spe', 22)}x)
Rev Growth: {data.get('rg', 0)}% | Net Margin: {data.get('pm', 0)}% | ROE: {data.get('roe', 0)}%
Trend: {data.get('trend', '—')} | Momentum: {data.get('momentum', '—')} | Confidence: {data.get('confidence', '—')}
Action Tag: {data.get('action_tag', '—')}

Key Insights:
{insights_text}

Risk Flags:
{risks_text}

Write a concise research note with EXACTLY these four sections:

BUSINESS OVERVIEW
Two sentences describing what the company does and its market position.

FINANCIAL ASSESSMENT
Three sentences with specific numbers from the data above.

KEY RISKS
1. [First specific risk]
2. [Second specific risk]

ANALYTICAL SUMMARY
Two sentences summarising the technical and fundamental picture.

STRICT RULES:
- Never use the words: buy, sell, invest, recommend, target price
- Write in third person, analyst voice
- Use actual numbers from the data above
- Total length: 200–280 words"""

    try:
        r = req.post(
            GROQ_URL,
            json={
                "model":       GROQ_MDL,
                "max_tokens":  550,
                "temperature": 0.2,
                "messages":    [{"role": "user", "content": prompt}],
            },
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type":  "application/json",
            },
            timeout=20,
        )
        if r.ok:
            return r.json()["choices"][0]["message"]["content"]
    except Exception:
        pass

    return None
