from http.server import BaseHTTPRequestHandler
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _utils import CORS_HEADERS, safe
import yfinance as yf

INDICES = [
    {"name":"NIFTY 50",   "sym":"^NSEI"},
    {"name":"BANK NIFTY", "sym":"^NSEBANK"},
    {"name":"SENSEX",     "sym":"^BSESN"},
    {"name":"FIN NIFTY",  "sym":"NIFTY_FIN_SERVICE.NS"},
    {"name":"MIDCAP 150", "sym":"^NSEMDCP150"},
    {"name":"IT NIFTY",   "sym":"^CNXIT"},
]

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        results = []
        for idx in INDICES:
            try:
                h = yf.Ticker(idx["sym"]).history(period="5d", auto_adjust=True)
                if len(h) >= 2:
                    cur  = round(float(h["Close"].iloc[-1]), 2)
                    prev = round(float(h["Close"].iloc[-2]), 2)
                    chg  = round(cur - prev, 2)
                    pct  = round(chg / prev * 100, 2) if prev > 0 else 0
                else:
                    cur = chg = pct = 0
                results.append({"name":idx["name"],"sym":idx["sym"],"price":cur,
                                "change":chg,"pct":pct,"direction":"up" if chg>=0 else "down"})
            except:
                results.append({"name":idx["name"],"sym":idx["sym"],
                               "price":0,"change":0,"pct":0,"direction":"neutral"})

        self.send_response(200)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(json.dumps(results).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
