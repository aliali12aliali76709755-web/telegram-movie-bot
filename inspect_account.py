import asyncio
import os
import sys
import json

# Ensure utf-8 output in Windows cmd/powershell
sys.stdout.reconfigure(encoding='utf-8')

from telethon import TelegramClient
from telethon.tl.functions.messages import GetDialogFiltersRequest

API_ID = 32374871
API_HASH = "88bae070f4b4fb8f348eb6a16e8879d2"
SESSION_PATH = os.path.join(os.path.dirname(__file__), "user_session")

async def main():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("NOT_AUTHORIZED")
        return

    print("Fetching dialogs...")
    dialogs = await client.get_dialogs(limit=100)
    
    print("\n--- ALL DIALOGS ---")
    for d in dialogs:
        chat_type = "User"
        if d.is_channel:
            chat_type = "Channel"
        elif d.is_group:
            chat_type = "Group"
            
        pinned_str = "[PINNED] " if d.pinned else ""
        print(f"{pinned_str}[{chat_type}] '{d.title or d.name}' | ID: {d.id}")

    print("\n--- FOLDERS (FILTERS) ---")
    try:
        filters = await client(GetDialogFiltersRequest())
        for f in filters:
            if hasattr(f, 'title'):
                title = f.title
                print(f"Folder: '{title}' (ID: {f.id})")
                if hasattr(f, 'include_peers'):
                    print(f"  Includes {len(f.include_peers)} peers")
                    for p in f.include_peers:
                        try:
                            entity = await client.get_entity(p)
                            ent_name = getattr(entity, 'title', None) or getattr(entity, 'first_name', None) or getattr(entity, 'username', 'Unknown')
                            is_bot = getattr(entity, 'bot', False)
                            print(f"    - {'[BOT] ' if is_bot else ''}{ent_name} (ID: {entity.id})")
                        except Exception as e:
                            print(f"    - Peer {p} error: {e}")
    except Exception as e:
        print(f"Could not fetch filters: {e}")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
