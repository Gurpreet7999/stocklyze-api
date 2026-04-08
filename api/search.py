import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _utils import YF_HEADERS
import requests as req
from urllib.parse import parse_qs, urlparse

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

POPULAR = [
    "RELIANCE","TCS","HDFCBANK","ICICIBANK","BHARTIARTL","SBIN","INFY","HINDUNILVR",
    "ITC","LT","BAJFINANCE","KOTAKBANK","AXISBANK","MARUTI","SUNPHARMA","TATAMOTORS",
    "NTPC","TITAN","POWERGRID","WIPRO","ULTRACEMCO","HCLTECH","NESTLEIND","TECHM",
    "ADANIENT","COALINDIA","ONGC","JSWSTEEL","TATASTEEL","BAJAJFINSV","INDUSINDBK",
    "BPCL","EICHERMOT","HEROMOTOCO","DIVISLAB","DRREDDY","CIPLA","APOLLOHOSP",
    "ADANIPORTS","TATACONSUM","SBILIFE","HDFCLIFE","HINDALCO","VEDL","TATAPOWER",
    "DMART","ZOMATO","HAL","BEL","IRCTC","RVNL","RECLTD","PFC","M&M","TVSMOTOR",
    "BAJAJ-AUTO","GODREJCP","MARICO","COLPAL","DABUR","PAGEIND","TRENT","NYKAA","PAYTM",
    "JUBLFOOD","IDFCFIRSTB","FEDERALBNK","AUBANK","YESBANK","BANDHANBNK","RBLBANK",
    "LUPIN","TORNTPHARM","BIOCON","ALKEM","ZYDUSLIFE","DLF","GODREJPROP","LODHA",
    "SIEMENS","ABB","POLYCAB","HAVELLS","PIDILITIND","BERGEPAINT","SAIL","IOC","GAIL",
    "HINDPETRO","TATACHEM","DEEPAKNTR","SRF","ANGELONE","CDSL","MCX","BSE",
]

def handler(request):
    # Parse query param
    qs = parse_qs(urlparse(request.get("url","")).query)
    q  = (qs.get("q",[""])[0] or "").strip()

    results = []
    if q:
        # Yahoo Finance live autocomplete — covers ALL NSE/BSE stocks
        try:
            url = f"https://query2.finance.yahoo.com/v1/finance/search?q={q}&newsCount=0&quotesCount=10&enableFuzzyQuery=true"
            r = req.get(url, headers=YF_HEADERS, timeout=8)
            if r.ok:
                for qt in r.json().get("quotes", []):
                    sym = qt.get("symbol","")
                    if not (sym.endswith(".NS") or sym.endswith(".BO")): continue
                    clean = sym.replace(".NS","").replace(".BO","")
                    results.append({
                        "sym": clean,
                        "name": qt.get("longname") or qt.get("shortname") or clean,
                        "exchange": "NSE" if sym.endswith(".NS") else "BSE",
                        "sector": qt.get("industry",""),
                    })
        except: pass

        # Local fuzzy fallback
        ql = q.lower()
        for sym in POPULAR:
            if ql in sym.lower() and not any(r["sym"]==sym for r in results):
                results.append({"sym":sym,"name":sym,"exchange":"NSE","sector":""})

    return {
    "statusCode": 200,
    "headers": HEADERS,
    "body": json.dumps([])
}
