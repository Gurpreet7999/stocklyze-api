from http.server import BaseHTTPRequestHandler
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _utils import CORS_HEADERS, yf_sym, safe
import yfinance as yf

WATCHLIST = [
    "RELIANCE","TCS","HDFCBANK","ICICIBANK","BHARTIARTL","SBIN","INFY","HINDUNILVR",
    "ITC","LT","BAJFINANCE","KOTAKBANK","AXISBANK","MARUTI","SUNPHARMA","TATAMOTORS",
    "NTPC","TITAN","POWERGRID","WIPRO","ULTRACEMCO","TECHM","NESTLEIND","HCLTECH",
    "ADANIENT","COALINDIA","ONGC","JSWSTEEL","TATASTEEL","BAJAJFINSV","INDUSINDBK",
    "BPCL","EICHERMOT","HEROMOTOCO","DIVISLAB","DRREDDY","CIPLA","APOLLOHOSP",
    "ADANIPORTS","TATACONSUM","SBILIFE","HDFCLIFE","HINDALCO","VEDL","TATAPOWER",
    "DMART","ZOMATO","HAL","BEL","IRCTC","RVNL","RECLTD","PFC","M&M","TVSMOTOR",
    "BAJAJ-AUTO","GODREJCP","MARICO","PAGEIND","TRENT","NYKAA","JUBLFOOD","DLF",
    "SIEMENS","ABB","POLYCAB","HAVELLS","PIDILITIND","YESBANK","BANDHANBNK","SAIL",
    "IOC","GAIL","HINDPETRO","LODHA","FEDERALBNK","LUPIN","TORNTPHARM","ZYDUSLIFE",
]

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        results = []
        # Batch fetch using yfinance — most efficient
        try:
            yf_syms = [yf_sym(s) for s in WATCHLIST[:60]]
            data = yf.download(
                yf_syms, period="2d",
                auto_adjust=True, group_by="ticker",
                threads=True, progress=False
            )
            for i, sym in enumerate(WATCHLIST[:60]):
                ys = yf_sym(sym)
                try:
                    if ys in data.columns.get_level_values(0):
                        df = data[ys]
                        if len(df) < 2: continue
                        cur  = round(float(df["Close"].iloc[-1]), 2)
                        prev = round(float(df["Close"].iloc[-2]), 2)
                        vol  = int(df["Volume"].iloc[-1]) if "Volume" in df else 0
                        if cur <= 0 or prev <= 0: continue
                        chg = round(cur-prev, 2)
                        pct = round(chg/prev*100, 2)
                        results.append({"sym":sym,"price":cur,"change":chg,"pct":pct,"vol":vol})
                except:
                    continue
        except Exception as e:
            # Fallback: fetch top 20 individually
            for sym in WATCHLIST[:20]:
                try:
                    h = yf.Ticker(yf_sym(sym)).history(period="5d", auto_adjust=True)
                    if len(h) < 2: continue
                    cur=round(float(h["Close"].iloc[-1]),2)
                    prev=round(float(h["Close"].iloc[-2]),2)
                    vol=int(h["Volume"].iloc[-1])
                    if cur<=0 or prev<=0: continue
                    chg=round(cur-prev,2); pct=round(chg/prev*100,2)
                    results.append({"sym":sym,"price":cur,"change":chg,"pct":pct,"vol":vol})
                except:
                    continue

        gainers = sorted(results, key=lambda x:x["pct"], reverse=True)[:10]
        losers  = sorted(results, key=lambda x:x["pct"])[:10]
        active  = sorted(results, key=lambda x:x["vol"], reverse=True)[:10]

        out = {"gainers":gainers,"losers":losers,"active":active}
        self.send_response(200)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(json.dumps(out).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
