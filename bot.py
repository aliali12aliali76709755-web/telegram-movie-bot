import asyncio
import os
import sys
import time
import re
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
import cryptg
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeVideo
from database import (
    get_media_item_by_id, search_media, get_stats, 
    get_series_seasons, get_season_episodes, get_next_episode,
    mark_transferred
)
import admin_service
import admin_handlers
import ai_service

API_ID = 32374871
API_HASH = "88bae070f4b4fb8f348eb6a16e8879d2"
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    TOKEN_FILE = os.path.join(os.path.dirname(__file__), "token.txt")
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            BOT_TOKEN = f.read().strip()

BOT_USERNAME = "@zxeeabot"
MOVIES_CHANNEL = -1004477353424
SERIES_CHANNEL = -1004453601662

BOT_SESSION_PATH = os.path.join(os.path.dirname(__file__), "bot_session")
COVER_IMAGE_PATH = os.path.join(os.path.dirname(__file__), "custom_cover.jpg")
THUMB_IMAGE_PATH = os.path.join(os.path.dirname(__file__), "custom_thumb_320.jpg")

BOT_SESSION_STRING = os.environ.get("BOT_SESSION_STRING", "1BJWap1sBu73MXBBm5hAOnknucvIdyCJEzS5kI0w-MKFyau0x4_VazWUZjYgD6_IK8jkbiGHva3cU2O1lGaZdEcPasK9T-OJUui3ROV8fkHewAKAlAAzLmO47TCGQWhLs3xqe-GoMlWhwseInvaUI6aeMPl61WdZjB15rHfPcKVFhq4BqUR_S7Hb6h77SgdmRFGQkzHjAFp94ej7YAZf8vpZjbzgxr-s6UreVDSm7ay5XlO6pC0lUfBSVtoTCT-qOuCCEXkb8dsDfX1u_dzt3E443OM_N0LnUC-6DCw5YEaA3gxN1uIruO44ynr3OAO7kqT00cLh5g1ty-gqbwZ1_-tUtcjEDzUw=").strip()

if BOT_SESSION_STRING:
    session_target = StringSession(BOT_SESSION_STRING)
else:
    session_target = BOT_SESSION_PATH

bot = TelegramClient(session_target, API_ID, API_HASH, connection_retries=None, retry_delay=3)

async def safe_answer(event, *args, **kwargs):
    """Safely answers a callback query without raising QueryIdInvalidError if expired."""
    if not event:
        return None
    try:
        return await event.answer(*args, **kwargs)
    except Exception:
        return None

SEASON_NAMES = {
    1: "الأول", 2: "الثاني", 3: "الثالث", 4: "الرابع",
    5: "الخامس", 6: "السادس", 7: "السابع", 8: "الثامن",
    9: "التاسع", 10: "العاشر"
}

def format_caption(item, storage_msg=None):
    if storage_msg and getattr(storage_msg, 'text', None) and BOT_USERNAME in storage_msg.text:
        return storage_msg.text
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

def verify_content_integrity(item, storage_msg) -> bool:
    """
    Validates that the file in storage_msg actually corresponds to the requested item.
    Prevents delivering mismatched media caused by legacy interleaved IDs.
    """
    if not storage_msg:
        return False

    msg_text = (storage_msg.text or "").lower()
    file_name = ""
    if storage_msg.media and hasattr(storage_msg.media, 'document') and storage_msg.media.document:
        for attr in storage_msg.media.document.attributes:
            if hasattr(attr, 'file_name') and attr.file_name:
                file_name = attr.file_name.lower()
                break

    combined = f"{msg_text} {file_name}".strip()
    if not combined:
        return True  # Minimal metadata; allow delivery

    expected_titles = []
    if item.get('series_title'):
        expected_titles.append(str(item['series_title']))
    if item.get('clean_title'):
        expected_titles.append(str(item['clean_title']))
    if item.get('title'):
        expected_titles.append(str(item['title']))

    all_words = []
    for t in expected_titles:
        for w in re.findall(r'[\w]+', t):
            if len(w) >= 3 and not re.match(r'^\d+$', w):
                all_words.append(w.lower())

    stop_words = {
        'season', 'episode', 'series', 'movie', 'bluray', 'web', 'x264', 'x265',
        '1080p', '720p', '480p', 'الموسم', 'الحلقة', 'فيلم', 'مسلسل', 'مترجم', 'مدبلج'
    }
    distinctive = [w for w in all_words if w not in stop_words]
    if not distinctive:
        return True

    for w in distinctive:
        if w in combined:
            return True

    return False

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. ADMIN COMMANDS & STATE HANDLER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.on(events.NewMessage(pattern=r'^/admin', func=lambda e: e.is_private))
async def admin_cmd_handler(event):
    if not admin_handlers.is_admin(event.sender_id):
        return
    text = admin_handlers.get_main_menu_text()
    buttons = admin_handlers.get_main_menu_buttons()
    await event.reply(text, buttons=buttons)

@bot.on(events.NewMessage(pattern=r'^/(cancel|exit|الغاء|خروج)', func=lambda e: e.is_private))
async def cancel_cmd_handler(event):
    if event.sender_id in admin_handlers.ADMIN_STATES:
        del admin_handlers.ADMIN_STATES[event.sender_id]
    ai_service.set_user_ai_mode(event.sender_id, False)
    ai_service.set_admin_ai_mode(event.sender_id, False)
    await event.reply("✅ تم إلغاء العملية والعودة للوضع الطبيعي.", buttons=Button.clear())

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. START COMMAND HANDLER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.on(events.NewMessage(pattern=r'^\s*[\u200e\u200f]?/(?:start|ابدأ|بدء)(?:\s+(.+))?', func=lambda e: e.is_private))
async def start_handler(event):
    ai_service.set_user_ai_mode(event.sender_id, False)
    ai_service.set_admin_ai_mode(event.sender_id, False)

    sender = await event.get_sender()
    admin_service.record_user(
        event.sender_id,
        username=getattr(sender, 'username', None),
        first_name=getattr(sender, 'first_name', None),
        last_name=getattr(sender, 'last_name', None)
    )

    # Check Mandatory Subscription (bypass for admin) - strictly live check!
    if not admin_handlers.is_admin(event.sender_id):
        is_ok, missing = await admin_handlers.check_user_subscriptions(bot, event.sender_id, force_live=True)
        if not is_ok:
            text, buttons = admin_handlers.build_fsub_prompt(missing)
            await event.reply(text, buttons=buttons)
            return

    param = event.pattern_match.group(1) if event.pattern_match else None
    if param and param.startswith("movie_"):
        try:
            m_id = int(param.replace("movie_", ""))
            await deliver_movie_by_id(event.chat_id, m_id, reply_to=event.id)
            return
        except Exception as e:
            print(f"Deep link error: {e}")

    text = (
        "أهلاً بك في بوت الأفلام والمسلسلات 🎬🍿\n\n"
        "• أرسل اسم أي فيلم أو مسلسل، وسأجلبه لك فوراً للمشاهدة والتحميل!\n"
        "• **لا تتذكر اسم الفيلم؟** اضغط على **(🧠 باحث المشاهد)** واشرح ما تتذكره وسيتعرف عليه الذكاء الاصطناعي فوراً!"
    )
    buttons = [
        [
            Button.inline("🧠 باحث المشاهد بالذكاء الاصطناعي", data="ai_user_start"),
            Button.inline("✨ اقترح لي أفلام", data="ai_user_suggest")
        ]
    ]
    await event.reply(text, buttons=buttons)

@bot.on(events.NewMessage(pattern=r'^/(ai|ذكاء)', func=lambda e: e.is_private))
async def ai_cmd_handler(event):
    if not admin_handlers.is_admin(event.sender_id):
        is_ok, missing = await admin_handlers.check_user_subscriptions(bot, event.sender_id)
        if not is_ok:
            text, buttons = admin_handlers.build_fsub_prompt(missing)
            await event.reply(text, buttons=buttons)
            return

    ai_service.set_user_ai_mode(event.sender_id, True)
    text = (
        "🧠 **باحث المشاهد والاقتراحات بالذكاء الاصطناعي 🎬**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "نسيت اسم فيلم أو تبحث عن عمل بمواصفات معينة؟\n\n"
        "✨ اشرح لي أي مشهد، أو قصة، أو شخصيات، أو اطلب اقتراحات ذكية وسأساعدك وأوفر لك روابط المشاهدة والتحميل فوراً!\n\n"
        "✍️ **أرسل وصفك أو طلبك الآن في رسالة:**"
    )
    buttons = [[Button.inline("❌ خروج من وضع الذكاء الاصطناعي", data="ai_user_exit")]]
    await event.reply(text, buttons=buttons)

@bot.on(events.NewMessage(pattern=r'^(/(support|help)|.*الدعم\s*الفني.*)', func=lambda e: e.is_private))
async def support_handler(event):
    text = (
        "💬 **قسم الدعم الفني والمساعدة**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "لطلب أي فيلم أو مسلسل، أو للإبلاغ عن أي استفسار أو مشكلة، "
        "يسعدنا تواصلك مباشرة مع فريق الدعم الفني عبر الرابط أدناه:\n\n"
        "👨‍💻 **معرف الدعم:** @DSAS3"
    )
    buttons = [[Button.url("👨‍💻 تواصل مع الدعم الفني", url="https://t.me/DSAS3")]]
    await event.reply(text, buttons=buttons)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. TEXT & SEARCH HANDLER (WITH ADMIN STATE INTERCEPTION)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.on(events.NewMessage(func=lambda e: e.is_private))
async def general_message_handler(event):
    raw_text = (event.raw_text or event.text or "").strip()
    if not raw_text:
        return

    # If it is any variant of /start, do not process here (already handled exclusively by start_handler)
    if re.search(r'^[\u200e\u200f]?/(start|ابدأ|بدء)', raw_text, re.I):
        return

    if raw_text.startswith('/'):
        return

    # 1. Intercept Admin interactive states
    if event.sender_id in admin_handlers.ADMIN_STATES:
        state = admin_handlers.ADMIN_STATES[event.sender_id]
        action = state.get('action')

        if action == 'broadcast_await_msg':
            admin_handlers.ADMIN_STATES[event.sender_id] = {
                'action': 'broadcast_confirm',
                'msg': event
            }
            user_ids = admin_service.get_all_user_ids()
            buttons = [
                [Button.inline("🚀 تأكيد وبدء الإذاعة فوراً", data="adm_bcast_confirm")],
                [Button.inline("❌ إلغاء الإذاعة", data="adm_bcast_cancel")]
            ]
            await event.reply(
                f"📢 **تم استلام رسالة الإذاعة بنجاح!**\n\n"
                f"👥 سيتم إرسالها إلى: **{len(user_ids):,}** مستخدم.\n"
                f"⚠️ هل أنت متأكد من بدء الإذاعة الجماعية الآن؟",
                buttons=buttons
            )
            return

        elif action == 'fsub_add_title':
            title = event.text.strip()
            state['title'] = title
            state['action'] = 'fsub_add_link'
            type_name = 'البوت' if state['type'] == 'bot' else ('القناة' if state['type'] == 'channel' else 'القروب')
            await event.reply(
                f"🔗 **أرسل الآن رابط {type_name} أو المعرف العام:**\n"
                f"مثال: `https://t.me/example` أو `@example`\n\n"
                f"• للإلغاء، أرسل `/cancel`."
            )
            return

        elif action == 'fsub_add_link':
            link = event.text.strip()
            state['link'] = link
            if state['type'] == 'bot':
                admin_service.add_mandatory_channel(
                    title=state['title'],
                    link_or_username=state['link'],
                    chat_id=None,
                    channel_type='bot'
                )
                del admin_handlers.ADMIN_STATES[event.sender_id]
                text, buttons = admin_handlers.get_fsub_view()
                await event.reply(f"✅ **تمت إضافة البوت ({state['title']}) بنجاح!**", buttons=buttons)
                return
            else:
                state['action'] = 'fsub_add_chat_id'
                type_name = 'القناة' if state['type'] == 'channel' else 'القروب'
                await event.reply(
                    f"🆔 **أرسل الآن معرف {type_name} الرقمي (Chat ID) أو المعرف العام (@username) للتحقق:**\n"
                    f"• للعامة: `@channel_username`\n"
                    f"• للخاصة: آيدي القناة الرقمي مثل `-1001234567890`\n"
                    f"*(ملاحظة هامة: يجب رفع البوت مشرفاً في القناة/القروب ليتمكن من فحص الأعضاء)*\n\n"
                    f"• أو أرسل نفس الرابط/المعرف إذا كانت عامة."
                )
                return

        elif action == 'fsub_add_chat_id':
            chat_id_val = event.text.strip()
            admin_service.add_mandatory_channel(
                title=state['title'],
                link_or_username=state['link'],
                chat_id=chat_id_val,
                channel_type=state['type']
            )
            del admin_handlers.ADMIN_STATES[event.sender_id]
            text, buttons = admin_handlers.get_fsub_view()
            await event.reply(f"✅ **تمت إضافة {state['title']} بنجاح وتفعيل الفحص!**", buttons=buttons)
            return

        elif action == 'ai_await_key':
            key_input = event.text.strip()
            del admin_handlers.ADMIN_STATES[event.sender_id]
            status_msg = await event.reply("⏳ جاري اختبار وصلاحية المفتاح مع مزود الذكاء الاصطناعي...")
            ok, res = await asyncio.to_thread(ai_service.test_api_key, key_input)
            if ok:
                ai_service.set_ai_api_key(key_input)
                text, buttons = admin_handlers.get_ai_settings_view()
                await status_msg.edit(f"🎉 **تم حفظ واختبار مفتاح الـ API بنجاح!**\nالذكاء الاصطناعي مفعّل وجاهز لخدمة المستخدمين والمدير فوراً.", buttons=buttons)
            else:
                text, buttons = admin_handlers.get_ai_settings_view()
                await status_msg.edit(f"❌ **فشل التحقق من المفتاح:**\n`{res}`\n\nيرجى التأكد من صحة المفتاح وإعادة المحاولة.", buttons=buttons)
            return

    # 1.5 Intercept Admin AI Assistant Dialogue
    if admin_handlers.is_admin(event.sender_id) and ai_service.is_admin_in_ai_mode(event.sender_id):
        try:
            async with bot.action(event.chat_id, 'typing'):
                ai_reply = await asyncio.to_thread(ai_service.chat_with_admin_ai, event.sender_id, raw_text)
        except Exception:
            ai_reply = await asyncio.to_thread(ai_service.chat_with_admin_ai, event.sender_id, raw_text)

        buttons = [
            [Button.inline("🔄 مسح الذاكرة", data="adm_ai_reset_mem")],
            [Button.inline("❌ إنهاء المحادثة والعودة للوحة", data="adm_ai_exit")]
        ]
        await event.reply(ai_reply, buttons=buttons)
        return

    # 2. Record User & Check Mandatory Subscription
    sender = await event.get_sender()
    admin_service.record_user(
        event.sender_id,
        username=getattr(sender, 'username', None),
        first_name=getattr(sender, 'first_name', None),
        last_name=getattr(sender, 'last_name', None)
    )

    if not admin_handlers.is_admin(event.sender_id):
        is_ok, missing = await admin_handlers.check_user_subscriptions(bot, event.sender_id)
        if not is_ok:
            text, buttons = admin_handlers.build_fsub_prompt(missing)
            await event.reply(text, buttons=buttons)
            return

    # 2.5 Intercept User Movie Detective & Recommender AI Mode
    if ai_service.is_user_in_ai_mode(event.sender_id):
        try:
            async with bot.action(event.chat_id, 'typing'):
                res = await asyncio.to_thread(ai_service.chat_with_user_ai, event.sender_id, raw_text)
        except Exception:
            res = await asyncio.to_thread(ai_service.chat_with_user_ai, event.sender_id, raw_text)

        reply_text = res.get('response_text', '')
        buttons = []
        for s in res.get('series', [])[:3]:
            buttons.append([Button.inline(f"📺 {s['series_title']} ({s['seasons_count']} مواسم)", data=f"series_{s['first_id']}")])
        for m in res.get('movies', [])[:4]:
            mb = round(m['file_size'] / (1024 * 1024))
            clean_disp = re.sub(r'[*_~`]+', '', m['clean_title']).strip()
            buttons.append([Button.inline(f"🎬 {clean_disp[:28]} ({m['quality']} | {mb}MB)", data=f"movie_{m['id']}")])

        if res.get('movies') or res.get('series'):
            reply_text += "\n\n🍿 **العمل متوفر في قنواتنا — اختر للمشاهدة والتحميل فوراً:**"
        elif res.get('searched_terms'):
            reply_text += "\n\n⚠️ **هذا العمل غير متوفر حالياً في مكتبة القنوات، وتم تسجيله لإضافته قريباً.**"

        buttons.append([Button.inline("❌ خروج من وضع الذكاء الاصطناعي", data="ai_user_exit")])
        await event.reply(reply_text, buttons=buttons)
        return

    # 3. Handle Russian buttons residue cleanup
    query = event.text.strip()
    if any(k in query for k in ['Главное', 'пользователя', 'меню', 'пользовател']):
        await event.reply("✨ تم مسح وتطهير الأزرار القديمة بالكامل.", buttons=Button.clear())
        return

    if len(query) < 2:
        await event.reply("⚠️ يرجى كتابة حرفين على الأقل للبحث.")
        return

    # 4. Instant Search (< 0.5ms)
    t0 = time.time()
    results = search_media(query, limit=15)
    series_list = results['series']
    movies_list = results['movies']

    matched = series_list[0]['series_title'] if series_list else (movies_list[0]['clean_title'] if movies_list else None)
    is_ser = 1 if series_list else 0
    admin_service.log_search(event.sender_id, query, matched_title=matched, is_series=is_ser)

    if not series_list and not movies_list:
        buttons = [
            [Button.inline("🧠 تحليل المشهد بالذكاء الاصطناعي", data="ai_user_start")],
            [Button.inline("✨ اقتراحات أفلام بالذكاء الاصطناعي", data="ai_user_suggest")]
        ]
        await event.reply(
            f"❌ لم يتم العثور على نتائج مباشرة لـ: **{query}**\n\n"
            "💡 **هل تشرح مشهداً أو قصة فيلم نسيت اسمه؟**\n"
            "اضغط على زر الذكاء الاصطناعي أدناه وسأتعرف عليه فوراً!",
            buttons=buttons
        )
        return

    buttons = []
    # 1. Add Series results
    for s in series_list:
        btn_text = f"📺 {s['series_title']} ({s['seasons_count']} مواسم | {s['episodes_count']} حلقة)"
        buttons.append([Button.inline(btn_text, data=f"series_{s['first_id']}")])

    # 2. Add Movie results
    for m in movies_list:
        mb = round(m['file_size'] / (1024 * 1024))
        clean_disp = re.sub(r'[*_~`]+', '', m['clean_title']).strip()
        btn_text = f"🎬 {clean_disp[:28]} ({m['quality']} | {mb}MB)"
        buttons.append([Button.inline(btn_text, data=f"movie_{m['id']}")])

    search_time = round((time.time() - t0) * 1000, 1)
    await event.reply(
        f"🔎 **نتائج البحث عن:** `{query}`  *(⚡ {search_time}ms)*\nاختر العمل المطلوب لعرض المواسم أو التحميل المباشر:",
        buttons=buttons
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. MANDATORY SUBSCRIPTION VERIFICATION CALLBACK
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.on(events.CallbackQuery(data=b"check_sub"))
async def check_sub_callback(event):
    is_ok, missing = await admin_handlers.check_user_subscriptions(bot, event.sender_id, force_live=True)
    if is_ok:
        admin_service.mark_user_subscribed(event.sender_id)
        await event.answer("🎉 تم التحقق من اشتراكك بنجاح!", alert=False)
        welcome_text = (
            "أهلاً بك في بوت الأفلام والمسلسلات 🎬🍿\n\n"
            "أرسل فقط اسم الفيلم أو المسلسل، وسأجلبه لك فوراً للمشاهدة والتحميل!"
        )
        try:
            await event.delete()
            await bot.send_message(event.chat_id, welcome_text)
        except Exception:
            try:
                await event.edit(welcome_text, buttons=None)
            except Exception:
                await bot.send_message(event.chat_id, welcome_text)
    else:
        await event.answer("❌ لم تشترك في كافة القنوات المطلوبة بعد! يرجى الاشتراك في القنوات ثم الضغط مجدداً.", alert=True)
        text, buttons = admin_handlers.build_fsub_prompt(missing)
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. ADMIN PANEL CALLBACK ROUTER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.on(events.CallbackQuery(pattern=r'^adm_'))
async def admin_callback_router(event):
    if not admin_handlers.is_admin(event.sender_id):
        await event.answer("⚠️ غير مصرح لك بالوصول.", alert=True)
        return

    data = event.data.decode('utf-8')
    try:
        if data == "adm_main":
            ai_service.set_admin_ai_mode(event.sender_id, False)
            text = admin_handlers.get_main_menu_text()
            buttons = admin_handlers.get_main_menu_buttons()
            await event.edit(text, buttons=buttons)

        elif data == "adm_close":
            await event.delete()

        elif data == "adm_stats_menu":
            await event.edit(
                "📊 **قسم الإحصائيات الدقيقة**\n━━━━━━━━━━━━━━━━━━━━━\nاختر الفترة الزمنية التي تريد عرض تفاصيلها:",
                buttons=admin_handlers.get_stats_menu_buttons()
            )

        elif data.startswith("adm_stat_"):
            period = data.replace("adm_stat_", "")
            text, buttons = admin_handlers.get_period_stats_view(period)
            await event.edit(text, buttons=buttons)

        elif data == "adm_top_menu":
            await event.edit(
                "🔝 **قائمة الأعمال الأكثر طلباً وبحثاً**\n━━━━━━━━━━━━━━━━━━━━━\nاختر نوع الأعمال لعرض توب 50:",
                buttons=admin_handlers.get_top_menu_buttons()
            )

        elif data.startswith("adm_top_movies_"):
            page = int(data.split("_")[-1])
            text, buttons = admin_handlers.get_top_movies_view(page)
            await event.edit(text, buttons=buttons)

        elif data.startswith("adm_top_series_"):
            page = int(data.split("_")[-1])
            text, buttons = admin_handlers.get_top_series_view(page)
            await event.edit(text, buttons=buttons)

        elif data == "adm_fsub_menu":
            text, buttons = admin_handlers.get_fsub_view()
            await event.edit(text, buttons=buttons)

        elif data == "adm_fsub_toggle":
            is_on = admin_service.toggle_force_sub()
            st = "تفعيل 🟢" if is_on else "تعطيل 🔴"
            await event.answer(f"تم {st} الاشتراك الإجباري!", alert=True)
            text, buttons = admin_handlers.get_fsub_view()
            await event.edit(text, buttons=buttons)

        elif data == "adm_fsub_reset":
            admin_service.reset_all_users_subscription()
            await event.answer("🔄 تم تصفير كاش اشتراك جميع المستخدمين بنجاح! سيتوجب عليهم التحقق مجدداً.", alert=True)

        elif data.startswith("adm_fsub_del_"):
            ch_id = int(data.replace("adm_fsub_del_", ""))
            admin_service.delete_mandatory_channel(ch_id)
            await event.answer("🗑️ تم حذف جهة الاشتراك بنجاح!", alert=True)
            text, buttons = admin_handlers.get_fsub_view()
            await event.edit(text, buttons=buttons)

        elif data == "adm_fsub_add":
            text = (
                "➕ **إضافة جهة اشتراك إجباري جديدة**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "اختر نوع جهة الاشتراك التي ترغب بإضافتها:"
            )
            buttons = [
                [
                    Button.inline("📢 قناة", data="adm_fsub_t_channel"),
                    Button.inline("👥 قروب", data="adm_fsub_t_group"),
                    Button.inline("🤖 بوت", data="adm_fsub_t_bot")
                ],
                [Button.inline("❌ إلغاء", data="adm_fsub_menu")]
            ]
            await event.edit(text, buttons=buttons)

        elif data.startswith("adm_fsub_t_"):
            ch_type = data.replace("adm_fsub_t_", "")
            type_names = {'channel': 'القناة', 'group': 'القروب', 'bot': 'البوت'}
            admin_handlers.ADMIN_STATES[event.sender_id] = {
                'action': 'fsub_add_title',
                'type': ch_type
            }
            await event.edit(
                f"✏️ **أرسل الآن اسم {type_names.get(ch_type, 'الجهة')}** الذي سيظهر للمستخدمين في الأزرار (مثال: قناة الأفلام الرسمية):\n\n"
                "• للإلغاء في أي وقت، أرسل `/cancel`."
            )

        elif data == "adm_bcast_menu":
            text, buttons = admin_handlers.get_bcast_menu_view()
            await event.edit(text, buttons=buttons)

        elif data == "adm_bcast_start":
            admin_handlers.ADMIN_STATES[event.sender_id] = {'action': 'broadcast_await_msg'}
            await event.edit(
                "📢 **أرسل الآن الرسالة أو الوسائط التي تريد إذاعتها لجميع المستخدمين:**\n\n"
                "• يمكنك إرسال: نص، صورة، فيديو، ملف، أو إعادة توجيه (Forward).\n"
                "• للإلغاء في أي وقت، أرسل `/cancel`."
            )

        elif data == "adm_bcast_confirm":
            state = admin_handlers.ADMIN_STATES.get(event.sender_id)
            if not state or state.get('action') != 'broadcast_confirm':
                await event.answer("⚠️ لا توجد إذاعة جاهزة للتأكيد.", alert=True)
                return
            source_msg = state['msg']
            del admin_handlers.ADMIN_STATES[event.sender_id]
            await event.delete()
            user_ids = admin_service.get_all_user_ids()
            asyncio.create_task(admin_handlers.run_broadcast(bot, event.chat_id, source_msg, user_ids))

        elif data == "adm_bcast_cancel":
            if event.sender_id in admin_handlers.ADMIN_STATES:
                del admin_handlers.ADMIN_STATES[event.sender_id]
            await event.answer("تم إلغاء الإذاعة.", alert=True)
            text, buttons = admin_handlers.get_bcast_menu_view()
            await event.edit(text, buttons=buttons)

        elif data == "adm_ai_settings":
            text, buttons = admin_handlers.get_ai_settings_view()
            await event.edit(text, buttons=buttons)

        elif data == "adm_ai_set_key":
            admin_handlers.ADMIN_STATES[event.sender_id] = {'action': 'ai_await_key'}
            await event.edit(
                "✏️ **أرسل الآن مفتاح الـ API الخاص بك في رسالة:**\n\n"
                "• يدعم جميع أنواع مفاتيح Google Gemini (الحديثة `AQ....` والسابقة `AIzaSy...`).\n"
                "• يدعم أيضاً مفاتيح OpenRouter و Groq و DeepSeek و OpenAI و Anthropic.\n"
                "• مزود بنظام تعزيز ذكي (AI Booster) لتقوية أي نموذج تلقائياً!\n"
                "• للإلغاء في أي وقت، أرسل `/cancel`."
            )

        elif data == "adm_ai_test_key":
            key = ai_service.get_ai_api_key()
            if not key:
                await safe_answer(event, "⚠️ لم يتم إدخال أي مفتاح بعد!", alert=True)
                return
            await safe_answer(event, "⏳ جاري فحص واختبار المفتاح...")
            ok, msg = await asyncio.to_thread(ai_service.test_api_key, key)
            if ok:
                await safe_answer(event, "✅ الاتصال ناجح ومفتاح الذكاء الاصطناعي يعمل بكفاءة 100%!", alert=True)
                text, buttons = admin_handlers.get_ai_settings_view()
                await event.edit(text, buttons=buttons)
            else:
                await safe_answer(event, f"❌ فشل الاختبار: {msg[:100]}", alert=True)

        elif data == "adm_ai_chat":
            ai_service.set_admin_ai_mode(event.sender_id, True)
            text, buttons = admin_handlers.get_admin_ai_chat_view()
            await event.edit(text, buttons=buttons)

        elif data == "adm_ai_reset_mem":
            ai_service.clear_admin_ai_session(event.sender_id)
            await safe_answer(event, "🔄 تم مسح الذاكرة وبدء جلسة حوارية جديدة بنجاح!", alert=True)

        elif data == "adm_ai_exit":
            ai_service.set_admin_ai_mode(event.sender_id, False)
            text = admin_handlers.get_main_menu_text()
            buttons = admin_handlers.get_main_menu_buttons()
            await event.edit(text, buttons=buttons)
    except Exception as e:
        print(f"admin_callback_router error on {data}: {e}", flush=True)
        await safe_answer(event, f"⚠️ خطأ: {e}", alert=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5.5 USER AI CALLBACK ROUTER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.on(events.CallbackQuery(pattern=r'^ai_user_'))
async def ai_user_callback_handler(event):
    data = event.data.decode('utf-8')
    await safe_answer(event)

    if not admin_handlers.is_admin(event.sender_id):
        is_ok, missing = await admin_handlers.check_user_subscriptions(bot, event.sender_id)
        if not is_ok:
            await safe_answer(event, "⚠️ يجب عليك الاشتراك في القنوات أولاً للمتابعة!", alert=True)
            text, buttons = admin_handlers.build_fsub_prompt(missing)
            try:
                await bot.send_message(event.chat_id, text, buttons=buttons)
            except Exception:
                pass
            return

    if data == "ai_user_start":
        ai_service.set_user_ai_mode(event.sender_id, True)
        text = (
            "🧠 **المساعد السينمائي الذكي 🎬**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "أهلاً بك! يمكنك وصف أي فيلم أو مسلسل نسيت اسمه:\n"
            "• لقطة أو مشهد محدد أو فكرة القصة.\n"
            "• أسماء شخصيات أو أوصاف ممثلين.\n"
            "• أو اطلب ترشيحاً لأي تصنيف سينمائي تفضله.\n\n"
            "✍️ **تفضل بكتابة رسالتك وسأتعرف عليه فوراً:**"
        )
        buttons = [[Button.inline("❌ خروج من وضع الذكاء الاصطناعي", data="ai_user_exit")]]
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await bot.send_message(event.chat_id, text, buttons=buttons)

    elif data == "ai_user_suggest":
        ai_service.set_user_ai_mode(event.sender_id, True)
        text = (
            "✨ **الترشيحات السينمائية الذكية 🍿**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "أهلاً بك! اطلب ترشيحاتك السينمائية مباشرة:\n"
            "• *\"اقترح لي فيلم غموض بنهاية غير متوقعة\"*\n"
            "• *\"أفضل مسلسلات الجريمة القصيرة\"*\n\n"
            "✍️ **اكتب طلبك أو التصنيف المفضل وسأرشح لك الأفضل فوراً:**"
        )
        buttons = [[Button.inline("❌ خروج من وضع الذكاء الاصطناعي", data="ai_user_exit")]]
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            await bot.send_message(event.chat_id, text, buttons=buttons)

    elif data == "ai_user_exit":
        ai_service.set_user_ai_mode(event.sender_id, False)
        await safe_answer(event, "تم الخروج من وضع الذكاء الاصطناعي.")
        try:
            await event.edit("🔍 اكتب اسم أي فيلم أو مسلسل في الشات للبحث العادي:")
        except Exception:
            await bot.send_message(event.chat_id, "🔍 اكتب اسم أي فيلم أو مسلسل في الشات للبحث العادي:")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. SERIES SEASONS & EPISODES BROWSING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.on(events.CallbackQuery(pattern=r'^series_(\d+)'))
async def series_card_handler(event):
    admin_service.mark_user_interacted(event.sender_id)
    if not admin_handlers.is_admin(event.sender_id):
        is_ok, missing = await admin_handlers.check_user_subscriptions(bot, event.sender_id)
        if not is_ok:
            await event.answer("⚠️ يجب عليك الاشتراك في القنوات أولاً للمتابعة!", alert=True)
            text, buttons = admin_handlers.build_fsub_prompt(missing)
            await bot.send_message(event.chat_id, text, buttons=buttons)
            return

    item_id = int(event.pattern_match.group(1))
    item = get_media_item_by_id(item_id)
    if not item:
        await event.answer("⚠️ المسلسل غير متوفر.", alert=True)
        return

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
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"• عدد المواسم المتوفرة: **{len(seasons)}**\n"
        f"• اختر الموسم المطلوب لعرض حلقاته:"
    )
    await event.edit(text, buttons=season_buttons)

@bot.on(events.CallbackQuery(pattern=r'^season_(\d+)_(\d+)'))
async def season_episodes_handler(event):
    admin_service.mark_user_interacted(event.sender_id)
    if not admin_handlers.is_admin(event.sender_id):
        is_ok, missing = await admin_handlers.check_user_subscriptions(bot, event.sender_id)
        if not is_ok:
            await event.answer("⚠️ يجب عليك الاشتراك في القنوات أولاً للمتابعة!", alert=True)
            text, buttons = admin_handlers.build_fsub_prompt(missing)
            await bot.send_message(event.chat_id, text, buttons=buttons)
            return

    item_id = int(event.pattern_match.group(1))
    season_num = int(event.pattern_match.group(2))

    item = get_media_item_by_id(item_id)
    if not item:
        await event.answer("⚠️ حدث خطأ.", alert=True)
        return

    series_title = item['series_title']
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
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 **الموسم {season_num} — اختر الحلقة المناسبة :**"
    )
    await event.edit(text, buttons=episode_buttons)

@bot.on(events.CallbackQuery(pattern=r'^play_ep_(\d+)'))
async def play_episode_handler(event):
    admin_service.mark_user_interacted(event.sender_id)
    if not admin_handlers.is_admin(event.sender_id):
        is_ok, missing = await admin_handlers.check_user_subscriptions(bot, event.sender_id, force_live=True)
        if not is_ok:
            await event.answer("⚠️ يجب عليك الاشتراك في القنوات والقروبات المطلوبة أولاً للمتابعة!", alert=True)
            text, buttons = admin_handlers.build_fsub_prompt(missing)
            await bot.send_message(event.chat_id, text, buttons=buttons)
            return

    ep_id = int(event.pattern_match.group(1))

    item = get_media_item_by_id(ep_id)
    if not item:
        await event.answer("⚠️ الحلقة غير متوفرة.", alert=True)
        return

    await event.answer("⏳ جاري تحضير الحلقة...")

    status_msg = await event.reply("⏳ جاري تجهيز الفيديو وإرساله إليك...")

    next_ep = get_next_episode(item['series_title'], item['season_num'], item['episode_num'])
    buttons = []
    if next_ep:
        buttons.append([Button.inline("الحلقة التالية ▶️", data=f"play_ep_{next_ep['id']}")])
    buttons.append([
        Button.inline("قائمة الحلقات", data=f"season_{item['id']}_{item['season_num']}"),
        Button.inline("قائمة المواسم", data=f"series_{item['id']}")
    ])

    try:
        target_msg_id = item.get('target_msg_id')
        if not target_msg_id:
            await status_msg.edit("⚠️ الحلقة قيد التجهيز والنقل، يرجى المحاولة بعد قليل.")
            return

        storage_msg = await bot.get_messages(SERIES_CHANNEL, ids=target_msg_id)
        if storage_msg and storage_msg.media:
            if not verify_content_integrity(item, storage_msg):
                print(f"⚠️ Content Integrity Mismatch for series ep #{item['id']} ({item.get('series_title')}) vs storage msg #{target_msg_id}")
                await status_msg.edit("⚠️ جاري تحديث بيانات هذه الحلقة لضمان دقة المحتوى 100%، يرجى المحاولة بعد قليل.")
                return

            caption = format_caption(item, storage_msg=storage_msg)
            await bot.send_file(
                event.chat_id,
                storage_msg.media,
                caption=caption,
                supports_streaming=True,
                buttons=buttons
            )
            admin_service.log_delivery(event.chat_id, item['id'], 'series', item['series_title'])
            await status_msg.delete()
        else:
            await status_msg.edit("⚠️ تعذر إرسال الفيديو من القناة الرئيسية.")
    except Exception as e:
        await status_msg.edit(f"⚠️ حدث خطأ أثناء تجهيز الفيديو: {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. MOVIE DELIVERY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def deliver_movie_by_id(chat_id, movie_id, callback_event=None, reply_to=None):
    admin_service.mark_user_interacted(chat_id)
    if not admin_handlers.is_admin(chat_id):
        is_ok, missing = await admin_handlers.check_user_subscriptions(bot, chat_id, force_live=True)
        if not is_ok:
            if callback_event:
                await callback_event.answer("⚠️ يجب عليك الاشتراك في القنوات والقروبات المطلوبة أولاً للمتابعة!", alert=True)
            text, buttons = admin_handlers.build_fsub_prompt(missing)
            await bot.send_message(chat_id, text, buttons=buttons)
            return

    item = get_media_item_by_id(movie_id)

    if not item:
        if callback_event:
            await callback_event.answer("⚠️ الفيلم غير متوفر.", alert=True)
        elif reply_to:
            await bot.send_message(chat_id, "⚠️ الفيلم غير متوفر.", reply_to=reply_to)
        return

    if callback_event:
        await callback_event.answer("⏳ جاري إرسال الفيلم فوراً...")

    try:
        target_msg_id = item.get('target_msg_id')
        if not target_msg_id or target_msg_id <= 0:
            if callback_event:
                await callback_event.answer("⚠️ الفيلم قيد التجهيز والنقل، يرجى المحاولة بعد قليل.", alert=True)
            elif reply_to:
                await bot.send_message(chat_id, "⚠️ الفيلم قيد التجهيز والنقل، يرجى المحاولة بعد قليل.", reply_to=reply_to)
            return

        storage_msg = await bot.get_messages(MOVIES_CHANNEL, ids=target_msg_id)
        if storage_msg and storage_msg.media:
            if not verify_content_integrity(item, storage_msg):
                print(f"⚠️ Content Integrity Mismatch for movie #{item['id']} ({item.get('clean_title')}) vs storage msg #{target_msg_id}")
                msg_fail = "⚠️ جاري تحديث بيانات هذا الفيلم لضمان دقة المحتوى 100%، يرجى المحاولة بعد قليل."
                if callback_event:
                    await callback_event.answer(msg_fail, alert=True)
                elif reply_to:
                    await bot.send_message(chat_id, msg_fail, reply_to=reply_to)
                return

            caption = format_caption(item, storage_msg=storage_msg)
            await bot.send_file(
                chat_id,
                storage_msg.media,
                caption=caption,
                supports_streaming=True
            )
            admin_service.log_delivery(chat_id, item['id'], 'movie', item['clean_title'])
        else:
            await bot.send_message(chat_id, "⚠️ تعذر جلب ملف الفيلم من القناة الرئيسية.", reply_to=reply_to)
    except Exception as e:
        print(f"Delivery error: {e}")
        await bot.send_message(chat_id, f"⚠️ حدث خطأ أثناء إرسال الفيلم: {e}", reply_to=reply_to)

@bot.on(events.CallbackQuery(pattern=r'^movie_(\d+)'))
async def play_movie_handler(event):
    movie_id = int(event.pattern_match.group(1))
    await deliver_movie_by_id(event.chat_id, movie_id, callback_event=event)

@bot.on(events.CallbackQuery(pattern=r'^back_search'))
async def back_search_handler(event):
    await event.edit("🔍 اكتب اسم أي فيلم أو مسلسل في الشات للبحث:")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 8. MAIN ENTRY POINT WITH RECONNECT RESILIENCE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def main(state_dict: dict = None):
    def _bg_setup():
        try:
            import urllib.request
            import json
            for lc in ['', 'ar']:
                cmd_data = {
                    'commands': [
                        {'command': 'start', 'description': 'بدء تشغيل البوت والبحث 🎬'},
                        {'command': 'ai', 'description': 'باحث المشاهد بالذكاء الاصطناعي 🧠'},
                        {'command': 'support', 'description': 'الدعم الفني والمساعدة 👨‍💻'}
                    ]
                }
                if lc:
                    cmd_data['language_code'] = lc
                req_cmd = urllib.request.Request(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands",
                    data=json.dumps(cmd_data).encode('utf-8'),
                    headers={'Content-Type': 'application/json'}
                )
                try:
                    urllib.request.urlopen(req_cmd, timeout=8)
                except Exception:
                    pass

            req_menu = urllib.request.Request(
                f"https://api.telegram.org/bot{BOT_TOKEN}/setChatMenuButton",
                data=json.dumps({'menu_button': {'type': 'commands'}}).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            try:
                urllib.request.urlopen(req_menu, timeout=8)
            except Exception:
                pass
            print("Bot menu commands registered successfully in background!")
        except Exception as e:
            print(f"Notice setting bot commands: {e}")

        try:
            admin_service.init_user_cache()
        except Exception as e:
            print(f"Notice init user cache: {e}")

    while True:
        try:
            print("Connecting Bot @zxeeabot...")
            await bot.start(bot_token=BOT_TOKEN)
            me = await bot.get_me()
            print(f"Bot @{me.username} ({me.first_name}) is LIVE and LISTENING for messages!", flush=True)

            if state_dict is not None:
                state_dict["connected"] = True
                state_dict["username"] = f"@{me.username}" if me.username else "@zxeeabot"
                state_dict["id"] = me.id
                state_dict["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

            # Run setup in background thread to avoid freezing the event loop
            import threading
            threading.Thread(target=_bg_setup, daemon=True).start()

            await bot.run_until_disconnected()
        except Exception as e:
            print(f"Bot disconnected ({e}). Reconnecting in 3s...", flush=True)
            if state_dict is not None:
                state_dict["connected"] = False
                state_dict["last_error"] = str(e)
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())
