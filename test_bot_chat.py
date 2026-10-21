import asyncio
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
from telethon import TelegramClient

API_ID = 32374871
API_HASH = "88bae070f4b4fb8f348eb6a16e8879d2"
SESSION_PATH = os.path.join(os.path.dirname(__file__), "user_session")
BOT_USERNAME = "zxeeabot"

async def main():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()
    
    print(f"Sending /start to @{BOT_USERNAME}...")
    await client.send_message(BOT_USERNAME, "/start")
    
    print("Waiting for bot reply...")
    await asyncio.sleep(3)
    
    async for msg in client.iter_messages(BOT_USERNAME, limit=2):
        if msg.out:
            print(f"User Sent: {msg.text}")
        else:
            print(f"Bot Replied:\n{msg.text}")
            
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
