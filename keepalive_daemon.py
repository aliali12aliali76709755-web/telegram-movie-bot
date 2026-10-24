import sys
sys.stdout.reconfigure(encoding='utf-8')
import time
import urllib.request
import json
from datetime import datetime

URL = "https://telegram-movie-bot-jno5.onrender.com/status"

def ping():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    t0 = time.time()
    try:
        req = urllib.request.Request(
            URL,
            headers={"User-Agent": "External-KeepAlive-Daemon/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            elapsed = round((time.time() - t0) * 1000, 1)
            data = json.loads(resp.read().decode('utf-8'))
            print(f"[{now}] [OK 200] ({elapsed}ms) | Bot: {data.get('bot')} | DB: {data.get('mongodb')}")
    except Exception as e:
        elapsed = round((time.time() - t0) * 1000, 1)
        print(f"[{now}] [ERROR] ({elapsed}ms): {e}")

def main():
    print("=" * 60)
    print(f"🚀 Render 1-Minute Keep-Alive Watchdog Daemon")
    print(f"Target: {URL}")
    print("=" * 60)
    while True:
        ping()
        time.sleep(60)

if __name__ == "__main__":
    main()
