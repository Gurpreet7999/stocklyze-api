import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _utils import get_chart, safe

INDICES = [
    {"name":"NIFTY 50",   "sym":"^NSEI"},
    {"name":"BANK NIFTY", "sym":"^NSEBANK"},
    {"name":"SENSEX",     "sym":"^BSESN"},
    {"name":"FIN NIFTY",  "sym":"NIFTY_FIN_SERVICE.NS"},
    {"name":"MIDCAP 150", "sym":"^NSEMDCP150"},
    {"name":"IT NIFTY",   "sym":"^CNXIT"},
]

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

def handler(request):
    results = []
    for idx in INDICES:
        series = get_chart(idx["sym"], period="5d")
        if series and len(series) >= 2:
            cur  = series[-1]["close"]
            prev = series[-2]["close"]
            chg  = round(cur - prev, 2)
            pct  = round(chg / prev * 100, 2) if prev > 0 else 0
        else:
            cur = chg = pct = 0
        results.append({
            "name": idx["name"],
            "sym":  idx["sym"],
            "price":  round(cur, 2),
            "change": chg,
            "pct":    pct,
            "direction": "up" if chg >= 0 else "down",
        })
    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps(results),
    }
