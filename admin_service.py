import sqlite3
import os
import re
from datetime import datetime

DEFAULT_MONGO_URI = "mongodb+srv://bosshoeheoejossnpe_db_user:eQl1SyEvwIRDMs1w@cluster0.etprryl.mongodb.net/?retryWrites=true&w=majority"
DB_PATH = os.path.join(os.path.dirname(__file__), "movies.db")
ADMIN_ID = 8625825633
ADMIN_IDS = {8625825633, 6641619062}

_mongo_client = None

def get_mongo_db():
    global _mongo_client
    mongo_uri = os.environ.get("MONGO_URI", "").strip() or DEFAULT_MONGO_URI
    if not mongo_uri:
        return None
    if _mongo_client is None:
        try:
            from pymongo import MongoClient
            try:
                import certifi
                ca_file = certifi.where()
                _mongo_client = MongoClient(mongo_uri, tlsCAFile=ca_file, serverSelectionTimeoutMS=7000)
            except Exception:
                _mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=7000)
            _mongo_client.admin.command('ping')
        except Exception as e:
            print(f"Admin service Mongo warning: {e}")
            _mongo_client = None
            return None
    return _mongo_client['telegram_movie_bot']

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

# 1. USER TRACKING
def record_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
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
            print(f"record_user mongo error: {e}")

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

def mark_user_subscribed(user_id: int):
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            mdb['bot_users'].update_one({'user_id': user_id}, {'$set': {'is_subscribed': 1, 'last_seen': now_str}})
            return
        except Exception:
            pass

    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE bot_users SET is_subscribed = 1, last_seen = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def is_user_cached_subscribed(user_id: int) -> bool:
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            u = mdb['bot_users'].find_one({'user_id': user_id})
            return bool(u and u.get('is_subscribed') == 1)
        except Exception:
            pass

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT is_subscribed FROM bot_users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return bool(row and row['is_subscribed'] == 1)

def reset_all_users_subscription():
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

def get_multi_period_stats():
    conn = get_connection()
    c = conn.cursor()
    
    stats = {}
    periods = ['today', 'week', 'month', 'year', 'all']
    
    for p in periods:
        f_seen = TIMEFRAME_USER_FIRST_SEEN[p]
        l_seen = TIMEFRAME_USER_LAST_SEEN[p]
        t_sql = TIMEFRAME_SQL[p]
        
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

        stats[p] = {
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

    conn.close()
    return stats

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
            col = mdb['media_items']
            movies = list(col.find({'is_series': 0}, {'clean_title': 1}).sort('id', -1).limit(50))
            return [{'title': m['clean_title'], 'req_count': 1} for m in movies]
        except Exception:
            pass

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
    
    if len(rows) < 50:
        existing_titles = {r['title'] for r in rows}
        c.execute("""
        SELECT DISTINCT clean_title as title
        FROM media_items
        WHERE is_series = 0
        ORDER BY id DESC
        LIMIT 100
        """)
        for r in c.fetchall():
            t = r['title']
            if t not in existing_titles and len(rows) < 50:
                rows.append({'title': t, 'req_count': 1})
                existing_titles.add(t)

    conn.close()
    return rows[:50]

def get_top_50_series():
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            col = mdb['media_items']
            titles = col.distinct('series_title', {'is_series': 1})
            res = []
            for t in titles[:50]:
                cnt = col.count_documents({'is_series': 1, 'series_title': t})
                res.append({'title': t, 'req_count': cnt})
            return sorted(res, key=lambda x: x['req_count'], reverse=True)
        except Exception:
            pass

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

    if len(rows) < 50:
        existing_titles = {r['title'] for r in rows}
        c.execute("""
        SELECT series_title as title, COUNT(*) as ep_cnt
        FROM media_items
        WHERE is_series = 1
        GROUP BY series_title
        ORDER BY ep_cnt DESC
        LIMIT 100
        """)
        for r in c.fetchall():
            t = r['title']
            if t not in existing_titles and len(rows) < 50:
                rows.append({'title': t, 'req_count': r['ep_cnt']})
                existing_titles.add(t)

    conn.close()
    return rows[:50]
