import asyncio
import os
import sys
import json
import time
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Ring buffer to capture last 200 stdout/stderr log lines for /logs endpoint
_LOG_BUFFER = deque(maxlen=200)

class LogCapture:
    def __init__(self, original):
        self.original = original
    def write(self, s):
        try:
            self.original.write(s)
            self.original.flush()
        except Exception:
            pass
        if s and s.strip():
            _LOG_BUFFER.append(s.strip())
    def flush(self):
        try:
            self.original.flush()
        except Exception:
            pass
    def reconfigure(self, **kwargs):
        if hasattr(self.original, 'reconfigure'):
            try:
                return self.original.reconfigure(**kwargs)
            except Exception:
                pass
    def __getattr__(self, name):
        return getattr(self.original, name)

sys.stdout = LogCapture(sys.stdout)
sys.stderr = LogCapture(sys.stderr)

BOT_RUNTIME_STATE = {
    "connected": False,
    "username": "@zxeeabot",
    "id": 8884645024,
    "started_at": None,
    "last_heartbeat": None,
    "last_error": None
}

# 1. Health check, Status & Live Logs HTTP Server
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/status", "/health"):
            mongo_err = None
            stats = {}
            db_status = "unknown"
            try:
                import database
                stats = database.get_stats()
                db_status = "connected"
            except Exception as e:
                db_status = "failed"
                mongo_err = str(e)

            bot_status = "connected" if BOT_RUNTIME_STATE["connected"] else "disconnected"

            resp = {
                "status": "online",
                "service": "telegram_movie_bot",
                "bot": bot_status,
                "bot_username": BOT_RUNTIME_STATE["username"],
                "bot_id": BOT_RUNTIME_STATE["id"],
                "bot_started_at": BOT_RUNTIME_STATE["started_at"],
                "last_heartbeat": BOT_RUNTIME_STATE["last_heartbeat"],
                "mongodb": db_status,
                "mongo_error": mongo_err,
                "stats": stats
            }
            body = json.dumps(resp, ensure_ascii=False, indent=2).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/logs":
            body = "\n".join(_LOG_BUFFER).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"online","service":"telegram_movie_bot"}')

    def log_message(self, format, *args):
        return  # suppress verbose access logs

def start_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"HTTP Server listening on 0.0.0.0:{port} (/status, /logs)...")
    server.serve_forever()

def keep_alive_watchdog():
    """
    Continuous watchdog thread that runs every 50 seconds:
    - Pings public Render URL to keep the container awake 24/7.
    - Updates heartbeat.
    """
    import urllib.request

    raw_public = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-movie-bot-jno5.onrender.com").rstrip("/")
    public_url = f"{raw_public}/status"
    port = int(os.environ.get("PORT", 10000))
    local_url = f"http://127.0.0.1:{port}/status"

    print("🔄 Keep-Alive Watchdog started. Monitoring every 50s...")
    time.sleep(10)

    while True:
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        BOT_RUNTIME_STATE["last_heartbeat"] = now_str

        # 1. Ping Render Public URL to reset 15-minute inactivity timer
        try:
            req = urllib.request.Request(
                public_url,
                headers={"User-Agent": "Render-KeepAlive-Engine/2.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                pass
        except Exception:
            try:
                with urllib.request.urlopen(local_url, timeout=5) as l_resp:
                    pass
            except Exception:
                pass

        time.sleep(50)

async def main():
    # Start HTTP server in daemon thread
    t_http = threading.Thread(target=start_http_server, daemon=True)
    t_http.start()

    # Start 1-Minute Keep-Alive Watchdog in daemon thread
    t_keepalive = threading.Thread(target=keep_alive_watchdog, daemon=True)
    t_keepalive.start()

    # Run Bot Service in main event loop
    from bot import main as run_bot
    await run_bot(state_dict=BOT_RUNTIME_STATE)

if __name__ == "__main__":
    asyncio.run(main())
