import asyncio
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

sys.stdout.reconfigure(encoding='utf-8')

# 1. Health check HTTP Server for Render
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status":"online","service":"telegram_movie_bot"}')

    def log_message(self, format, *args):
        return # suppress access logs

def start_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"HTTP Health Server running on port {port}...")
    server.serve_forever()

# 2. Telegram Bot and Background Transfer Runner
async def background_transfer_loop():
    from transfer_worker import main as run_transfer
    await asyncio.sleep(10) # wait for bot to start cleanly
    print("Background Transfer Worker started!")
    while True:
        try:
            print("\n[Worker] Running transfer batch...")
            await run_transfer(limit=5)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[Worker Error] {e}")
            await asyncio.sleep(30)

async def main():
    # Start HTTP health server in daemon thread
    t = threading.Thread(target=start_http_server, daemon=True)
    t.start()

    from bot import bot, BOT_TOKEN, user_client
    print("Starting User Client on Cloud Server...")
    await user_client.connect()

    print("Starting Bot @zxeeabot on Cloud Server...")
    await bot.start(bot_token=BOT_TOKEN)
    print("Cloud Server: Bot and User Client are LIVE!")

    # Run bot and transfer loop concurrently
    await asyncio.gather(
        bot.run_until_disconnected(),
        user_client.run_until_disconnected(),
        background_transfer_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())
