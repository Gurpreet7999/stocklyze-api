from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, sys, os, requests as req
sys.path.insert(0, os.path.dirname(__file__))
from _utils import CORS_HEADERS

NIFTY_POPULAR = [
    "RELIANCE","TCS","HDFCBANK","ICICIBANK","BHARTIARTL","SBIN","INFY","HINDUNILVR",
    "ITC","LT","BAJFINANCE","KOTAKBANK","AXISBANK","MARUTI","SUNPHARMA","TATAMOTORS",
    "NTPC","TITAN","POWERGRID","WIPRO","ULTRACEMCO","TECHM","NESTLEIND","HCLTECH",
    "ADANIENT","COALINDIA","ONGC","JSWSTEEL","TATASTEEL","BAJAJFINSV","INDUSINDBK",
    "BPCL","EICHERMOT","HEROMOTOCO","DIVISLAB","DRREDDY","CIPLA","APOLLOHOSP",
    "ADANIPORTS","TATACONSUM","BRITANNIA","SBILIFE","HDFCLIFE","HINDALCO","VEDL",
    "TATAPOWER","DMART","ZOMATO","HAL","BEL","IRCTC","RVNL","NHPC","RECLTD","PFC",
    "MUTHOOTFIN","CHOLAFIN","BAJAJ-AUTO","TVSMOTOR","MRF","BOSCHLTD","MOTHERSON",
    "GODREJCP","MARICO","COLPAL","DABUR","VBL","PAGEIND","TRENT","NYKAA","PAYTM",
    "JUBLFOOD","IDFCFIRSTB","FEDERALBNK","AUBANK","LUPIN","TORNTPHARM","BIOCON",
    "ALKEM","ZYDUSLIFE","DLF","GODREJPROP","LODHA","SIEMENS","ABB","POLYCAB","HAVELLS",
    "PIDILITIND","BERGEPAINT","YESBANK","BANDHANBNK","RBLBANK","ANGELONE","CDSL","BSE",
    "HAL","SAIL","IOC","GAIL","HINDPETRO","M&M","TATACHEM","DEEPAKNTR","PIIND","SRF",
]

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query).get("q", [""])[0].strip()
        results = []

        if q:
            # 1. Yahoo Finance autocomplete — real-time, covers ALL NSE/BSE stocks
            try:
                url = f"https://query2.finance.yahoo.com/v1/finance/search?q={q}+NSE&newsCount=0&quotesCount=10&enableFuzzyQuery=true"
                r = req.get(url, timeout=8,
                    headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
                if r.ok:
                    for qt in r.json().get("quotes", []):
                        sym = qt.get("symbol", "")
                        if not (sym.endswith(".NS") or sym.endswith(".BO")):
                            continue
                        clean = sym.replace(".NS","").replace(".BO","")
                        results.append({
                            "sym": clean,
                            "name": qt.get("longname") or qt.get("shortname") or clean,
                            "exchange": qt.get("exchange","NSE"),
                            "sector": qt.get("industry",""),
                        })
            except:
                pass

            # 2. Fallback — local fuzzy match from popular list
            ql = q.lower()
            for sym in NIFTY_POPULAR:
                if ql in sym.lower() and not any(r["sym"]==sym for r in results):
                    results.append({"sym":sym,"name":sym,"exchange":"NSE","sector":""})

        self.send_response(200)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(json.dumps(results[:12]).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
