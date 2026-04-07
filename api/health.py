from datetime import datetime
import json, os

def handler(request):
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps({
            "status": "ok",
            "service": "Stocklyze API v5",
            "groq": bool(os.environ.get("GROQ_API_KEY","")),
            "ts": datetime.utcnow().isoformat() + "Z",
        })
    }
