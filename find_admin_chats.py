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
    
    dialogs = await client.get_dialogs(limit=200)
    print("--- CHATS WHERE USER IS CREATOR OR ADMIN ---")
    for d in dialogs:
        if d.is_channel or d.is_group:
            ent = d.entity
            is_admin = getattr(ent, 'admin_rights', None) is not None
            is_creator = getattr(ent, 'creator', False)
            if is_admin or is_creator:
                print(f"{'CREATOR' if is_creator else 'ADMIN'}: '{d.title}' (ID: {d.id})")
                
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
