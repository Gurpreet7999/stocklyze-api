import requests, json, time, os

API_KEY = "7FWMCB6KRCIOBHGP"

STOCKS = [
    "RELIANCE.BSE",
    "TCS.BSE",
    "INFY.BSE",
    "HDFCBANK.BSE",
    "ICICIBANK.BSE",
    "SBIN.BSE",
    "ITC.BSE"
]

DATA = {}

for sym in STOCKS:
    print("Fetching:", sym)

    url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={sym}&apikey={API_KEY}"

    try:
        r = requests.get(url, timeout=10)
        d = r.json().get("Global Quote", {})

        if not d:
            continue

        DATA[sym.split(".")[0]] = {
            "sym": sym.split(".")[0],
            "price": float(d.get("05. price", 0)),
            "change": float(d.get("09. change", 0)),
            "pct": d.get("10. change percent", "0%"),
        }

        time.sleep(12)  # ⚠️ rate limit बचाने के लिए

    except Exception as e:
        print("Error:", e)

# save file
os.makedirs("data", exist_ok=True)

with open("data/stocks.json", "w") as f:
    json.dump(DATA, f, indent=2)

print("✅ Data saved to data/stocks.json")
