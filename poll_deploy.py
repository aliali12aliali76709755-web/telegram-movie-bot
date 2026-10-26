import urllib.request
import json
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

API_KEY = "rnd_QbfKeHw9bSHL3hPa1ehowcKrxsBj"
SVC_ID = "srv-dbcmcfo473hc739hkvs0"
DEPLOY_ID = "dep-dbflhn8n74is73es7rs0"
url = f"https://api.render.com/v1/services/{SVC_ID}/deploys/{DEPLOY_ID}"
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json"
}

for i in range(30):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            status = data.get('status')
            print(f"[{i+1}/30] Deploy Status: {status}")
            if status == "live":
                print("🎉 Deploy is LIVE!")
                break
            elif status in ["build_failed", "canceled", "deactivated"]:
                print(f"❌ Deploy ended with status: {status}")
                break
    except Exception as e:
        print(f"Check error: {e}")
    time.sleep(10)
