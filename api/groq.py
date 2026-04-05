from http.server import BaseHTTPRequestHandler
import json
import os
import requests

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

class handler(BaseHTTPRequestHandler):
    def _set_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors()
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body or "{}")

            prompt = data.get("prompt", "Say hello from Groq + Vercel.")
            model = data.get("model", "llama-3.3-70b-versatile")

            if not GROQ_API_KEY:
                raise ValueError("GROQ_API_KEY not set")

            groq_resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2,
                },
                timeout=30,
            )

            groq_resp.raise_for_status()
            resp_json = groq_resp.json()
            content = resp_json["choices"][0]["message"]["content"]

            self.send_response(200)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "content": content}).encode())
        except Exception as e:
            self.send_response(500)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": False,
                "error": str(e)
            }).encode())
