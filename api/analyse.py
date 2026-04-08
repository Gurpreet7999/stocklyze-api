import json, sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

from _utils import yf_sym, safe, fmt_cap, get_chart, get_fundamentals, score_stock
import numpy as np
from datetime import datetime
from urllib.parse import parse_qs, urlparse

CACHE = {}
CACHE_TTL = 120

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}

def cached_analyse(sym):
    now = time.time()

    if sym in CACHE and now - CACHE[sym]["ts"] < CACHE_TTL:
        return CACHE[sym]["data"]

    data = analyse(sym)
    CACHE[sym] = {"data": data, "ts": now}
    return data


def handler(request):
    try:
        qs = parse_qs(urlparse(request.get("url","")).query)
        sym = (qs.get("sym",[""])[0]).upper().strip()

        if not sym:
            return res({"error": "symbol required"})

        data = cached_analyse(sym)
        return res(data)

    except Exception as e:
        return res({"error": "Server failed"}, code=200)


def analyse(sym):
    ysym = yf_sym(sym)

    # fetch chart
    try:
        series = get_chart(ysym, "6mo")
    except:
        series = []

    if not series:
        return {"error": "No data (rate limited or invalid stock)"}

    closes = np.array([x["close"] for x in series])

    cur = float(closes[-1])
    prev = float(closes[-2]) if len(closes) > 1 else cur

    change = round(cur - prev, 2)
    pct = round(change / prev * 100, 2) if prev else 0

    ma50 = round(np.mean(closes[-50:]), 2) if len(closes) >= 50 else cur

    # fundamentals (optional)
    try:
        fd = get_fundamentals(ysym)
    except:
        fd = {}

    return {
        "sym": sym,
        "price": cur,
        "change": change,
        "pct": pct,
        "ma50": ma50,
        "name": fd.get("name", sym),
        "sector": fd.get("sector", ""),
        "series": series[-100:],
        "analysed_at": datetime.utcnow().isoformat()
    }


def res(data, code=200):
    return {
        "statusCode": code,
        "headers": HEADERS,
        "body": json.dumps(data)
    }
