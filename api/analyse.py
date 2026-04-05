from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _utils import CORS_HEADERS, yf_sym, safe, fmt_cap, score_stock, groq_analysis, SECTOR_PE
import yfinance as yf
import numpy as np
from datetime import datetime

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Extract symbol from path: /api/analyse?sym=RELIANCE
        q = parse_qs(urlparse(self.path).query)
        sym = (q.get("sym", [""])[0] or q.get("symbol", [""])[0]).upper().strip()

        if not sym:
            self.send_response(400)
            for k, v in CORS_HEADERS.items(): self.send_header(k, v)
            self.end_headers()
            self.wfile.write(json.dumps({"error":"sym parameter required"}).encode())
            return

        try:
            result = fetch_and_analyse(sym)
            self.send_response(200)
            for k, v in CORS_HEADERS.items(): self.send_header(k, v)
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception as e:
            self.send_response(404 if "No data" in str(e) else 500)
            for k, v in CORS_HEADERS.items(): self.send_header(k, v)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        for k, v in CORS_HEADERS.items(): self.send_header(k, v)
        self.end_headers()


def fetch_and_analyse(sym: str) -> dict:
    ysym = yf_sym(sym)
    ticker = yf.Ticker(ysym)

    # Fetch 2yr history
    hist = ticker.history(period="2y", auto_adjust=True)
    if hist.empty:
        ticker = yf.Ticker(sym + ".BO")
        hist = ticker.history(period="2y", auto_adjust=True)
    if hist.empty:
        raise ValueError(f"No data found for '{sym}'. Use a valid NSE symbol like RELIANCE, TCS, HDFCBANK.")

    # Build OHLCV series
    series = []
    for dt, row in hist.iterrows():
        c = round(float(row.get("Close", 0)), 2)
        if c <= 0: continue
        series.append({
            "time": dt.strftime("%Y-%m-%d"),
            "open": round(float(row.get("Open", c)), 2),
            "high": round(float(row.get("High", c)), 2),
            "low":  round(float(row.get("Low",  c)), 2),
            "close": c,
            "volume": int(row.get("Volume", 0)),
        })
    if len(series) < 10:
        raise ValueError(f"Insufficient price data for '{sym}'")

    # Fundamentals
    full_info = {}
    try: full_info = ticker.info
    except: pass

    g = lambda k, d=0.0: safe(full_info.get(k, d), d)

    cur   = round(g("currentPrice") or g("regularMarketPrice") or series[-1]["close"], 2)
    prev  = round(g("previousClose") or (series[-2]["close"] if len(series)>1 else cur), 2)
    chg   = round(cur - prev, 2)
    pct   = round(chg/prev*100 if prev>0 else 0, 2)

    closes_arr = np.array([s["close"] for s in series])
    h52 = round(g("fiftyTwoWeekHigh") or float(np.array([s["high"] for s in series[-252:]]).max()), 2)
    l52 = round(g("fiftyTwoWeekLow")  or float(np.array([s["low"]  for s in series[-252:]]).min()), 2)
    mc  = g("marketCap")
    pe  = round(g("trailingPE"), 1) if g("trailingPE") else None
    pb  = round(g("priceToBook"), 2) if g("priceToBook") else None
    sector   = full_info.get("sector", "") or ""
    industry = full_info.get("industry", "") or ""
    name     = full_info.get("longName") or full_info.get("shortName") or sym
    desc     = (full_info.get("longBusinessSummary","") or "")[:500]

    fd_data = {
        "sector": sector, "beta": g("beta",1),
        "trailing_pe": g("trailingPE"), "price_to_book": g("priceToBook"),
        "revenue_growth": g("revenueGrowth"), "earnings_growth": g("earningsGrowth"),
        "profit_margins": g("profitMargins"), "return_on_equity": g("returnOnEquity"),
        "return_on_assets": g("returnOnAssets"), "debt_to_equity": g("debtToEquity"),
        "held_percent_institutions": g("heldPercentInstitutions"),
        "held_percent_insiders": g("heldPercentInsiders"),
    }

    eng = score_stock(fd_data, series)
    spe = SECTOR_PE.get(sector, 22)

    # Groq AI analysis
    groq_text = groq_analysis({
        "sym":sym,"name":name,"sector":sector,"price":cur,"h52":h52,"l52":l52,
        "pe":f"{pe:.1f}" if pe else "N/A","pb":f"{pb:.1f}" if pb else "N/A",
        "spe":spe,"mc_fmt":fmt_cap(mc),
        "rg": round(g("revenueGrowth",0)*100,2),
        "pm": round(g("profitMargins",0)*100,2),
        "roe":round(g("returnOnEquity",0)*100,2),
        "inst":round(g("heldPercentInstitutions",0)*100,2),
        "beta":round(g("beta",1),2),
        **eng,
    })

    return {
        "sym":sym,"name":name,"sector":sector,"industry":industry,
        "description":desc,"exchange":full_info.get("exchange","NSE"),
        "price":cur,"change":chg,"pct":pct,
        "open": round(g("regularMarketOpen") or series[-1]["open"], 2),
        "high": round(g("regularMarketDayHigh") or series[-1]["high"], 2),
        "low":  round(g("regularMarketDayLow")  or series[-1]["low"],  2),
        "vol":  int(g("regularMarketVolume") or series[-1]["volume"]),
        "h52":h52,"l52":l52,"mc":mc,"mc_fmt":fmt_cap(mc),
        "pe":pe,"pb":pb,"spe":spe,
        "eps":  round(g("trailingEps"),2) if g("trailingEps") else None,
        "beta": round(g("beta",1),2),
        "div_yield": round(g("dividendYield",0)*100,2),
        "rg":  round(g("revenueGrowth",0)*100,2),
        "pm":  round(g("profitMargins",0)*100,2),
        "roe": round(g("returnOnEquity",0)*100,2),
        "roa": round(g("returnOnAssets",0)*100,2),
        "op_margin":round(g("operatingMargins",0)*100,2),
        "eg":  round(g("earningsGrowth",0)*100,2),
        "de":  round(g("debtToEquity",0)/100,2),
        "inst":    round(g("heldPercentInstitutions",0)*100,2),
        "insiders":round(g("heldPercentInsiders",0)*100,2),
        "target_price":round(g("targetMeanPrice"),2) if g("targetMeanPrice") else None,
        "analyst_count":int(g("numberOfAnalystOpinions",0)),
        "ma50": round(float(np.mean(closes_arr[-50:])),2) if len(closes_arr)>=50 else cur,
        "ma200":round(float(np.mean(closes_arr[-200:])),2) if len(closes_arr)>=200 else cur,
        **eng,
        "series":series,
        "groq_text":groq_text,
        "analysed_at":datetime.utcnow().isoformat()+"Z",
    }
