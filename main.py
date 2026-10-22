import asyncio
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

sys.stdout.reconfigure(encoding='utf-8')

# 1. Health check HTTP Server for Render Free Tier Web Service
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
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

async def main():
    # Start HTTP health server in daemon thread
    t = threading.Thread(target=start_http_server, daemon=True)
    t.start()

    # Run Bot Service
    from bot import main as run_bot
    await run_bot()

if __name__ == "__main__":
    asyncio.run(main())
