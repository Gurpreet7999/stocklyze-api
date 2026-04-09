import sys
import os
import json

# add api folder to path
sys.path.append(os.path.join(os.path.dirname(__file__), "api"))

from fastapi import FastAPI
import analyse  # import full module

app = FastAPI()


@app.get("/api/analyse")
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
