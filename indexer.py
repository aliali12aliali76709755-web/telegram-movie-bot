import asyncio
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
from telethon import TelegramClient
from database import init_db, add_media_item, parse_media_details, get_stats

API_ID = 32374871
API_HASH = "88bae070f4b4fb8f348eb6a16e8879d2"
SESSION_PATH = os.path.join(os.path.dirname(__file__), "user_session")

SOURCE_CHATS = [
    {"id": -1002359099671, "name": "أفلام و مسلسلات | Movies , Series"},
    {"id": -1002704261279, "name": "قروب المناقشة والطلبات"}
]

async def index_chat(client, chat_id, chat_name, limit=500):
    print(f"\nScanning '{chat_name}' (ID: {chat_id}) - limit: {limit}...")
    try:
        entity = await client.get_entity(chat_id)
    except Exception as e:
        print(f"Error accessing chat {chat_id}: {e}")
        return 0

    indexed_count = 0
    scanned = 0

    async for msg in client.iter_messages(entity, limit=limit):
        scanned += 1
        video_obj = msg.video
        doc_obj = msg.document if (msg.document and msg.document.mime_type and msg.document.mime_type.startswith('video/')) else None
        
        media_obj = video_obj or doc_obj
        if not media_obj:
            continue

        file_size = media_obj.size
        duration = 0
        file_name = None
        for attr in media_obj.attributes:
            if hasattr(attr, 'duration'):
                duration = attr.duration
            if hasattr(attr, 'file_name'):
                file_name = attr.file_name

        caption = msg.text or msg.message or ""
        parsed = parse_media_details(caption, file_name)
        media_type = "video" if video_obj else "document"

        add_media_item(
            parsed_data=parsed,
            raw_caption=caption,
            source_chat_id=chat_id,
            source_msg_id=msg.id,
            file_size=file_size,
            duration=duration,
            media_type=media_type
        )
        indexed_count += 1

    print(f"Finished '{chat_name}': Scanned {scanned} msgs, indexed {indexed_count} items.")
    return indexed_count

async def main(limit_per_chat=300):
    init_db()
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()

    for chat in SOURCE_CHATS:
        await index_chat(client, chat["id"], chat["name"], limit=limit_per_chat)

    print("\n--- INDEXING SUMMARY ---")
    stats = get_stats()
    print(f"Total items in DB: {stats['total']}")
    print(f"Distinct Series: {stats['total_series']}")
    print(f"Movies: {stats['total_movies']}")

    await client.disconnect()

if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    asyncio.run(main(limit))
