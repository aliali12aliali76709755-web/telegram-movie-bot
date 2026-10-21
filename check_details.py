import asyncio
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
from telethon import TelegramClient

API_ID = 32374871
API_HASH = "88bae070f4b4fb8f348eb6a16e8879d2"
SESSION_PATH = os.path.join(os.path.dirname(__file__), "user_session")

async def main():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()
    
    print("Checking 'قناة افلام' details:")
    ent = await client.get_entity(-1004477353424)
    print(f"Title: {ent.title}")
    
    # Check messages in 'قناة افلام'
    total = 0
    async for m in client.iter_messages(ent):
        total += 1
        print(f"Msg {m.id}: date={m.date}, text={m.text}, media={type(m.media)}")
    print(f"Total messages in 'قناة افلام': {total}")
    
    # Check 'me' (Saved Messages)
    saved_total = 0
    saved_videos = 0
    async for m in client.iter_messages('me', limit=20):
        saved_total += 1
        if m.video or m.document:
            saved_videos += 1
    print(f"Saved messages (الرسائل المحفوظة): {saved_total} msgs, {saved_videos} media")
    
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
