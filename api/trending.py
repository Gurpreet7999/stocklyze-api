import json, sys, os, time
sys.path.insert(0, os.path.dirname(__file__))
from _utils import get_chart, yf_sym

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

WATCHLIST = [
    "RELIANCE","TCS","HDFCBANK","ICICIBANK","BHARTIARTL","SBIN","INFY","ITC",
    "LT","AXISBANK","KOTAKBANK","MARUTI","SUNPHARMA","TATAMOTORS","NTPC"
]

# 🔥 SIMPLE CACHE (IMPORTANT)
CACHE = {}
CACHE_TTL = 60  # seconds


def fetch_one(sym):
    try:
        series = get_chart(yf_sym(sym), period="5d")
        if not series or len(series) < 2:
            return None

        cur = series[-1]["close"]
        prev = series[-2]["close"]
        vol = series[-1]["volume"]

        if cur <= 0 or prev <= 0:
            return None

        chg = round(cur - prev, 2)
        pct = round(chg / prev * 100, 2)

        return {
            "sym": sym,
            "price": cur,
            "change": chg,
            "pct": pct,
            "vol": vol
        }

    except:
        return None


def cached_fetch(sym):
    now = time.time()

    if sym in CACHE and now - CACHE[sym]["ts"] < CACHE_TTL:
        return CACHE[sym]["data"]

    data = fetch_one(sym)
    CACHE[sym] = {"data": data, "ts": now}
    return data


def handler(request):
    results = []

    # 🔥 NO THREADING (Vercel safe)
    for sym in WATCHLIST:
        data = cached_fetch(sym)
        if data:
            results.append(data)

    if not results:
        return {
            "statusCode": 200,
            "headers": HEADERS,
            "body": json.dumps({"gainers": [], "losers": [], "active": []}),
        }

    gainers = sorted(results, key=lambda x: x["pct"], reverse=True)[:5]
    losers = sorted(results, key=lambda x: x["pct"])[:5]
    active = sorted(results, key=lambda x: x["vol"], reverse=True)[:5]

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({
            "gainers": gainers,
            "losers": losers,
            "active": active
        }),
    }
