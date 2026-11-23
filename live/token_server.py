"""Small token service for the live demo page (local version).

Run: python live/token_server.py
POST /token  {"mode": "new"|"existing", "persona": "...", "business": "...", "keyterms": [...], "passcode": "..."}
  -> {"token": "...", "url": "wss://...", "room": "..."}
Keeps the LiveKit secret off the web page. Set DEMO_PASSCODE to require a passcode; MAX tokens per minute is capped.
The deployed version (Vercel) mirrors this logic.
"""
import json
import os
import secrets
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv
from livekit import api

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))
PASSCODE = os.environ.get("DEMO_PASSCODE", "")
RATE_PER_MIN = int(os.environ.get("TOKENS_PER_MIN", "6"))
_recent = []


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        self._send(200, {"ok": True, "passcode_required": bool(PASSCODE)})

    def do_POST(self):
        now = time.time()
        _recent[:] = [t for t in _recent if now - t < 60]
        if len(_recent) >= RATE_PER_MIN:
            return self._send(429, {"error": "Too many calls started in the last minute. Try again shortly."})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "Bad request"})
        if PASSCODE and body.get("passcode") != PASSCODE:
            return self._send(401, {"error": "That passcode is not right."})
        _recent.append(now)
        cfg = {"mode": "existing" if body.get("mode") == "existing" else "new",
               "persona": str(body.get("persona") or "")[:30], "business": str(body.get("business") or "")[:60],
               "keyterms": [str(k)[:40] for k in (body.get("keyterms") or [])][:30],
               "hours": str(body.get("hours") or "")[:60], "voice": str(body.get("voice") or "")[:40],
               "greeting": str(body.get("greeting") or "")[:300], "rules": str(body.get("rules") or "")[:700],
               "service_area": str(body.get("service_area") or "")[:120],
               "services": [str(k)[:40] for k in (body.get("services") or [])][:6]}
        room = f"demo-{secrets.token_hex(4)}"
        token = (api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
                 .with_identity(f"caller-{secrets.token_hex(3)}").with_name("Caller")
                 .with_metadata(json.dumps(cfg))
                 .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True,
                                              can_publish_data=True))
                 .with_ttl(timedelta(minutes=10)).to_jwt())
        self._send(200, {"token": token, "url": os.environ["LIVEKIT_URL"], "room": room})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("TOKEN_PORT", "8787"))
    print(f"token server on http://localhost:{port} (passcode {'on' if PASSCODE else 'off'})")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
