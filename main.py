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

# 1. Health check, Status, Mini App & API HTTP Server
class HealthHandler(BaseHTTPRequestHandler):
    def send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        import urllib.parse
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        # 1. Telegram Mini App Frontend (HTML/SPA)
        if path in ("/", "/app", "/miniapp", "/webapp"):
            html_path = os.path.join(os.path.dirname(__file__), "webapp", "index.html")
            if os.path.exists(html_path):
                with open(html_path, "r", encoding="utf-8") as f:
                    content = f.read()
                body = content.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
                return
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"Mini App template not found.")
                return

        # 2. Mini App API: List Movies (Paginated, Searchable, Filterable)
        elif path == "/api/movies":
            page = int(params.get('page', ['1'])[0])
            limit = min(50, max(1, int(params.get('limit', ['24'])[0])))
            query = params.get('query', [None])[0] or params.get('q', [None])[0]
            genre = params.get('genre', [None])[0]
            sort = params.get('sort', ['featured'])[0]

            try:
                import database
                res = database.get_miniapp_movies(page=page, limit=limit, query=query, genre=genre, sort=sort)
                body = json.dumps({"status": "success", **res}, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'public, max-age=60')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # 3. Mini App API: Single Movie Details
        elif path.startswith("/api/movie/"):
            m_id_str = path.replace("/api/movie/", "").strip("/")
            try:
                m_id = int(m_id_str)
                import database
                item = database.get_movie_by_id(m_id)
                if item:
                    body = json.dumps({"status": "success", "movie": item}, ensure_ascii=False).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Cache-Control', 'public, max-age=300')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(b'{"status": "error", "message": "Movie not found"}')
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # 4. Mini App API: Featured Carousel Movies
        elif path == "/api/featured":
            limit = min(12, max(1, int(params.get('limit', ['6'])[0])))
            try:
                import database
                featured = database.get_featured_movies(limit=limit)
                body = json.dumps({"status": "success", "items": featured}, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'public, max-age=120')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # 5. Mini App API: Available Genres
        elif path == "/api/genres":
            try:
                import database
                genres = database.get_genres_summary()
                body = json.dumps({"status": "success", "genres": genres}, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'public, max-age=300')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # 6. Status & Health Check
        elif path in ("/status", "/health"):
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
                "stats": stats
            }
            body = json.dumps(resp, ensure_ascii=False, indent=2).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        # 7. Secure Live Logs
        elif path.startswith("/logs"):
            if params.get('key', [''])[0] != '6641619062':
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Access Denied"}')
                return

            body = "\n".join(_LOG_BUFFER).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)
            return

        # Default fallback
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b'{"status":"online","service":"telegram_movie_bot","miniapp":"/app"}')

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
    # 0. Initialize Database Schema and Indexes (both MongoDB and SQLite)
    try:
        import database
        database.init_db()
        print("✅ Database schema and indexes initialized.")
    except Exception as e:
        print(f"Notice during init_db: {e}")

    # 1. Start HTTP Server in daemon thread (serves Mini App & APIs)
    t_http = threading.Thread(target=start_http_server, daemon=True)
    t_http.start()

    # 2. Start 1-Minute Keep-Alive Watchdog in daemon thread
    t_keepalive = threading.Thread(target=keep_alive_watchdog, daemon=True)
    t_keepalive.start()

    # 3. Start Background Movie Metadata & Poster Enrichment Worker
    try:
        import metadata_enricher
        metadata_enricher.start_background_enrichment_worker()
        print("🚀 Background movie metadata & poster enrichment daemon launched!")
    except Exception as e:
        print(f"Notice starting metadata enricher: {e}")

    # 4. Run Telegram Bot Service in main event loop
    from bot import main as run_bot
    await run_bot(state_dict=BOT_RUNTIME_STATE)

if __name__ == "__main__":
    asyncio.run(main())
