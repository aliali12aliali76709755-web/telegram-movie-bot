import urllib.request
import json

api_key = 'rnd_S96xwl0b7gxzHZ45Lbb8oO8cu66s'
req = urllib.request.Request('https://api.render.com/v1/services', headers={
    'Authorization': f'Bearer {api_key}',
    'Accept': 'application/json'
})

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        print('Total Services:', len(data))
        for item in data:
            s = item.get('service', {})
            details = s.get('serviceDetails', {})
            print(f"Service: {s.get('name')} | Type: {s.get('type')} | Plan: {details.get('plan')} | Region: {details.get('region')}")
except Exception as e:
    print('Error:', e)
