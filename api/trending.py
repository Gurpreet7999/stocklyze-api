import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _utils import get_chart, yf_sym

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

# Top NSE stocks for trending — fetched live
WATCHLIST = [
    "RELIANCE","TCS","HDFCBANK","ICICIBANK","BHARTIARTL","SBIN","INFY","HINDUNILVR",
    "ITC","LT","BAJFINANCE","KOTAKBANK","AXISBANK","MARUTI","SUNPHARMA","TATAMOTORS",
    "NTPC","TITAN","POWERGRID","WIPRO","ULTRACEMCO","HCLTECH","NESTLEIND","TECHM",
    "ADANIENT","COALINDIA","ONGC","JSWSTEEL","TATASTEEL","BAJAJFINSV","INDUSINDBK",
    "BPCL","EICHERMOT","HEROMOTOCO","DIVISLAB","DRREDDY","CIPLA","APOLLOHOSP",
    "ADANIPORTS","TATACONSUM","SBILIFE","HDFCLIFE","HINDALCO","VEDL","TATAPOWER",
    "DMART","ZOMATO","HAL","BEL","IRCTC","M&M","TVSMOTOR","BAJAJ-AUTO","GODREJCP",
    "MARICO","PAGEIND","TRENT","NYKAA","JUBLFOOD","LUPIN","ZYDUSLIFE","DLF","HAVELLS",
]

def handler(request):
    results = []
    # Fetch each individually — Vercel serverless doesn't support yfinance batch well
    # Use concurrent approach via direct Yahoo Finance API
    import concurrent.futures

    def fetch_one(sym):
        try:
            series = get_chart(yf_sym(sym), period="5d")
            if not series or len(series) < 2:
                return None
            cur  = series[-1]["close"]
            prev = series[-2]["close"]
            vol  = series[-1]["volume"]
            if cur <= 0 or prev <= 0: return None
            chg = round(cur - prev, 2)
            pct = round(chg / prev * 100, 2)
            return {"sym": sym, "price": cur, "change": chg, "pct": pct, "vol": vol}
        except:
            return None

    # Fetch top 40 in parallel (Vercel allows threading)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(fetch_one, sym): sym for sym in WATCHLIST[:40]}
        for future in concurrent.futures.as_completed(futures, timeout=25):
            try:
                result = future.result()
                if result:
                    results.append(result)
            except:
                pass

    gainers = sorted(results, key=lambda x: x["pct"], reverse=True)[:10]
    losers  = sorted(results, key=lambda x: x["pct"])[:10]
    active  = sorted(results, key=lambda x: x["vol"], reverse=True)[:10]

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({"gainers": gainers, "losers": losers, "active": active}),
    }
