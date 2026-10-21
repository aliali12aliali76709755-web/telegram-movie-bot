import asyncio
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
import cryptg
from telethon import TelegramClient
from database import get_connection, mark_transferred

API_ID = 32374871
API_HASH = "88bae070f4b4fb8f348eb6a16e8879d2"
BOT_USERNAME = "@zxeeabot"
STORAGE_CHANNEL = -1004477353424

USER_SESSION_PATH = os.path.join(os.path.dirname(__file__), "user_session")
TEMP_DIR = os.path.join(os.path.dirname(__file__), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

SEASON_NAMES = {
    1: "الأول", 2: "الثاني", 3: "الثالث", 4: "الرابع",
    5: "الخامس", 6: "السادس", 7: "السابع", 8: "الثامن",
    9: "التاسع", 10: "العاشر"
}

def format_caption(item):
    if item['is_series']:
        s_name = SEASON_NAMES.get(item['season_num'], str(item['season_num']))
        return (
            f"🎬 **مسلسل: {item['series_title']}**\n"
            f"🍿 **الموسم {s_name} — الحلقة {item['episode_num']}**\n"
            f"✨ **عبر: {BOT_USERNAME}**"
        )
    else:
        return (
            f"🎬 **فيلم: {item['clean_title']}**\n"
            f"🌟 **الجودة: {item['quality']}**\n"
            f"✨ **عبر: {BOT_USERNAME}**"
        )

async def transfer_single_item(client, item):
    size_mb = round(item['file_size'] / (1024 * 1024), 1)
    caption = format_caption(item)
    print(f"\n[Transferring #{item['id']}] {item['clean_title']} ({size_mb} MB)...")
    
    # 1. Fetch message from source chat
    try:
        source_msg = await client.get_messages(item['source_chat_id'], ids=item['source_msg_id'])
    except Exception as e:
        print(f"Error fetching source msg #{item['source_msg_id']}: {e}")
        return False

    if not source_msg or not (source_msg.video or source_msg.document):
        print(f"No media found in source msg #{item['source_msg_id']}")
        return False

    # 2. Download media to temp file
    t0 = time.time()
    print("  -> Downloading from restricted source...")
    file_path = await client.download_media(source_msg, file=TEMP_DIR)
    dl_time = round(time.time() - t0, 1)
    print(f"  -> Downloaded in {dl_time}s to {file_path}")

    # 3. Upload to STORAGE_CHANNEL (قناة افلام)
    t1 = time.time()
    print("  -> Uploading to 'قناة افلام'...")
    sent_msg = await client.send_file(
        STORAGE_CHANNEL,
        file_path,
        caption=caption,
        supports_streaming=True
    )
    up_time = round(time.time() - t1, 1)
    print(f"  -> Uploaded successfully as Msg #{sent_msg.id} in {up_time}s!")

    # 4. Clean up local temp file
    if os.path.exists(file_path):
        os.remove(file_path)

    # 5. Mark transferred in database
    mark_transferred(
        source_chat_id=item['source_chat_id'],
        source_msg_id=item['source_msg_id'],
        target_msg_id=sent_msg.id
    )
    return True

async def main(filter_title=None, limit=20):
    client = TelegramClient(USER_SESSION_PATH, API_ID, API_HASH)
    await client.connect()
    
    conn = get_connection()
    cur = conn.cursor()
    if filter_title:
        cur.execute("""
        SELECT * FROM media_items 
        WHERE is_transferred = 0 AND (series_title LIKE ? OR clean_title LIKE ?)
        ORDER BY season_num ASC, episode_num ASC LIMIT ?
        """, (f"%{filter_title}%", f"%{filter_title}%", limit))
    else:
        cur.execute("""
        SELECT * FROM media_items 
        WHERE is_transferred = 0
        ORDER BY id DESC LIMIT ?
        """, (limit,))
        
    items = [dict(r) for r in cur.fetchall()]
    conn.close()

    print(f"Found {len(items)} untransferred items to process.")
    transferred_count = 0
    for it in items:
        try:
            success = await transfer_single_item(client, it)
            if success:
                transferred_count += 1
        except Exception as e:
            print(f"Failed to transfer item #{it['id']}: {e}")
            await asyncio.sleep(2)

    print(f"\nBatch completed! Successfully transferred {transferred_count}/{len(items)} items to 'قناة افلام'.")
    await client.disconnect()

if __name__ == "__main__":
    filter_arg = sys.argv[1] if len(sys.argv) > 1 else None
    limit_arg = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    asyncio.run(main(filter_arg, limit_arg))
