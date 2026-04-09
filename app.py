import sys
import os
import json

# add api folder to path
sys.path.append(os.path.join(os.path.dirname(__file__), "api"))

from fastapi import FastAPI
import analyse  # import full module

app = FastAPI()

@app.get("/api/search")
def search(q: str):
    stocks = [
        {"sym": "RELIANCE", "name": "Reliance Industries", "sector": "Energy"},
        {"sym": "TCS", "name": "Tata Consultancy Services", "sector": "IT"},
        {"sym": "INFY", "name": "Infosys", "sector": "IT"},
        {"sym": "HDFCBANK", "name": "HDFC Bank", "sector": "Banking"},
        {"sym": "ICICIBANK", "name": "ICICI Bank", "sector": "Banking"},
        {"sym": "SBIN", "name": "State Bank of India", "sector": "Banking"},
        {"sym": "ITC", "name": "ITC Limited", "sector": "FMCG"},
    ]

    q = q.lower()
    return [
        s for s in stocks
        if q in s["sym"].lower() or q in s["name"].lower()
    ]

@app.get("/api/indices")
def indices():
    return [
        {"name": "NIFTY 50", "price": 22450, "change": 120, "pct": 0.54},
        {"name": "SENSEX", "price": 73900, "change": -80, "pct": -0.11},
        {"name": "BANK NIFTY", "price": 48200, "change": 210, "pct": 0.44},
    ]

def run_analysis(sym: str):
    # simulate Vercel request
    request = {
        "url": f"/api/analyse?sym={sym}"
    }

    response = analyse.handler(request)

    # extract actual data
    body = response.get("body", "{}")

    try:
        return json.loads(body)
    except:
        return {"error": "Invalid response"}
