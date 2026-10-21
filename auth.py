import asyncio
import os
import sys
import json
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

API_ID = 32374871
API_HASH = "88bae070f4b4fb8f348eb6a16e8879d2"
PHONE = "+8801356112990"
SESSION_PATH = os.path.join(os.path.dirname(__file__), "user_session")
AUTH_DATA_FILE = os.path.join(os.path.dirname(__file__), "auth_data.json")

async def request_code():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()
    
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"ALREADY_AUTHORIZED: {me.first_name} (@{me.username}) - ID: {me.id}")
        await client.disconnect()
        return
        
    print(f"Sending code request to {PHONE}...")
    res = await client.send_code_request(PHONE)
    with open(AUTH_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"phone_code_hash": res.phone_code_hash, "phone": PHONE}, f)
    print("CODE_REQUESTED_SUCCESSFULLY")
    await client.disconnect()

async def submit_code(code, password=None):
    if not os.path.exists(AUTH_DATA_FILE):
        print("ERROR: auth_data.json not found. Run request_code first.")
        return
        
    with open(AUTH_DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()
    
    try:
        await client.sign_in(PHONE, code, phone_code_hash=data["phone_code_hash"])
        me = await client.get_me()
        print(f"LOGIN_SUCCESS: {me.first_name} (@{me.username}) - ID: {me.id}")
    except SessionPasswordNeededError:
        if not password:
            print("2FA_PASSWORD_REQUIRED")
        else:
            await client.sign_in(password=password)
            me = await client.get_me()
            print(f"LOGIN_SUCCESS_2FA: {me.first_name} (@{me.username}) - ID: {me.id}")
    except Exception as e:
        print(f"LOGIN_ERROR: {e}")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--code":
        code = sys.argv[2]
        pwd = sys.argv[3] if len(sys.argv) > 3 else None
        asyncio.run(submit_code(code, pwd))
    else:
        asyncio.run(request_code())
