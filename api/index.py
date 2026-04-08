import json, os
from urllib.parse import parse_qs, urlparse

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}

DATA = {}
try:
    with open(os.path.join(os.path.dirname(__file__), "../data/stocks.json")) as f:
        DATA = json.load(f)
except:
    DATA = {}

def app(request):
    qs = parse_qs(urlparse(request.get("url", "")).query)
    sym = (qs.get("sym", [""])[0]).upper().strip()

    if not sym:
        return res({"error": "symbol required"})

    if sym not in DATA:
        return res({"error": "Stock not found or not cached"})

    return res(DATA[sym])

def res(data):
    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps(data)
    }
