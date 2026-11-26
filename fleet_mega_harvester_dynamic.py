import asyncio
import os
import sys
import time
import json
import re
from collections import deque
from telethon import TelegramClient, errors
from pymongo import ReplaceOne

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from database import parse_media_details, get_connection, get_mongo_db

SOURCE_CH = -1004479154283
MOVIES_CH = -1004477353424
SERIES_CH = -1004453601662

STORE_CAPTION_LINE = "المتجر الخاص بالبوت @NitroJet3BOT"
STATE_FILE = os.path.join(BASE_DIR, "fleet_harvest_state.json")
MAX_MSG_ID = 12715

ACCOUNTS = [
    {"name": "Sarah", "session": "user_session_2", "api_id": 31947327, "api_hash": "88bae070f4b4fb8f348eb6a16e8879d2"},
    {"name": "Yousef", "session": "user_session_3", "api_id": 37935234, "api_hash": "3cc62807b20c5ae599058cc42f5a42e0"},
    {"name": "Ahmed", "session": "user_session_4", "api_id": 32190742, "api_hash": "88bae070f4b4fb8f348eb6a16e8879d2"},
    {"name": "Nitro", "session": "user_session_5", "api_id": 35697447, "api_hash": "3523908e9c2d5c93f3b4273e14480ae8"},
    {"name": "Janth", "session": "user_session_6", "api_id": 31610153, "api_hash": "760273e572dc9dff94701104a27c10ef"},
    {"name": "Khalil", "session": "user_session_7", "api_id": 37860913, "api_hash": "e8a03e3d229bd4a4d690255fca35a493"},
    {"name": "Jisan", "session": "user_session_8", "api_id": 38849287, "api_hash": "bbbe5b27feac417361caa4342a6d1b51"},
]

db_queue = asyncio.Queue()
speed_window = deque(maxlen=2000)
work_queue = asyncio.Queue()
transferred_lock = asyncio.Lock()
transferred_count = 0

def load_existing_source_ids():
    ids = set()
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT source_msg_id FROM media_items WHERE source_chat_id = ?", (SOURCE_CH,))
        rows = c.fetchall()
        conn.close()
        ids.update(r[0] for r in rows if r[0] is not None)
    except Exception as e:
        print(f"SQLite load err: {e}")

    try:
        mdb = get_mongo_db()
        if mdb is not None:
            m_ids = mdb['media_items'].distinct("source_msg_id", {"source_chat_id": SOURCE_CH})
            ids.update(i for i in m_ids if i is not None)
    except Exception as e:
        print(f"Mongo load err: {e}")

    return ids

def format_clean_caption(item_details, orig_text):
    title = item_details.get('clean_title') or "فيلم"
    title = re.sub(r'[*_~`]+', '', title).strip()
    title = re.sub(r'@\w+', '', title).strip()
    title = re.sub(r'https?://\S+', '', title).strip()
    
    quality = item_details.get('quality') or "HD"
    is_series = item_details.get('is_series', 0)
    
    if is_series:
        s = item_details.get('season_num', 1)
        ep = item_details.get('episode_num', 1)
        st = item_details.get('series_title') or title
        st = re.sub(r'[*_~`]+', '', st).strip()
        return (
            f"📺 **{st}**\n"
            f"الموسم {s} | الحلقة {ep}\n"
            f"🌟 **الجودة: {quality}**\n"
            f"✨ **عبر: @zxeeabot**\n"
            f"{STORE_CAPTION_LINE}"
        )
    else:
        return (
            f"🎬 **فيلم: {title}**\n"
            f"🌟 **الجودة: {quality}**\n"
            f"✨ **عبر: @zxeeabot**\n"
            f"{STORE_CAPTION_LINE}"
        )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ASYNCHRONOUS DATABASE BATCH INSERTER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def db_batch_worker():
    mdb = get_mongo_db()
    col = mdb['media_items'] if mdb is not None else None

    while True:
        items = []
        try:
            item = await asyncio.wait_for(db_queue.get(), timeout=1.0)
            items.append(item)
            while len(items) < 100:
                try:
                    item = db_queue.get_nowait()
                    items.append(item)
                except asyncio.QueueEmpty:
                    break
        except asyncio.TimeoutError:
            continue

        if not items:
            continue

        # 1. Bulk write to SQLite first to generate canonical item ID
        try:
            def _sqlite_bulk():
                conn = get_connection()
                c = conn.cursor()
                for it in items:
                    c.execute("""
                    INSERT INTO media_items (
                        is_series, series_title, season_num, episode_num,
                        title, clean_title, raw_caption, source_chat_id, source_msg_id,
                        target_msg_id, file_size, duration, quality, media_type, is_transferred
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_chat_id, source_msg_id) DO UPDATE SET
                        target_msg_id=excluded.target_msg_id,
                        is_transferred=excluded.is_transferred
                    """, (
                        it.get('is_series', 0), it.get('series_title'), it.get('season_num', 1), it.get('episode_num', 0),
                        it.get('title'), it.get('clean_title'), it.get('raw_caption'), it.get('source_chat_id'), it.get('source_msg_id'),
                        it.get('target_msg_id'), it.get('file_size', 0), it.get('duration', 0), it.get('quality', 'HD'),
                        it.get('media_type', 'video'), it.get('is_transferred', 1)
                    ))
                    c.execute("SELECT id FROM media_items WHERE source_chat_id = ? AND source_msg_id = ?",
                              (it['source_chat_id'], it['source_msg_id']))
                    row = c.fetchone()
                    if row:
                        it['id'] = row[0]
                conn.commit()
                conn.close()
            await asyncio.to_thread(_sqlite_bulk)
        except Exception as e:
            print(f"[DB-Worker] SQLite bulk write notice: {e}", flush=True)

        # 2. Bulk write to MongoDB with non-null canonical ID
        if col is not None:
            try:
                ops = []
                for it in items:
                    if it.get('id') is not None:
                        ops.append(ReplaceOne(
                            {"source_chat_id": it["source_chat_id"], "source_msg_id": it["source_msg_id"]},
                            it,
                            upsert=True
                        ))
                if ops:
                    await asyncio.to_thread(col.bulk_write, ops, ordered=False)
            except Exception as e:
                print(f"[DB-Worker] Mongo bulk write notice: {e}", flush=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WORK-STEALING DYNAMIC WORKER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def dynamic_worker(acc):
    global transferred_count
    session_path = os.path.join(BASE_DIR, acc['session'])
    client = TelegramClient(session_path, acc['api_id'], acc['api_hash'])
    name = acc['name']
    await client.connect()

    if not await client.is_user_authorized():
        print(f"[{name}] ❌ Session not authorized. Exiting.", flush=True)
        return

    print(f"[{name}] 🚀 Dynamic Worker ready & pulling from shared pool...", flush=True)

    while not work_queue.empty():
        try:
            chunk = work_queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        try:
            msgs = await client.get_messages(SOURCE_CH, ids=chunk)
        except errors.FloodWaitError as fwe:
            print(f"[{name}] ⏳ FloodWait {fwe.seconds}s on fetch. Returning chunk & sleeping...", flush=True)
            await work_queue.put(chunk)
            await asyncio.sleep(fwe.seconds + 2)
            continue
        except Exception as e:
            print(f"[{name}] Fetch error: {e}", flush=True)
            await work_queue.put(chunk)
            await asyncio.sleep(1)
            continue

        for m in msgs:
            if not m or not m.media or not hasattr(m.media, 'document') or not m.media.document:
                continue

            fname = getattr(m.file, 'name', None) or ""
            parsed = parse_media_details(m.text or "", fname)
            caption = format_clean_caption(parsed, m.text or "")
            dest_ch = MOVIES_CH if parsed.get('is_series') == 0 else SERIES_CH

            success = False
            for attempt in range(3):
                try:
                    sent = await client.send_file(dest_ch, m.media, caption=caption, supports_streaming=True)
                    t_now = time.time()
                    speed_window.append(t_now)

                    t_cutoff = t_now - 60
                    recent_count = sum(1 for t in speed_window if t >= t_cutoff)

                    it_record = {
                        "id": None,
                        "title": parsed.get('clean_title'),
                        "clean_title": parsed.get('clean_title'),
                        "raw_caption": caption,
                        "source_chat_id": SOURCE_CH,
                        "source_msg_id": m.id,
                        "target_msg_id": sent.id,
                        "file_size": m.file.size if m.file else 0,
                        "duration": parsed.get('duration', 0),
                        "quality": parsed.get('quality', 'HD'),
                        "media_type": "video",
                        "is_series": parsed.get('is_series', 0),
                        "series_title": parsed.get('series_title'),
                        "season_num": parsed.get('season_num', 1),
                        "episode_num": parsed.get('episode_num', 0),
                        "is_transferred": 1,
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
                    }
                    await db_queue.put(it_record)

                    async with transferred_lock:
                        transferred_count += 1
                        total = transferred_count

                    title_disp = (parsed.get('clean_title') or fname or f"Msg #{m.id}").strip()
                    ch_type = "🎬 Movie" if dest_ch == MOVIES_CH else "📺 Series"
                    print(f"[{name}] ⚡ {ch_type} #{sent.id} | Speed: {recent_count} msgs/min | '{title_disp[:30]}' (Total: {total}/{MAX_MSG_ID})", flush=True)
                    success = True
                    await asyncio.sleep(0.08)
                    break
                except errors.FloodWaitError as fwe:
                    print(f"[{name}] ⏳ FloodWait on send ({fwe.seconds}s). Sleeping...", flush=True)
                    await asyncio.sleep(fwe.seconds + 2)
                except Exception as e:
                    print(f"[{name}] Error sending msg #{m.id}: {e}", flush=True)
                    await asyncio.sleep(0.5)
                    break

        work_queue.task_done()

    print(f"[{name}] 🎉 All assigned tasks completed!", flush=True)
    await client.disconnect()

async def main():
    global transferred_count
    print("==================================================================")
    print("⚡ DYNAMIC POOL MEGA HARVESTER (ALL 7 ACCOUNTS COOPERATIVE)")
    print(f"   Source Channel: {SOURCE_CH} ('مخزن جديد')")
    print(f"   Target Channels: MOVIES ({MOVIES_CH}) & SERIES ({SERIES_CH})")
    print(f"   Max Message ID: {MAX_MSG_ID}")
    print("==================================================================")

    existing_ids = load_existing_source_ids()
    transferred_count = len(existing_ids)
    print(f"Already transferred/indexed: {transferred_count:,} messages.")

    missing_ids = [i for i in range(1, MAX_MSG_ID + 1) if i not in existing_ids]
    print(f"Remaining messages to process: {len(missing_ids):,} messages.")

    if not missing_ids:
        print("🎉 ALL 12,715 MESSAGES ALREADY FULLY TRANSFERRED!")
        return

    # Chunk missing IDs in batches of 50
    CHUNK_SIZE = 50
    for idx in range(0, len(missing_ids), CHUNK_SIZE):
        work_queue.put_nowait(missing_ids[idx:idx + CHUNK_SIZE])

    print(f"Work pool prepared: {work_queue.qsize()} batches of {CHUNK_SIZE} IDs.")

    # Start DB background worker
    asyncio.create_task(db_batch_worker())

    # Launch all 7 accounts in cooperative work pool
    tasks = [dynamic_worker(acc) for acc in ACCOUNTS]
    await asyncio.gather(*tasks)

    print("\n🎉 ALL 12,715 MESSAGES FROM SOURCE CHANNEL PROCESSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(main())
