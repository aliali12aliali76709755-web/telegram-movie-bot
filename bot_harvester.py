import asyncio
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
from telethon import TelegramClient
from database import init_db, add_media_item, parse_media_details, get_connection
from titles_list import HARVEST_CATALOG, MOVIE_ALIASES
from export_registry import export_registry

API_ID = 32374871
API_HASH = "88bae070f4b4fb8f348eb6a16e8879d2"
BOT_USERNAME = "@zxeeabot"
STORAGE_CHANNEL = -1004477353424

# Primary and fallback bots from user's account
SOURCE_BOTS = [
    {"name": "بوت وي سيما", "id": 8898823458},
    {"name": "Movie Bot", "id": 7710690306},
    {"name": "NETFLIX", "id": 7453357428},
    {"name": "Netflixsbot", "id": 5930571403}
]

def get_transferred_titles():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT clean_title FROM media_items WHERE is_series = 0 AND is_transferred = 1")
        titles = [r['clean_title'].replace("🎬", "").strip().lower() for r in cursor.fetchall()]
        conn.close()
        return titles
    except Exception:
        return []

async def harvest_single_title(client, bot_info, query_text, display_title):
    bot_id = bot_info["id"]
    try:
        # Send query to bot
        await client.send_message(bot_id, query_text)
        await asyncio.sleep(2.5)

        # Get bot response message with buttons
        msg = None
        async for m in client.iter_messages(bot_id, limit=3):
            if not m.out and m.buttons:
                msg = m
                break

        if not msg or not msg.buttons:
            return False

        # Look for [مشاهدة] or [تحميل] button
        watch_btn_pos = None
        for r_idx, row in enumerate(msg.buttons):
            for c_idx, b in enumerate(row):
                if any(k in b.text for k in ["مشاهدة", "تحميل", "Watch", "Download"]):
                    watch_btn_pos = (r_idx, c_idx)
                    break
            if watch_btn_pos:
                break

        if not watch_btn_pos:
            return False

        # Click the watch/download button
        await msg.click(watch_btn_pos[0], watch_btn_pos[1])

        # Wait for video message (max 6s)
        video_msg = None
        for _ in range(6):
            await asyncio.sleep(1)
            async for m in client.iter_messages(bot_id, limit=2):
                if not m.out and m.video:
                    video_msg = m
                    break
            if video_msg:
                break

        if not video_msg:
            return False

        size_mb = video_msg.video.size // 1048576
        caption = f"🎬 {display_title}\n💾 الحجم: {size_mb} MB\n✨ عبر: {BOT_USERNAME}"

        # 0-second cloud pointer transfer
        t0 = time.time()
        sent = await client.send_file(STORAGE_CHANNEL, video_msg.media, caption=caption, supports_streaming=True)
        elapsed = round(time.time() - t0, 2)
        print(f"  [SUCCESS] '{display_title}' ({size_mb}MB) sent to 'قناة افلام' as Msg #{sent.id} in {elapsed}s!", flush=True)

        # Save to database
        parsed = parse_media_details(caption, file_name=f"{display_title}.mp4")
        add_media_item(
            parsed_data=parsed,
            raw_caption=caption,
            source_chat_id=bot_id,
            source_msg_id=video_msg.id,
            target_msg_id=sent.id,
            file_size=video_msg.video.size,
            is_transferred=1
        )
        return True

    except Exception as e:
        print(f"  [Error] {query_text} via {bot_info['name']}: {e}", flush=True)
        return False

async def main():
    init_db()
    client = TelegramClient("user_session", API_ID, API_HASH)
    await client.connect()

    transferred = get_transferred_titles()
    print(f"=== STARTING CONTINUOUS LIGHTNING HARVESTER (MOVIES ONLY) ===", flush=True)
    print(f"Total Movies in Catalog: {len(HARVEST_CATALOG)}", flush=True)
    print(f"Already Transferred: {len(transferred)}", flush=True)

    success_count = 0
    start_time = time.time()

    for idx, title in enumerate(HARVEST_CATALOG, 1):
        t_low = title.lower()
        if any(t_low == done or t_low in done or done in t_low for done in transferred):
            print(f"[{idx}/{len(HARVEST_CATALOG)}] '{title}' already transferred. Skipping.", flush=True)
            continue

        print(f"\n[{idx}/{len(HARVEST_CATALOG)}] Harvesting Movie: '{title}'...", flush=True)
        harvested = False

        # Try title itself across bots
        queries_to_try = [title]
        if title in MOVIE_ALIASES:
            queries_to_try.extend(MOVIE_ALIASES[title])

        for q in queries_to_try:
            for bot_info in SOURCE_BOTS:
                ok = await harvest_single_title(client, bot_info, query_text=q, display_title=title)
                if ok:
                    success_count += 1
                    harvested = True
                    transferred.append(title.lower())
                    if success_count % 5 == 0:
                        try:
                            export_registry()
                        except Exception:
                            pass
                    break
            if harvested:
                break

        if not harvested:
            print(f"  -> Movie not found in sources.", flush=True)

        # 1.5s safe delay between movies
        await asyncio.sleep(1.5)

    export_registry()
    total_time = round((time.time() - start_time) / 60, 1)
    print(f"\n=== FINISHED! Successfully transferred {success_count} new movies in {total_time} minutes ===", flush=True)
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
