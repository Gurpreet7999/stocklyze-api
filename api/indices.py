import json

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}

def handler(request):
    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps([])
    }
