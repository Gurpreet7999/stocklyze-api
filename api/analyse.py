import json, sys, os, math
sys.path.insert(0, os.path.dirname(__file__))
from _utils import (yf_sym, safe, fmt_cap, get_chart, get_fundamentals,
                    score_stock, groq_analysis, SECTOR_PE)
import numpy as np
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import time

def cached_analyse(sym):
    now = time.time()

    if sym in CACHE and now - CACHE[sym]["ts"] < CACHE_TTL:
        return CACHE[sym]["data"]

    data = analyse(sym)
    CACHE[sym] = {"data": data, "ts": now}
    return data

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

def handler(request):
    # OPTIONS preflight
    if request.get("method","GET") == "OPTIONS":
        return {"statusCode": 200, "headers": HEADERS, "body": ""}

    # Parse symbol from query string
    qs  = parse_qs(urlparse(request.get("url","")).query)
    sym = (qs.get("sym",[""])[0] or qs.get("symbol",[""])[0]).upper().strip()

    if not sym:
        return {"statusCode": 400, "headers": HEADERS,
                "body": json.dumps({"error": "sym parameter required. Example: /api/analyse?sym=RELIANCE"})}

    try:
        result = cached_analyse(sym)
        return {"statusCode": 200, "headers": HEADERS, "body": json.dumps(result, default=str)}
    except ValueError as e:
        return {"statusCode": 404, "headers": HEADERS, "body": json.dumps({"error": str(e)})}
    except Exception as e:
        return {"statusCode": 500, "headers": HEADERS, "body": json.dumps({"error": f"Analysis failed: {str(e)}"})}


def analyse(sym: str) -> dict:
    ysym = yf_sym(sym)

    # Step 1: Get 1-year chart data (faster than 2yr, enough for analysis)
    series = get_chart(ysym, period="1y")

    # Fallback to BSE if NSE fails
    if not series or len(series) < 20:
        bse_sym = sym + ".BO"
        series = get_chart(bse_sym, period="1y")

    if not series or len(series) < 20:
        raise ValueError(
            f"No data found for '{sym}'. "
            f"Make sure it is a valid NSE symbol (e.g. RELIANCE, TCS, HDFCBANK, ZOMATO, INFY)."
        )

    # Step 2: Get fundamentals (PE, ROE, margins etc.)
    fd = get_fundamentals(ysym)
    if not fd.get("name"):
        fd_bse = get_fundamentals(sym + ".BO")
        if fd_bse.get("name"): fd = fd_bse

    # Step 3: Build price stats from series
    closes_arr = np.array([s["close"] for s in series], dtype=float)
    highs_arr  = np.array([s["high"]  for s in series], dtype=float)
    lows_arr   = np.array([s["low"]   for s in series], dtype=float)

    cur  = round(float(series[-1]["close"]), 2)
    prev = round(float(series[-2]["close"]) if len(series)>1 else cur, 2)
    chg  = round(cur - prev, 2)
    pct  = round(chg / prev * 100, 2) if prev > 0 else 0

    h52  = round(float(highs_arr[-252:].max())  if len(highs_arr)>=252  else float(highs_arr.max()),  2)
    l52  = round(float(lows_arr[-252:].min())   if len(lows_arr)>=252   else float(lows_arr.min()),   2)
    ma50 = round(float(np.mean(closes_arr[-50:])),  2) if len(closes_arr)>=50  else cur
    ma200= round(float(np.mean(closes_arr[-200:])), 2) if len(closes_arr)>=200 else cur

    # Use fundamentals or fallback values
    mc     = fd.get("mc", 0)
    pe     = fd.get("pe") or None
    pb     = fd.get("pb") or None
    sector = fd.get("sector","")
    spe    = SECTOR_PE.get(sector, 22)
    name   = fd.get("name") or sym

    # Step 4: Score engine
    eng = score_stock(fd, series)

    # Step 5: Groq AI analysis (non-blocking — returns None if fails)
    groq_text = groq_analysis({
        "sym": sym, "name": name, "sector": sector,
        "price": cur, "h52": h52, "l52": l52,
        "pe":  f"{pe:.1f}" if pe else "N/A",
        "pb":  f"{pb:.1f}" if pb else "N/A",
        "spe": spe, "mc_fmt": fmt_cap(mc),
        "rg":  round(safe(fd.get("revenue_growth",0))*100, 2),
        "pm":  round(safe(fd.get("profit_margins",0))*100, 2),
        "roe": round(safe(fd.get("return_on_equity",0))*100, 2),
        "inst":round(safe(fd.get("held_institutions",0))*100, 2),
        "beta":round(safe(fd.get("beta",1),1), 2),
        **eng,
    })

    return {
        "sym": sym,
        "name": name,
        "sector": sector,
        "industry": fd.get("industry",""),
        "description": fd.get("description",""),
        "exchange": fd.get("exchange","NSE"),
        "price":  cur,
        "change": chg,
        "pct":    pct,
        "open":   round(float(series[-1]["open"]),  2),
        "high":   round(float(series[-1]["high"]),  2),
        "low":    round(float(series[-1]["low"]),   2),
        "vol":    series[-1]["volume"],
        "h52":    h52,
        "l52":    l52,
        "mc":     mc,
        "mc_fmt": fmt_cap(mc),
        "pe":     round(pe, 1) if pe else None,
        "pb":     round(pb, 2) if pb else None,
        "spe":    spe,
        "eps":    fd.get("eps"),
        "beta":   round(safe(fd.get("beta",1),1), 2),
        "div_yield":  round(safe(fd.get("div_yield",0))*100, 2),
        "rg":         round(safe(fd.get("revenue_growth",0))*100, 2),
        "pm":         round(safe(fd.get("profit_margins",0))*100, 2),
        "roe":        round(safe(fd.get("return_on_equity",0))*100, 2),
        "roa":        round(safe(fd.get("return_on_assets",0))*100, 2),
        "op_margin":  round(safe(fd.get("op_margins",0))*100, 2),
        "eg":         round(safe(fd.get("earnings_growth",0))*100, 2),
        "de":         round(safe(fd.get("debt_to_equity",0))/100, 2),
        "inst":       round(safe(fd.get("held_institutions",0))*100, 2),
        "insiders":   round(safe(fd.get("held_insiders",0))*100, 2),
        "target_price":  fd.get("target_price"),
        "analyst_count": fd.get("analyst_count",0),
        "ma50":  ma50,
        "ma200": ma200,
        **eng,
        "series":       series,
        "groq_text":    groq_text,
        "analysed_at":  datetime.utcnow().isoformat() + "Z",
    }
