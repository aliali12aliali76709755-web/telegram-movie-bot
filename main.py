import asyncio
import os
import sys
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

sys.stdout.reconfigure(encoding='utf-8')

# 1. Health check & Status HTTP Server for Render
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

            bot_status = "unknown"
            bot_username = None
            try:
                from bot import bot
                if bot and bot.is_connected():
                    bot_status = "connected"
                    bot_username = "@zxeeabot"
                else:
                    bot_status = "disconnected"
            except Exception as b_err:
                bot_status = f"error: {b_err}"

            resp = {
                "status": "online",
                "service": "telegram_movie_bot",
                "bot": bot_status,
                "bot_username": bot_username,
                "mongodb": db_status,
                "mongo_error": mongo_err,
                "stats": stats
            }
            body = json.dumps(resp, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
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
    print(f"HTTP Health Server listening on 0.0.0.0:{port}...")
    server.serve_forever()

def keep_alive_watchdog():
    """
    Continuous watchdog thread that runs every 50 seconds:
    - Pings public Render URL (https://telegram-movie-bot-jno5.onrender.com/status) to keep the Render container awake 24/7.
    - Pings local HTTP server to verify web service health.
    - Monitors Telegram Bot connectivity and logs heartbeat.
    """
    import urllib.request
    import time
    from datetime import datetime

    raw_public = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-movie-bot-jno5.onrender.com").rstrip("/")
    public_url = f"{raw_public}/status"
    port = int(os.environ.get("PORT", 10000))
    local_url = f"http://127.0.0.1:{port}/status"

    print(f"🔄 Keep-Alive Watchdog started. Monitoring every 50s...")
    time.sleep(15)  # wait for initial startup

    while True:
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        # 1. Ping Render Public URL to reset 15-minute inactivity timer
        try:
            req = urllib.request.Request(
                public_url,
                headers={"User-Agent": "Render-KeepAlive-Engine/2.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                pass
        except Exception:
            # Fallback to local ping if external fails
            try:
                with urllib.request.urlopen(local_url, timeout=5) as l_resp:
                    pass
            except Exception:
                pass

        # 2. Check Bot Connection
        try:
            from bot import bot
            if not bot or not bot.is_connected():
                print(f"⚠️ [{now_str}] Watchdog Alert: Bot disconnected! Reconnection will trigger.", flush=True)
            else:
                print(f"💓 [{now_str}] Keep-Alive Heartbeat: Server & Bot @zxeeabot are LIVE & HEALTHY.", flush=True)
        except Exception as b_err:
            print(f"⚠️ [{now_str}] Watchdog Bot check note: {b_err}", flush=True)

        time.sleep(50)

async def main():
    # Start HTTP health server in daemon thread
    t_http = threading.Thread(target=start_http_server, daemon=True)
    t_http.start()

    # Start 1-Minute Keep-Alive Watchdog in daemon thread
    t_keepalive = threading.Thread(target=keep_alive_watchdog, daemon=True)
    t_keepalive.start()

    # Run Bot Service
    from bot import main as run_bot
    await run_bot()

if __name__ == "__main__":
    asyncio.run(main())

