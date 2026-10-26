import sqlite3
import os
import re
import threading
import time
from datetime import datetime, timedelta

DEFAULT_MONGO_URI = "mongodb+srv://bosshoeheoejossnpe_db_user:eQl1SyEvwIRDMs1w@cluster0.etprryl.mongodb.net/?retryWrites=true&w=majority"
DB_PATH = os.path.join(os.path.dirname(__file__), "movies.db")
ADMIN_ID = 8625825633
ADMIN_IDS = {8625825633, 6641619062}

_mongo_client = None
_SUBSCRIBED_CACHE = set()
_RECORDED_CACHE = {}  # user_id -> timestamp
_CACHE_INITIALIZED = False

def init_user_cache():
    global _CACHE_INITIALIZED
    if _CACHE_INITIALIZED:
        return
    try:
        mdb = get_mongo_db()
        if mdb is not None:
            now_ts = time.time()
            for doc in mdb['bot_users'].find({'is_subscribed': 1}, {'user_id': 1}):
                _SUBSCRIBED_CACHE.add(doc['user_id'])
            for doc in mdb['bot_users'].find({}, {'user_id': 1}):
                _RECORDED_CACHE[doc['user_id']] = now_ts
            _CACHE_INITIALIZED = True
            print(f"init_user_cache: Cached {len(_SUBSCRIBED_CACHE)} subscribed users and {len(_RECORDED_CACHE)} total users in RAM.")
            return
    except Exception as e:
        print(f"init_user_cache mongo warning: {e}")

    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS bot_users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, first_seen TIMESTAMP, last_seen TIMESTAMP, is_subscribed INTEGER DEFAULT 0, is_blocked INTEGER DEFAULT 0, has_interacted INTEGER DEFAULT 0)")
        c.execute("SELECT user_id, is_subscribed FROM bot_users")
        now_ts = time.time()
        for r in c.fetchall():
            uid = r['user_id']
            _RECORDED_CACHE[uid] = now_ts
            if r['is_subscribed'] == 1:
                _SUBSCRIBED_CACHE.add(uid)
        conn.close()
        _CACHE_INITIALIZED = True
        print(f"init_user_cache (sqlite): Cached {len(_SUBSCRIBED_CACHE)} subscribed users and {len(_RECORDED_CACHE)} total users in RAM.")
    except Exception as e:
        print(f"init_user_cache sqlite warning: {e}")

def get_mongo_db():
    try:
        import database
        return database.get_mongo_db()
    except Exception as e:
        print(f"Admin service get_mongo_db error: {e}")
        return None
_SQLITE_INITED = False
def get_connection():
    global _SQLITE_INITED
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    if not _SQLITE_INITED:
        try:
            c = conn.cursor()
            c.executescript("""
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                first_seen TIMESTAMP,
                last_seen TIMESTAMP,
                is_subscribed INTEGER DEFAULT 0,
                is_blocked INTEGER DEFAULT 0,
                has_interacted INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS search_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                query TEXT,
                matched_title TEXT,
                is_series INTEGER DEFAULT 0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS delivery_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                media_id INTEGER,
                media_type TEXT,
                title TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS mandatory_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                link_or_username TEXT,
                chat_id TEXT,
                channel_type TEXT DEFAULT 'channel',
                is_active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """)
            conn.commit()
            _SQLITE_INITED = True
        except Exception:
            pass
    return conn

# 1. USER TRACKING (HIGH-CONCURRENCY NON-BLOCKING)
def record_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
    init_user_cache()
    now_ts = time.time()
    # If user was already recorded in the last 15 minutes, skip DB completely!
    if user_id in _RECORDED_CACHE and (now_ts - _RECORDED_CACHE[user_id]) < 900:
        return
    _RECORDED_CACHE[user_id] = now_ts

    def _bg_record():
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        mdb = get_mongo_db()
        if mdb is not None:
            try:
                set_fields = {'last_seen': now_str}
                if username: set_fields['username'] = username
                if first_name: set_fields['first_name'] = first_name
                if last_name: set_fields['last_name'] = last_name

                mdb['bot_users'].update_one(
                    {'user_id': user_id},
                    {
                        '$set': set_fields,
                        '$setOnInsert': {
                            'user_id': user_id,
                            'first_seen': now_str,
                            'is_subscribed': 0,
                            'is_blocked': 0,
                            'has_interacted': 0
                        }
                    },
                    upsert=True
                )
                return
            except Exception as e:
                print(f"record_user mongo notice: {e}")

        try:
            conn = get_connection()
            c = conn.cursor()
            c.execute("""
            INSERT INTO bot_users (user_id, username, first_name, last_name, first_seen, last_seen)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                username = coalesce(excluded.username, bot_users.username),
                first_name = coalesce(excluded.first_name, bot_users.first_name),
                last_name = coalesce(excluded.last_name, bot_users.last_name),
                last_seen = CURRENT_TIMESTAMP
            """, (user_id, username, first_name, last_name))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"record_user sqlite notice: {e}")

    threading.Thread(target=_bg_record, daemon=True).start()

_RECENT_VERIFIED = {}  # user_id -> float timestamp (TTL 20 seconds)

def mark_user_subscribed(user_id: int):
    _RECENT_VERIFIED[user_id] = time.time()
    def _bg_sub():
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        mdb = get_mongo_db()
        if mdb is not None:
            try:
                mdb['bot_users'].update_one({'user_id': user_id}, {'$set': {'is_subscribed': 1, 'last_seen': now_str}}, upsert=True)
                return
            except Exception:
                pass

        try:
            conn = get_connection()
            c = conn.cursor()
            c.execute("UPDATE bot_users SET is_subscribed = 1, last_seen = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
        except Exception:
            pass

    threading.Thread(target=_bg_sub, daemon=True).start()

def mark_user_unsubscribed(user_id: int):
    _RECENT_VERIFIED.pop(user_id, None)
    if user_id in _SUBSCRIBED_CACHE:
        _SUBSCRIBED_CACHE.discard(user_id)
    def _bg_unsub():
        mdb = get_mongo_db()
        if mdb is not None:
            try:
                mdb['bot_users'].update_one({'user_id': user_id}, {'$set': {'is_subscribed': 0}})
                return
            except Exception:
                pass

        try:
            conn = get_connection()
            c = conn.cursor()
            c.execute("UPDATE bot_users SET is_subscribed = 0 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
        except Exception:
            pass

    threading.Thread(target=_bg_unsub, daemon=True).start()

def is_user_cached_subscribed(user_id: int) -> bool:
    # Strict short-lived verification: ONLY valid if verified in the last 15 seconds!
    # If more than 15 seconds passed, caller MUST perform live Telegram check!
    return (time.time() - _RECENT_VERIFIED.get(user_id, 0)) < 15

def reset_all_users_subscription():
    _RECENT_VERIFIED.clear()
    _SUBSCRIBED_CACHE.clear()
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            mdb['bot_users'].update_many({}, {'$set': {'is_subscribed': 0}})
            return
        except Exception:
            pass

    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE bot_users SET is_subscribed = 0")
    conn.commit()
    conn.close()

def mark_user_interacted(user_id: int):
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            mdb['bot_users'].update_one({'user_id': user_id}, {'$set': {'has_interacted': 1, 'last_seen': now_str}})
            return
        except Exception:
            pass

    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE bot_users SET has_interacted = 1, last_seen = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def mark_user_blocked(user_id: int, is_blocked: int = 1):
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            mdb['bot_users'].update_one({'user_id': user_id}, {'$set': {'is_blocked': is_blocked}})
            return
        except Exception:
            pass

    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE bot_users SET is_blocked = ? WHERE user_id = ?", (is_blocked, user_id))
    conn.commit()
    conn.close()

def get_all_user_ids():
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            return [u['user_id'] for u in mdb['bot_users'].find({}, {'user_id': 1}).sort('first_seen', -1)]
        except Exception:
            pass

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT user_id FROM bot_users ORDER BY first_seen DESC")
    ids = [r[0] for r in c.fetchall()]
    conn.close()
    return ids

def get_users_overview():
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            col = mdb['bot_users']
            total = col.count_documents({})
            blocked = col.count_documents({'is_blocked': 1})
            subscribed = col.count_documents({'is_subscribed': 1})
            return {
                'total': total,
                'active': total - blocked,
                'blocked': blocked,
                'subscribed': subscribed
            }
        except Exception:
            pass

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM bot_users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM bot_users WHERE is_blocked = 1")
    blocked = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM bot_users WHERE is_subscribed = 1")
    subscribed = c.fetchone()[0]
    conn.close()
    return {
        'total': total,
        'active': total - blocked,
        'blocked': blocked,
        'subscribed': subscribed
    }

# 2. MANDATORY CHANNELS
def get_mandatory_channels():
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            return list(mdb['mandatory_channels'].find().sort('id', 1))
        except Exception:
            pass

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM mandatory_channels ORDER BY id ASC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_active_mandatory_channels():
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            return list(mdb['mandatory_channels'].find({'is_active': 1}).sort('id', 1))
        except Exception:
            pass

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM mandatory_channels WHERE is_active = 1 ORDER BY id ASC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def add_mandatory_channel(title: str, link_or_username: str, chat_id: str = None, channel_type: str = "channel"):
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            col = mdb['mandatory_channels']
            last = col.find_one(sort=[('id', -1)])
            new_id = (last['id'] + 1) if last and 'id' in last else 1
            col.insert_one({
                'id': new_id,
                'title': title,
                'link_or_username': link_or_username,
                'chat_id': chat_id,
                'channel_type': channel_type,
                'is_active': 1
            })
            return new_id
        except Exception as e:
            print(f"add_mandatory_channel mongo error: {e}")

    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO mandatory_channels (title, link_or_username, chat_id, channel_type, is_active)
    VALUES (?, ?, ?, ?, 1)
    """, (title, link_or_username, chat_id, channel_type))
    conn.commit()
    new_id = c.lastrowid
    conn.close()
    return new_id

def delete_mandatory_channel(channel_id: int):
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            mdb['mandatory_channels'].delete_one({'id': channel_id})
            return
        except Exception:
            pass

    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM mandatory_channels WHERE id = ?", (channel_id,))
    conn.commit()
    conn.close()

def toggle_mandatory_channel(channel_id: int):
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            col = mdb['mandatory_channels']
            ch = col.find_one({'id': channel_id})
            if ch:
                col.update_one({'id': channel_id}, {'$set': {'is_active': 1 - ch.get('is_active', 1)}})
            return
        except Exception:
            pass

    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE mandatory_channels SET is_active = 1 - is_active WHERE id = ?", (channel_id,))
    conn.commit()
    conn.close()

# 3. SETTINGS
def get_setting(key: str, default: str = None):
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            s = mdb['bot_settings'].find_one({'key': key})
            return s['value'] if s and 'value' in s else default
        except Exception:
            pass

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key: str, value: str):
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            mdb['bot_settings'].update_one({'key': key}, {'$set': {'value': str(value)}}, upsert=True)
            return
        except Exception:
            pass

    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO bot_settings (key, value) VALUES (?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, str(value)))
    conn.commit()
    conn.close()

def is_force_sub_enabled() -> bool:
    return get_setting('force_sub_enabled', '0') == '1'

def toggle_force_sub() -> bool:
    cur = is_force_sub_enabled()
    new_val = '0' if cur else '1'
    set_setting('force_sub_enabled', new_val)
    return new_val == '1'

# 4. LOGGING SEARCHES & DELIVERIES
def log_search(user_id: int, query: str, matched_title: str = None, is_series: int = 0):
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            mdb['search_logs'].insert_one({
                'user_id': user_id,
                'query': query,
                'matched_title': matched_title,
                'is_series': is_series,
                'timestamp': now_str
            })
            mark_user_interacted(user_id)
            return
        except Exception as e:
            print(f"log_search mongo error: {e}")

    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
        INSERT INTO search_logs (user_id, query, matched_title, is_series)
        VALUES (?, ?, ?, ?)
        """, (user_id, query, matched_title, is_series))
        c.execute("UPDATE bot_users SET has_interacted = 1, last_seen = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"log_search error: {e}")

def log_delivery(user_id: int, media_id: int, media_type: str, title: str):
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            mdb['delivery_logs'].insert_one({
                'user_id': user_id,
                'media_id': media_id,
                'media_type': media_type,
                'title': title,
                'timestamp': now_str
            })
            mark_user_interacted(user_id)
            return
        except Exception as e:
            print(f"log_delivery mongo error: {e}")

    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
        INSERT INTO delivery_logs (user_id, media_id, media_type, title)
        VALUES (?, ?, ?, ?)
        """, (user_id, media_id, media_type, title))
        c.execute("UPDATE bot_users SET has_interacted = 1, last_seen = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"log_delivery error: {e}")

# 5. MULTI-TIMEFRAME ANALYTICS
TIMEFRAME_SQL = {
    'today': "timestamp >= datetime('now', 'start of day')",
    'week': "timestamp >= datetime('now', '-7 days')",
    'month': "timestamp >= datetime('now', 'start of month')",
    'year': "timestamp >= datetime('now', 'start of year')",
    'all': "1=1"
}

TIMEFRAME_USER_FIRST_SEEN = {
    'today': "first_seen >= datetime('now', 'start of day')",
    'week': "first_seen >= datetime('now', '-7 days')",
    'month': "first_seen >= datetime('now', 'start of month')",
    'year': "first_seen >= datetime('now', 'start of year')",
    'all': "1=1"
}

TIMEFRAME_USER_LAST_SEEN = {
    'today': "last_seen >= datetime('now', 'start of day')",
    'week': "last_seen >= datetime('now', '-7 days')",
    'month': "last_seen >= datetime('now', 'start of month')",
    'year': "last_seen >= datetime('now', 'start of year')",
    'all': "1=1"
}

PERIOD_NAMES = {
    'today': "اليوم 📅",
    'week': "هذا الأسبوع 📅",
    'month': "هذا الشهر 📅",
    'year': "هذه السنة 📅",
    'all': "الشاملة (منذ البداية) 🌐"
}

_STATS_CACHE = {}  # period -> (timestamp, data)

def get_stats_for_period(p: str):
    now_ts = time.time()
    if p in _STATS_CACHE:
        cached_ts, cached_data = _STATS_CACHE[p]
        if now_ts - cached_ts < 30:
            return cached_data

    mdb = get_mongo_db()
    if mdb is not None:
        try:
            now_dt = datetime.utcnow()
            date_filters = {
                'today': now_dt.strftime('%Y-%m-%d 00:00:00'),
                'week': (now_dt - timedelta(days=7)).strftime('%Y-%m-%d 00:00:00'),
                'month': now_dt.strftime('%Y-%m-01 00:00:00'),
                'year': now_dt.strftime('%Y-01-01 00:00:00'),
                'all': None
            }
            start_str = date_filters.get(p)
            u_col = mdb['bot_users']
            s_col = mdb['search_logs']
            d_col = mdb['delivery_logs']

            if p == 'all' or not start_str:
                tot_u = u_col.count_documents({})
                new_u = tot_u
                ret_u = 0
                idl_u = u_col.count_documents({'is_subscribed': 0, 'has_interacted': 0})
                sub_u = u_col.count_documents({'is_subscribed': 1})
                tot_s = s_col.count_documents({})
                mov_d = d_col.count_documents({'media_type': 'movie'})
                ser_d = d_col.count_documents({'media_type': 'series'})
            else:
                tot_u = u_col.count_documents({'last_seen': {'$gte': start_str}})
                new_u = u_col.count_documents({'first_seen': {'$gte': start_str}})
                ret_u = u_col.count_documents({'first_seen': {'$lt': start_str}, 'last_seen': {'$gte': start_str}})
                idl_u = u_col.count_documents({'is_subscribed': 0, 'has_interacted': 0, 'first_seen': {'$gte': start_str}})
                sub_u = u_col.count_documents({'is_subscribed': 1, 'last_seen': {'$gte': start_str}})
                tot_s = s_col.count_documents({'timestamp': {'$gte': start_str}})
                mov_d = d_col.count_documents({'media_type': 'movie', 'timestamp': {'$gte': start_str}})
                ser_d = d_col.count_documents({'media_type': 'series', 'timestamp': {'$gte': start_str}})

            res = {
                'total_users': tot_u,
                'idle_users': idl_u,
                'subscribed_users': sub_u,
                'total_searches': tot_s,
                'new_users': new_u,
                'returning_users': ret_u,
                'movies_delivered': mov_d,
                'series_delivered': ser_d,
                'total_delivered': mov_d + ser_d
            }
            _STATS_CACHE[p] = (now_ts, res)
            return res
        except Exception as e:
            print(f"get_stats_for_period mongo error: {e}")

    try:
        conn = get_connection()
        c = conn.cursor()
        f_seen = TIMEFRAME_USER_FIRST_SEEN.get(p, '1=1')
        l_seen = TIMEFRAME_USER_LAST_SEEN.get(p, '1=1')
        t_sql = TIMEFRAME_SQL.get(p, '1=1')

        if p == 'all':
            c.execute("SELECT COUNT(*) FROM bot_users")
        else:
            c.execute(f"SELECT COUNT(*) FROM bot_users WHERE {l_seen}")
        total_users = c.fetchone()[0]

        if p == 'all':
            c.execute("SELECT COUNT(*) FROM bot_users WHERE is_subscribed = 0 AND has_interacted = 0")
        else:
            c.execute(f"SELECT COUNT(*) FROM bot_users WHERE is_subscribed = 0 AND has_interacted = 0 AND {f_seen}")
        idle_users = c.fetchone()[0]

        if p == 'all':
            c.execute("SELECT COUNT(*) FROM bot_users WHERE is_subscribed = 1")
        else:
            c.execute(f"SELECT COUNT(*) FROM bot_users WHERE is_subscribed = 1 AND {l_seen}")
        subscribed_users = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM search_logs WHERE {t_sql}")
        total_searches = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM bot_users WHERE {f_seen}")
        new_users = c.fetchone()[0]

        if p == 'all':
            returning_users = 0
        else:
            c.execute(f"SELECT COUNT(*) FROM bot_users WHERE NOT ({f_seen}) AND ({l_seen})")
            returning_users = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM delivery_logs WHERE media_type = 'movie' AND {t_sql}")
        movies_delivered = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM delivery_logs WHERE media_type = 'series' AND {t_sql}")
        series_delivered = c.fetchone()[0]

        conn.close()
        res = {
            'total_users': total_users,
            'idle_users': idle_users,
            'subscribed_users': subscribed_users,
            'total_searches': total_searches,
            'new_users': new_users,
            'returning_users': returning_users,
            'movies_delivered': movies_delivered,
            'series_delivered': series_delivered,
            'total_delivered': movies_delivered + series_delivered
        }
        _STATS_CACHE[p] = (now_ts, res)
        return res
    except Exception as e:
        print(f"get_stats_for_period sqlite fallback error: {e}")
        return {
            'total_users': 0, 'idle_users': 0, 'subscribed_users': 0,
            'total_searches': 0, 'new_users': 0, 'returning_users': 0,
            'movies_delivered': 0, 'series_delivered': 0, 'total_delivered': 0
        }

def get_multi_period_stats():
    return {p: get_stats_for_period(p) for p in ['today', 'week', 'month', 'year', 'all']}

def format_period_report(p: str, data: dict) -> str:
    name = PERIOD_NAMES.get(p, p)
    return (
        f"📊 **إحصائيات البوت — {name}**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👥 **المستخدمين والحركة:**\n"
        f"• 👤 إجمالي المستخدمين المتفاعلين: **{data['total_users']:,}**\n"
        f"• 🆕 مستخدمين جدد أول مرة: **{data['new_users']:,}**\n"
        f"• 🔄 مستخدمين قدامى عادوا للبوت: **{data['returning_users']:,}**\n"
        f"• 💤 دخلوا ستارت ولم يتفاعلوا أو يشتركوا: **{data['idle_users']:,}**\n"
        f"• ✅ المشتركون في قنوات البوت: **{data['subscribed_users']:,}**\n\n"
        f"🔍 **البحث والاستعلام:**\n"
        f"• 🔎 عمليات البحث المنفذة: **{data['total_searches']:,}** عملية\n\n"
        f"🚀 **الأعمال والتسليم:**\n"
        f"• 🎬 أفلام تم إرسالها: **{data['movies_delivered']:,}** فيلم\n"
        f"• 📺 حلقات تم إرسالها: **{data['series_delivered']:,}** حلقة\n"
        f"• 📦 إجمالي الأعمال المرسلة: **{data['total_delivered']:,}** ملف\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )

def get_top_50_movies():
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            pipeline = [
                {'$match': {'is_series': 0, 'matched_title': {'$ne': None}}},
                {'$group': {'_id': '$matched_title', 'req_count': {'$sum': 1}}},
                {'$sort': {'req_count': -1}},
                {'$limit': 50}
            ]
            res = list(mdb['search_logs'].aggregate(pipeline))
            rows = [{'title': r['_id'], 'req_count': r['req_count']} for r in res if r.get('_id')]
            if len(rows) < 50:
                existing = {r['title'] for r in rows}
                col = mdb['media_items']
                for m in col.find({'is_series': 0}, {'clean_title': 1}).sort('id', -1).limit(100):
                    t = m.get('clean_title')
                    if t and t not in existing and len(rows) < 50:
                        rows.append({'title': t, 'req_count': 1})
                        existing.add(t)
            return rows[:50]
        except Exception as e:
            print(f"get_top_50_movies mongo error: {e}")

    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
        SELECT title, COUNT(*) as req_count
        FROM (
            SELECT title FROM delivery_logs WHERE media_type = 'movie'
            UNION ALL
            SELECT matched_title as title FROM search_logs WHERE is_series = 0 AND matched_title IS NOT NULL
        )
        WHERE title IS NOT NULL AND title != ''
        GROUP BY title
        ORDER BY req_count DESC
        LIMIT 50
        """)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows[:50]
    except Exception as e:
        print(f"get_top_50_movies fallback error: {e}")
        return []

def get_top_50_series():
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            pipeline = [
                {'$match': {'is_series': 1, 'matched_title': {'$ne': None}}},
                {'$group': {'_id': '$matched_title', 'req_count': {'$sum': 1}}},
                {'$sort': {'req_count': -1}},
                {'$limit': 50}
            ]
            res = list(mdb['search_logs'].aggregate(pipeline))
            rows = [{'title': r['_id'], 'req_count': r['req_count']} for r in res if r.get('_id')]
            if len(rows) < 50:
                existing = {r['title'] for r in rows}
                col = mdb['media_items']
                for t in col.distinct('series_title', {'is_series': 1}):
                    if t and t not in existing and len(rows) < 50:
                        rows.append({'title': t, 'req_count': 1})
                        existing.add(t)
            return rows[:50]
        except Exception as e:
            print(f"get_top_50_series mongo error: {e}")

    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
        SELECT title, COUNT(*) as req_count
        FROM (
            SELECT title FROM delivery_logs WHERE media_type = 'series'
            UNION ALL
            SELECT matched_title as title FROM search_logs WHERE is_series = 1 AND matched_title IS NOT NULL
        )
        WHERE title IS NOT NULL AND title != ''
        GROUP BY title
        ORDER BY req_count DESC
        LIMIT 50
        """)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows[:50]
    except Exception as e:
        print(f"get_top_50_series fallback error: {e}")
        return []
