import asyncio
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

from telethon import TelegramClient
from telethon.tl.types import Channel, MessageMediaDocument

API_ID = 32374871
API_HASH = "88bae070f4b4fb8f348eb6a16e8879d2"
SESSION_PATH = os.path.join(os.path.dirname(__file__), "user_session")
CHANNEL_ID = -1004477353424

async def main():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()
    
    entity = await client.get_entity(CHANNEL_ID)
    print(f"Channel Title: {entity.title}")
    print(f"Channel ID: {entity.id}")
    print(f"Restricted (noforwards): {getattr(entity, 'noforwards', False)}")
    
    # Check full channel info (linked chat / discussion group)
    from telethon.tl.functions.channels import GetFullChannelRequest
    full_channel = await client(GetFullChannelRequest(entity))
    linked_chat_id = full_channel.full_chat.linked_chat_id
    print(f"Linked discussion group ID: {linked_chat_id}")
    
    # Get total message count
    total_messages = 0
    video_count = 0
    doc_count = 0
    text_count = 0
    
    sample_messages = []
    
    print("\nReading messages...")
    async for msg in client.iter_messages(entity, limit=200):
        total_messages += 1
        has_media = False
        media_type = "None"
        file_name = None
        file_size = 0
        
        if msg.video:
            video_count += 1
            has_media = True
            media_type = "Video"
            file_size = msg.video.size
            for attr in msg.video.attributes:
                if hasattr(attr, 'file_name'):
                    file_name = attr.file_name
        elif msg.document:
            doc_count += 1
            has_media = True
            media_type = "Document"
            file_size = msg.document.size
            for attr in msg.document.attributes:
                if hasattr(attr, 'file_name'):
                    file_name = attr.file_name
        else:
            text_count += 1
            
        if len(sample_messages) < 15:
            sample_messages.append({
                "id": msg.id,
                "date": str(msg.date),
                "media_type": media_type,
                "file_name": file_name,
                "file_size_mb": round(file_size / (1024 * 1024), 2) if file_size else 0,
                "text": msg.text or msg.message or ""
            })
            
    print(f"\nStats for scanned {total_messages} messages:")
    print(f"Videos: {video_count}")
    print(f"Documents: {doc_count}")
    print(f"Text-only: {text_count}")
    
    print("\n--- SAMPLE MESSAGES ---")
    for s in sample_messages:
        print(f"\n[Msg #{s['id']}] Date: {s['date']} | Type: {s['media_type']} | Size: {s['file_size_mb']} MB")
        if s['file_name']:
            print(f"File Name: {s['file_name']}")
        print(f"Text/Caption:\n{s['text'][:200]}...")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
