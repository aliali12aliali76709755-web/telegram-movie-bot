import asyncio
import time
from telethon import events, Button
from telethon.errors import (
    UserIsBlockedError,
    InputUserDeactivatedError,
    FloodWaitError,
    UserNotParticipantError,
    ChatAdminRequiredError,
    ChannelPrivateError,
    ChannelInvalidError
)
import admin_service

ADMIN_ID = 8625825633
ADMIN_IDS = {8625825633, 6641619062}
ADMIN_STATES = {}  # admin_id: {'action': ..., 'data': ...}

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS or user_id in admin_service.ADMIN_IDS

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. MAIN ADMIN PANEL VIEW
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_main_menu_text():
    overview = admin_service.get_users_overview()
    fsub_status = "مفعل 🟢" if admin_service.is_force_sub_enabled() else "معطل 🔴"
    channels = admin_service.get_mandatory_channels()
    return (
        "👑 **لوحة تحكم الإدارة الرسمية**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👋 أهلاً بك سيدي المدير (`{ADMIN_ID}`).\n\n"
        f"📊 **نظرة عامة على النظام:**\n"
        f"• 👥 إجمالي المستخدمين: **{overview['total']:,}**\n"
        f"• ✅ المشتركون بالقنوات: **{overview['subscribed']:,}**\n"
        f"• 🚫 المحظورون / المعطلون: **{overview['blocked']:,}**\n"
        f"• 🔐 الاشتراك الإجباري: **{fsub_status}** ({len(channels)} جهة)\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "اختر القسم المطلوب لإدارته:"
    )

def get_main_menu_buttons():
    return [
        [
            Button.inline("📊 الإحصائيات الشاملة", data="adm_stats_menu"),
            Button.inline("📢 الإذاعة الجماعية", data="adm_bcast_menu")
        ],
        [
            Button.inline("🔐 الاشتراك الإجباري", data="adm_fsub_menu"),
            Button.inline("🔝 الأكثر طلباً (توب 50)", data="adm_top_menu")
        ],
        [
            Button.inline("🔄 تحديث اللوحة", data="adm_main"),
            Button.inline("❌ إغلاق", data="adm_close")
        ]
    ]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. STATS VIEW
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_stats_menu_buttons():
    return [
        [
            Button.inline("📅 إحصائيات اليوم", data="adm_stat_today"),
            Button.inline("📅 هذا الأسبوع", data="adm_stat_week")
        ],
        [
            Button.inline("📅 هذا الشهر", data="adm_stat_month"),
            Button.inline("📅 هذه السنة", data="adm_stat_year")
        ],
        [
            Button.inline("🌐 الإحصائيات الشاملة (الكل)", data="adm_stat_all")
        ],
        [
            Button.inline("🔙 رجوع للرئيسية", data="adm_main")
        ]
    ]

def get_period_stats_view(period: str):
    period_data = admin_service.get_stats_for_period(period)
    text = admin_service.format_period_report(period, period_data)
    buttons = [
        [
            Button.inline("🔄 تحديث", data=f"adm_stat_{period}"),
            Button.inline("🔙 باقي الفترات", data="adm_stats_menu")
        ],
        [
            Button.inline("🏠 الرئيسية", data="adm_main")
        ]
    ]
    return text, buttons

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. TOP 50 VIEWS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_top_menu_buttons():
    return [
        [
            Button.inline("🎬 توب 50 أفلام", data="adm_top_movies_1"),
            Button.inline("📺 توب 50 مسلسلات", data="adm_top_series_1")
        ],
        [
            Button.inline("🔙 رجوع للرئيسية", data="adm_main")
        ]
    ]

def get_top_movies_view(page: int = 1):
    items = admin_service.get_top_50_movies()
    start_idx = (page - 1) * 25
    page_items = items[start_idx:start_idx + 25]
    
    lines = [f"🔝 **أكثر 50 فيلماً طلباً وبحثاً (صفحة {page}/2):**\n━━━━━━━━━━━━━━━━━━━━━"]
    for i, item in enumerate(page_items, start=start_idx + 1):
        lines.append(f"{i}. 🎬 **{item['title']}** — ({item['req_count']} طلب)")
    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    text = "\n".join(lines)

    nav_row = []
    if page == 1:
        nav_row.append(Button.inline("الصفحة التالية ➡️", data="adm_top_movies_2"))
    else:
        nav_row.append(Button.inline("⬅️ الصفحة السابقة", data="adm_top_movies_1"))
    nav_row.append(Button.inline("🔙 رجوع", data="adm_top_menu"))

    return text, [nav_row, [Button.inline("🏠 الرئيسية", data="adm_main")]]

def get_top_series_view(page: int = 1):
    items = admin_service.get_top_50_series()
    start_idx = (page - 1) * 25
    page_items = items[start_idx:start_idx + 25]

    lines = [f"🔝 **أكثر 50 مسلسلاً طلباً وبحثاً (صفحة {page}/2):**\n━━━━━━━━━━━━━━━━━━━━━"]
    for i, item in enumerate(page_items, start=start_idx + 1):
        lines.append(f"{i}. 📺 **{item['title']}** — ({item['req_count']} طلب)")
    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    text = "\n".join(lines)

    nav_row = []
    if page == 1:
        nav_row.append(Button.inline("الصفحة التالية ➡️", data="adm_top_series_2"))
    else:
        nav_row.append(Button.inline("⬅️ الصفحة السابقة", data="adm_top_series_1"))
    nav_row.append(Button.inline("🔙 رجوع", data="adm_top_menu"))

    return text, [nav_row, [Button.inline("🏠 الرئيسية", data="adm_main")]]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. MANDATORY SUBSCRIPTION VIEW
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_fsub_view():
    is_on = admin_service.is_force_sub_enabled()
    status_text = "مفعل 🟢" if is_on else "معطل 🔴"
    channels = admin_service.get_mandatory_channels()

    lines = [
        "🔐 **إدارة نظام الاشتراك الإجباري**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"• حالة النظام الحالية: **{status_text}**\n"
        f"• إجمالي الجهات المضافة: **{len(channels)}**\n"
    ]

    type_icons = {'channel': '📢 قناة', 'group': '👥 قروب', 'bot': '🤖 بوت'}

    if channels:
        lines.append("\n📋 **قائمة القنوات والقروبات والبوتات:**")
        for ch in channels:
            st = "✅ نشط" if ch['is_active'] else "⏸️ متوقف"
            t_name = type_icons.get(ch['channel_type'], ch['channel_type'])
            lines.append(f"• {t_name}: **{ch['title']}** [{st}]")
            lines.append(f"   🔗 الرابط: `{ch['link_or_username']}`")
            if ch['chat_id']:
                lines.append(f"   🆔 الآيدي: `{ch['chat_id']}`")
    else:
        lines.append("\n⚠️ لم تقم بإضافة أي قناة أو قروب أو بوت بعد.")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━\nاختر الإجراء المطلوب:")
    text = "\n".join(lines)

    buttons = []
    # Toggle button
    btn_toggle_text = "🔴 تعطيل الاشتراك الإجباري" if is_on else "🟢 تفعيل الاشتراك الإجباري"
    buttons.append([Button.inline(btn_toggle_text, data="adm_fsub_toggle")])
    buttons.append([Button.inline("➕ إضافة قناة / قروب / بوت", data="adm_fsub_add")])

    # Delete buttons for each channel
    for ch in channels:
        t_icon = '📢' if ch['channel_type'] == 'channel' else ('👥' if ch['channel_type'] == 'group' else '🤖')
        buttons.append([
            Button.inline(f"❌ حذف {t_icon} {ch['title'][:20]}", data=f"adm_fsub_del_{ch['id']}")
        ])

    buttons.append([Button.inline("🔄 إعادة فحص اشتراك المستخدمين", data="adm_fsub_reset")])
    buttons.append([Button.inline("🔙 رجوع للرئيسية", data="adm_main")])

    return text, buttons

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. BROADCAST VIEW
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_bcast_menu_view():
    overview = admin_service.get_users_overview()
    text = (
        "📢 **نظام الإذاعة الجماعية (Broadcast)**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 إجمالي المستخدمين المسجلين: **{overview['total']:,}**\n"
        f"• النشطون حالياً: **{overview['active']:,}**\n"
        f"• المحظورون / المعطلون: **{overview['blocked']:,}**\n\n"
        "⚡ **ملاحظة:** سيتم إرسال الإذاعة لجميع المستخدمين الذين استخدموا البوت، "
        "مع كشف وتسجيل من قام بحظر البوت تلقائياً في الإحصائيات.\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )
    buttons = [
        [Button.inline("📨 بدء إذاعة جديدة", data="adm_bcast_start")],
        [Button.inline("🔙 رجوع للرئيسية", data="adm_main")]
    ]
    return text, buttons

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. BROADCAST EXECUTION ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def run_broadcast(bot, admin_chat_id: int, source_msg, user_ids: list):
    status_msg = await bot.send_message(
        admin_chat_id,
        "🚀 **بدأت عملية الإذاعة الجماعية...**\n"
        f"👥 إجمالي المستهدفين: **{len(user_ids):,}** مستخدم\n"
        "⏳ يرجى الانتظار..."
    )

    total = len(user_ids)
    sent = 0
    blocked = 0
    failed = 0
    start_time = time.time()
    last_update_time = time.time()

    for idx, uid in enumerate(user_ids, start=1):
        try:
            # Send message or forward
            if source_msg.fwd_from:
                await bot.forward_messages(uid, source_msg)
            elif source_msg.media:
                await bot.send_file(uid, source_msg.media, caption=source_msg.text)
            else:
                await bot.send_message(uid, source_msg.text)
            sent += 1
        except UserIsBlockedError:
            blocked += 1
            admin_service.mark_user_blocked(uid, 1)
        except InputUserDeactivatedError:
            blocked += 1
            admin_service.mark_user_blocked(uid, 1)
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 1)
            try:
                if source_msg.media:
                    await bot.send_file(uid, source_msg.media, caption=source_msg.text)
                else:
                    await bot.send_message(uid, source_msg.text)
                sent += 1
            except Exception:
                failed += 1
        except Exception as e:
            failed += 1

        # Periodic live status update every 3 seconds or 30 users
        if time.time() - last_update_time > 3 or idx == total:
            pct = round((idx / total) * 100, 1)
            elapsed = round(time.time() - start_time, 1)
            try:
                await status_msg.edit(
                    f"📢 **جاري تنفيذ الإذاعة الجماعية... ({pct}%)**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👥 التقدم: **{idx:,}** من **{total:,}**\n"
                    f"✅ تم الإرسال بنجاح: **{sent:,}**\n"
                    f"🚫 حظر/حساب محذوف: **{blocked:,}**\n"
                    f"⚠️ أخطاء أخرى: **{failed:,}**\n"
                    f"⏱️ الوقت المنقضي: **{elapsed}** ثانية\n"
                    f"━━━━━━━━━━━━━━━━━━━━━"
                )
                last_update_time = time.time()
            except Exception:
                pass
        
        # Gentle throttling to avoid flood bans
        await asyncio.sleep(0.04)

    total_time = round(time.time() - start_time, 1)
    await bot.send_message(
        admin_chat_id,
        f"🎉 **اكتملت الإذاعة الجماعية بنجاح!**\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 إجمالي المستهدفين: **{total:,}**\n"
        f"✅ تم التسليم بنجاح: **{sent:,}**\n"
        f"🚫 مستخدمين حظروا البوت: **{blocked:,}**\n"
        f"⚠️ فشل الإرسال: **{failed:,}**\n"
        f"⏱️ استغرقت العملية كاملة: **{total_time}** ثانية\n"
        f"━━━━━━━━━━━━━━━━━━━━━",
        buttons=[[Button.inline("🏠 الرئيسية", data="adm_main")]]
    )

_CHANNEL_ENTITY_CACHE = {}

async def check_user_subscriptions(bot, user_id: int, force_live: bool = False):
    """
    Checks if a user is subscribed to all active mandatory channels/groups/bots.
    Strictly verifies live membership so users who leave after subscribing cannot use the bot.
    Returns: (is_ok: bool, missing_list: list)
    """
    if not admin_service.is_force_sub_enabled():
        return True, []

    if is_admin(user_id):
        return True, []

    # If not force_live, allow a 20-second fast window for consecutive clicks
    if not force_live and admin_service.is_user_cached_subscribed(user_id):
        return True, []

    channels = admin_service.get_active_mandatory_channels()
    if not channels:
        return True, []

    missing = []
    for ch in channels:
        ch_type = ch.get('channel_type', 'channel')
        if ch_type == 'bot':
            continue

        identifier = ch.get('chat_id') or ch.get('link_or_username')
        if not identifier:
            continue

        identifier_clean = identifier.strip()
        if "t.me/" in identifier_clean:
            parts = identifier_clean.split("t.me/")
            if len(parts) > 1 and not parts[1].startswith("+") and not parts[1].startswith("joinchat"):
                identifier_clean = f"@{parts[1].split('/')[0]}"

        try:
            if identifier_clean.startswith("-100") or identifier_clean.isdigit() or (identifier_clean.startswith("-") and identifier_clean[1:].isdigit()):
                target_entity = int(identifier_clean)
            else:
                target_entity = identifier_clean

            entity = _CHANNEL_ENTITY_CACHE.get(str(target_entity))
            if entity is None:
                entity = await bot.get_entity(target_entity)
                _CHANNEL_ENTITY_CACHE[str(target_entity)] = entity

            from telethon.tl.functions.channels import GetParticipantRequest
            await bot(GetParticipantRequest(channel=entity, participant=user_id))
        except UserNotParticipantError:
            missing.append(ch)
        except FloodWaitError as fwe:
            print(f"Telegram FloodWait ({fwe.seconds}s) on check_user_subscriptions")
            if fwe.seconds < 3:
                await asyncio.sleep(fwe.seconds + 0.5)
            else:
                return True, []
        except Exception as e:
            print(f"Could not verify subscription in {ch.get('title')}: {e}")
            pass

    if missing:
        # User is NOT a participant in all required channels! Mark unsubscribed!
        admin_service.mark_user_unsubscribed(user_id)
        return False, missing

    # Confirmed subscribed right now!
    admin_service.mark_user_subscribed(user_id)
    return True, []

def build_fsub_prompt(missing_channels: list):
    text = (
        "⚠️ **عذراً عزيزي، يجب عليك الاشتراك في القنوات التالية أولاً لاستخدام البوت:**\n\n"
        "اشترك في القنوات عبر الأزرار أدناه، ثم اضغط على زر **(✅ تحقق من الاشتراك)** للدخول فوراً:"
    )
    buttons = []
    type_labels = {'channel': '📢', 'group': '👥', 'bot': '🤖'}
    for ch in missing_channels:
        lbl = type_labels.get(ch.get('channel_type', 'channel'), '📢')
        url = ch.get('link_or_username', '')
        if not url.startswith('http'):
            url = f"https://t.me/{url.replace('@', '')}"
        ch_title = (ch.get('title') or '').strip() or url.split('/')[-1]
        buttons.append([Button.url(f"{lbl} {ch_title}", url=url)])

    buttons.append([Button.inline("✅ تحقق من الاشتراك", data="check_sub")])
    return text, buttons
