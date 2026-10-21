import asyncio
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
import cryptg
from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeVideo
from database import (
    get_connection, search_media, get_stats, 
    get_series_seasons, get_season_episodes, get_next_episode,
    mark_transferred
)

API_ID = 32374871
API_HASH = "88bae070f4b4fb8f348eb6a16e8879d2"
BOT_TOKEN = "8884645024:AAFgHszR26PgAWxL5TjUAc4Hbcl7-gUpM5A"
BOT_USERNAME = "@zxeeabot"
STORAGE_CHANNEL = -1004477353424

USER_SESSION_PATH = os.path.join(os.path.dirname(__file__), "user_session")
BOT_SESSION_PATH = os.path.join(os.path.dirname(__file__), "bot_session")
TEMP_DIR = os.path.join(os.path.dirname(__file__), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

bot = TelegramClient(BOT_SESSION_PATH, API_ID, API_HASH)
user_client = TelegramClient(USER_SESSION_PATH, API_ID, API_HASH)

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

async def ensure_transferred(item, status_callback=None):
    """
    Ensures media is uploaded to STORAGE_CHANNEL (قناة افلام).
    If not transferred yet, user_client downloads from restricted channel
    and uploads to STORAGE_CHANNEL, then marks transferred.
    """
    if item.get('is_transferred') and item.get('target_msg_id'):
        return item['target_msg_id']

    if status_callback:
        await status_callback("⏳ جاري جلب الفيديو وتجهيزه لأول مرة (يرجى الانتظار ثوانٍ)...")

    # Fetch from source using user_client (who has access to the restricted channel)
    source_msg = await user_client.get_messages(item['source_chat_id'], ids=item['source_msg_id'])
    if not source_msg or not (source_msg.video or source_msg.document):
        raise Exception("لم يتم العثور على ملف الفيديو في القناة المصدر")

    # Download via user_client
    file_path = await user_client.download_media(source_msg, file=TEMP_DIR)
    
    if status_callback:
        await status_callback("🚀 جاري رفع الفيديو إلى القناة الرسمية...")

    # Upload to STORAGE_CHANNEL via user_client
    sent_msg = await user_client.send_file(
        STORAGE_CHANNEL,
        file_path,
        caption=f"🎬 {item['clean_title']}",
        supports_streaming=True
    )

    # Clean local file
    if os.path.exists(file_path):
        os.remove(file_path)

    # Update database
    mark_transferred(
        source_chat_id=item['source_chat_id'],
        source_msg_id=item['source_msg_id'],
        target_msg_id=sent_msg.id
    )

    return sent_msg.id

@bot.on(events.NewMessage(pattern=r'^/start(?:\s+(.+))?', func=lambda e: e.is_private))
async def start_handler(event):
    param = event.pattern_match.group(1)
    if param and param.startswith("movie_"):
        try:
            m_id = int(param.replace("movie_", ""))
            await deliver_movie_by_id(event.chat_id, m_id, reply_to=event.id)
            return
        except Exception as e:
            print(f"Deep link error: {e}")

    stats = get_stats()
    text = (
        "🎬 **أهلاً بك في بوت الأفلام والمسلسلات الرسمي!**\n\n"
        f"📊 **إحصائيات المكتبة الحالية:**\n"
        f"• 🎬 الأفلام المتوفرة: **{stats['total_movies']}** فيلم\n"
        f"• 📺 المسلسلات المتوفرة: **{stats['total_series']}** مسلسل\n"
        f"• 📦 إجمالي الأعمال: **{stats['total']}** عمل سينمائي\n\n"
        "🔍 **طريقة الاستخدام:**\n"
        "اكتب اسم أي فيلم أو مسلسل مباشرة في الشات (مثلاً: `Inception` أو `Avatar` أو `Gladiator`).\n\n"
        "🛡️ **جميع الأعمال مفحوصة وموثقة برعاية Trustpilot**"
    )
    if os.path.exists(COVER_IMAGE_PATH):
        await event.reply(text, file=COVER_IMAGE_PATH)
    else:
        await event.reply(text)

@bot.on(events.NewMessage(func=lambda e: e.is_private))
async def search_handler(event):
    if event.text.startswith('/'):
        return

    query = event.text.strip()
    if len(query) < 2:
        await event.reply("⚠️ يرجى كتابة حرفين على الأقل للبحث.")
        return

    results = search_media(query, limit=15)
    series_list = results['series']
    movies_list = results['movies']

    if not series_list and not movies_list:
        await event.reply(f"❌ لم يتم العثور على نتائج لـ: **{query}**\nجرّب كتابة الاسم بشكل مختلف.")
        return

    buttons = []
    
    # 1. Add Series results
    for s in series_list:
        btn_text = f"📺 {s['series_title']} ({s['seasons_count']} مواسم | {s['episodes_count']} حلقة)"
        buttons.append([Button.inline(btn_text, data=f"series_{s['first_id']}")])

    # 2. Add Movie results
    for m in movies_list:
        mb = round(m['file_size'] / (1024 * 1024))
        btn_text = f"🎬 {m['clean_title'][:25]} ({m['quality']} | {mb}MB)"
        buttons.append([Button.inline(btn_text, data=f"movie_{m['id']}")])

    await event.reply(
        f"🔎 **نتائج البحث عن:** `{query}`\nاختر العمل المطلوب لعرض المواسم أو التحميل المباشر:",
        buttons=buttons
    )

@bot.on(events.CallbackQuery(pattern=r'^series_(\d+)'))
async def series_card_handler(event):
    item_id = int(event.pattern_match.group(1))
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM media_items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        await event.answer("⚠️ المسلسل غير متوفر.", alert=True)
        return

    item = dict(row)
    series_title = item['series_title']
    seasons = get_series_seasons(series_title)

    season_buttons = []
    row_btns = []
    for s in seasons:
        row_btns.append(Button.inline(f"الموسم {s}", data=f"season_{item_id}_{s}"))
        if len(row_btns) == 2:
            season_buttons.append(row_btns)
            row_btns = []
    if row_btns:
        season_buttons.append(row_btns)

    season_buttons.append([Button.inline("رجوع للبحث", data="back_search")])

    text = (
        f"📺 **{series_title}**\n"
        f"-------------------------------------\n"
        f"• عدد المواسم: **{len(seasons)}**\n"
        f"• اختر الموسم المطلوب لعرض حلقاته:"
    )
    await event.edit(text, buttons=season_buttons)

@bot.on(events.CallbackQuery(pattern=r'^season_(\d+)_(\d+)'))
async def season_episodes_handler(event):
    item_id = int(event.pattern_match.group(1))
    season_num = int(event.pattern_match.group(2))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT series_title FROM media_items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        await event.answer("⚠️ حدث خطأ.", alert=True)
        return

    series_title = row['series_title']
    episodes = get_season_episodes(series_title, season_num)

    if not episodes:
        await event.answer("لا توجد حلقات مسجلة لهذا الموسم حالياً.", alert=True)
        return

    episode_buttons = []
    row_btns = []
    for ep in episodes:
        ep_text = f"الحلقة {ep['episode_num']}"
        row_btns.append(Button.inline(ep_text, data=f"play_ep_{ep['id']}"))
        if len(row_btns) == 3:
            episode_buttons.append(row_btns)
            row_btns = []
    if row_btns:
        episode_buttons.append(row_btns)

    episode_buttons.append([
        Button.inline("قائمة المواسم", data=f"series_{item_id}"),
        Button.inline("القائمة الرئيسية", data="back_search")
    ])

    text = (
        f"📺 **{series_title}**\n"
        f"-------------------------------------\n"
        f"📍 **الموسم {season_num} — اختر الحلقة المناسبة :**"
    )
    await event.edit(text, buttons=episode_buttons)

@bot.on(events.CallbackQuery(pattern=r'^play_ep_(\d+)'))
async def play_episode_handler(event):
    ep_id = int(event.pattern_match.group(1))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM media_items WHERE id = ?", (ep_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        await event.answer("⚠️ الحلقة غير متوفرة.", alert=True)
        return

    item = dict(row)
    caption = format_caption(item)
    await event.answer("⏳ جاري تحضير الحلقة...")

    status_msg = await event.reply("⏳ جاري تجهيز الفيديو وإرساله إليك...")

    async def update_status(text):
        try:
            await status_msg.edit(text)
        except Exception:
            pass

    next_ep = get_next_episode(item['series_title'], item['season_num'], item['episode_num'])
    buttons = []
    if next_ep:
        buttons.append([Button.inline("الحلقة التالية ▶️", data=f"play_ep_{next_ep['id']}")])
    buttons.append([
        Button.inline("قائمة الحلقات", data=f"season_{item['id']}_{item['season_num']}"),
        Button.inline("قائمة المواسم", data=f"series_{item['id']}")
    ])

    try:
        target_msg_id = await ensure_transferred(item, status_callback=update_status)
        
        # Now fetch from STORAGE_CHANNEL (where bot is admin) and send
        storage_msg = await bot.get_messages(STORAGE_CHANNEL, ids=target_msg_id)
        if storage_msg and storage_msg.media:
            await bot.send_file(
                event.chat_id,
                storage_msg.media,
                caption=caption,
                supports_streaming=True,
                buttons=buttons
            )
            await status_msg.delete()
        else:
            await status_msg.edit("⚠️ تعذر إرسال الفيديو من القناة الرئيسية.")
    except Exception as e:
        await status_msg.edit(f"⚠️ حدث خطأ أثناء تجهيز الفيديو: {e}")

COVER_IMAGE_PATH = os.path.join(os.path.dirname(__file__), "custom_cover.jpg")
THUMB_IMAGE_PATH = os.path.join(os.path.dirname(__file__), "custom_thumb_320.jpg")

async def deliver_movie_by_id(chat_id, movie_id, callback_event=None, reply_to=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM media_items WHERE id = ?", (movie_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        if callback_event:
            await callback_event.answer("⚠️ الفيلم غير متوفر.", alert=True)
        elif reply_to:
            await bot.send_message(chat_id, "⚠️ الفيلم غير متوفر.", reply_to=reply_to)
        return

    item = dict(row)
    caption = format_caption(item)
    mb = round(item['file_size'] / (1024 * 1024))
    title = item['clean_title'].replace('🎬', '').strip()

    if callback_event:
        await callback_event.answer("⏳ جاري تجهيز الفيلم...")

    has_cover = bool(item.get('has_custom_cover'))
    target_msg_id = item.get('target_msg_id')

    # Case 1: ALREADY CONVERTED (INSTANT DELIVERY IN 0.5s!)
    if has_cover and target_msg_id:
        try:
            storage_msg = await bot.get_messages(STORAGE_CHANNEL, ids=target_msg_id)
            if storage_msg and storage_msg.media:
                await bot.send_file(
                    chat_id,
                    storage_msg.media,
                    caption=caption,
                    supports_streaming=True
                )
                return
        except Exception as e:
            print(f"Error sending already converted movie: {e}")

    # Case 2: ON-DEMAND LIVE PROCESSING! (First time requested)
    status_msg = await bot.send_message(
        chat_id,
        f"⏳ **جاري معالجة فيلم:** `{title}` ({mb} MB)\n"
        f"🛡️ **تجهيز غلاف Trustpilot الحصري...**\n"
        f"⚡ يستغرق لحظات قليلة لأول مرة فقط!",
        reply_to=reply_to
    )

    async def update_status(text):
        try:
            await status_msg.edit(text)
        except Exception:
            pass

    temp_file = None
    storage_msg = None
    try:
        current_target_id = await ensure_transferred(item, status_callback=update_status)
        storage_msg = await bot.get_messages(STORAGE_CHANNEL, ids=current_target_id)
        if not storage_msg or not storage_msg.media:
            await update_status("⚠️ تعذر جلب ملف الفيلم.")
            return

        await update_status(f"⚡ جاري دمج غلاف Trustpilot لفيلم: `{title}`...")

        temp_file = os.path.join(TEMP_DIR, f"temp_{movie_id}_{int(time.time())}.mp4")
        await bot.download_media(storage_msg, file=temp_file)

        attrs = []
        if storage_msg.document and storage_msg.document.attributes:
            for a in storage_msg.document.attributes:
                if isinstance(a, DocumentAttributeVideo):
                    attrs.append(DocumentAttributeVideo(
                        duration=a.duration,
                        w=a.w,
                        h=a.h,
                        supports_streaming=True
                    ))
        if not attrs:
            attrs = [DocumentAttributeVideo(duration=5400, w=1280, h=720, supports_streaming=True)]

        thumb_arg = THUMB_IMAGE_PATH if os.path.exists(THUMB_IMAGE_PATH) else None
        new_storage_msg = await bot.send_file(
            STORAGE_CHANNEL,
            temp_file,
            thumb=thumb_arg,
            caption=caption,
            attributes=attrs,
            supports_streaming=True
        )

        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE media_items SET target_msg_id = ?, has_custom_cover = 1 WHERE id = ?", (new_storage_msg.id, movie_id))
        conn.commit()
        conn.close()

        await bot.send_file(
            chat_id,
            new_storage_msg.media,
            caption=caption,
            supports_streaming=True
        )
        await status_msg.delete()

    except Exception as e:
        print(f"On-demand processing error: {e}")
        try:
            if storage_msg and storage_msg.media:
                await bot.send_file(chat_id, storage_msg.media, caption=caption, supports_streaming=True)
                await status_msg.delete()
        except Exception:
            await update_status(f"⚠️ حدث خطأ أثناء تجهيز الفيلم: {e}")
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

@bot.on(events.CallbackQuery(pattern=r'^movie_(\d+)'))
async def play_movie_handler(event):
    movie_id = int(event.pattern_match.group(1))
    await deliver_movie_by_id(event.chat_id, movie_id, callback_event=event)

@bot.on(events.CallbackQuery(pattern=r'^back_search'))
async def back_search_handler(event):
    await event.edit("🔍 اكتب اسم أي فيلم أو مسلسل في الشات للبحث:")

async def run_both():
    print("Connecting User Client...")
    await user_client.connect()
    print("Starting Bot @zxeeabot...")
    await bot.start(bot_token=BOT_TOKEN)
    print("Both User Client and Bot are LIVE and connected!")
    await asyncio.gather(
        bot.run_until_disconnected(),
        user_client.run_until_disconnected()
    )

if __name__ == "__main__":
    asyncio.run(run_both())
