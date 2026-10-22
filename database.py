import sqlite3
import os
import re
from datetime import datetime

DEFAULT_MONGO_URI = "mongodb+srv://bosshoeheoejossnpe_db_user:eQl1SyEvwIRDMs1w@cluster0.etprryl.mongodb.net/?retryWrites=true&w=majority"
DB_PATH = os.path.join(os.path.dirname(__file__), "movies.db")

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
                _mongo_client = MongoClient(mongo_uri, tlsCAFile=ca_file, tlsAllowInvalidCertificates=True, serverSelectionTimeoutMS=7000)
            except Exception:
                _mongo_client = MongoClient(mongo_uri, tlsAllowInvalidCertificates=True, serverSelectionTimeoutMS=7000)
            _mongo_client.admin.command('ping')
        except Exception as e:
            print(f"MongoDB connection notice: {e}")
            _mongo_client = None
            raise e
    return _mongo_client['telegram_movie_bot']

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            media_col = mdb['media_items']
            media_col.create_index([('id', 1)], unique=True)
            media_col.create_index([('clean_title', 1)])
            media_col.create_index([('series_title', 1), ('season_num', 1), ('episode_num', 1)])
            media_col.create_index([('is_series', 1)])
            media_col.create_index([('is_transferred', 1)])
            print("MongoDB Atlas collections and indexes ready.")
            return
        except Exception as e:
            print(f"MongoDB init_db notice: {e}")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS media_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        is_series INTEGER DEFAULT 0,
        series_title TEXT,
        season_num INTEGER DEFAULT 1,
        episode_num INTEGER DEFAULT 0,
        title TEXT NOT NULL,
        clean_title TEXT NOT NULL,
        raw_caption TEXT,
        source_chat_id INTEGER NOT NULL,
        source_msg_id INTEGER NOT NULL,
        target_msg_id INTEGER,
        file_id TEXT,
        file_size INTEGER,
        duration INTEGER,
        quality TEXT,
        media_type TEXT,
        is_transferred INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source_chat_id, source_msg_id)
    )
    """)
    cursor.execute("PRAGMA table_info(media_items)")
    existing_cols = [r[1] for r in cursor.fetchall()]
    if 'is_series' not in existing_cols:
        cursor.execute("ALTER TABLE media_items ADD COLUMN is_series INTEGER DEFAULT 0;")
    if 'series_title' not in existing_cols:
        cursor.execute("ALTER TABLE media_items ADD COLUMN series_title TEXT;")
    if 'season_num' not in existing_cols:
        cursor.execute("ALTER TABLE media_items ADD COLUMN season_num INTEGER DEFAULT 1;")
    if 'episode_num' not in existing_cols:
        cursor.execute("ALTER TABLE media_items ADD COLUMN episode_num INTEGER DEFAULT 0;")
    if 'has_custom_cover' not in existing_cols:
        cursor.execute("ALTER TABLE media_items ADD COLUMN has_custom_cover INTEGER DEFAULT 0;")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_title ON media_items(clean_title);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_series ON media_items(series_title, season_num, episode_num);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_transferred ON media_items(is_transferred);")
    conn.commit()
    conn.close()

def parse_media_details(caption: str, file_name: str = None):
    clean_line = ""
    if caption:
        lines = [l.strip() for l in caption.splitlines() if l.strip()]
        if lines:
            first_line = lines[0]
            clean = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', first_line)
            clean = re.sub(r'@\w+', '', clean)
            clean = re.sub(r'https?://\S+', '', clean)
            clean = re.sub(r'[\U0001F1E6-\U0001F1FF]{2}', '', clean)
            clean_line = clean.strip(" -|:")

    if not clean_line and file_name:
        clean_line = os.path.splitext(file_name)[0]
        clean_line = re.sub(r'[\._]', ' ', clean_line)

    quality = "HD"
    text_to_check = f"{caption or ''} {file_name or ''}"
    if re.search(r'\b1080p?\b', text_to_check, re.I):
        quality = "1080p"
    elif re.search(r'\b720p?\b', text_to_check, re.I):
        quality = "720p"
    elif re.search(r'\b480p?\b', text_to_check, re.I):
        quality = "480p"
    elif re.search(r'\b4k|2160p?\b', text_to_check, re.I):
        quality = "4K"

    s_match = re.search(r'[sS](\d+)\s*[eE](\d+)', clean_line)
    if not s_match:
        s_match = re.search(r'[sS](\d+)\s*[eE](\d+)', text_to_check)

    if s_match:
        s_num = int(s_match.group(1))
        e_num = int(s_match.group(2))
        series_title = re.sub(r'[sS]\d+\s*[eE]\d+.*', '', clean_line, flags=re.I).strip(" -|:")
        return {
            'is_series': 1,
            'series_title': series_title or clean_line,
            'season_num': s_num,
            'episode_num': e_num,
            'clean_title': f"{series_title} | S{s_num:02d}E{e_num:02d}",
            'quality': quality
        }

    ep_match = re.search(r'(?:EP\.?|Episode|الحلقة|حلقة)\s*(\d+)', clean_line, re.I)
    if ep_match:
        e_num = int(ep_match.group(1))
        season_match = re.search(r'(?:S|Season|الموسم)\s*(\d+)', clean_line, re.I)
        s_num = int(season_match.group(1)) if season_match else 1
        
        series_title = re.sub(r'(?:\||\-)?\s*(?:S|Season|الموسم)\s*\d+', '', clean_line, flags=re.I)
        series_title = re.sub(r'(?:\||\-)?\s*(?:EP\.?|Episode|الحلقة|حلقة)\s*\d+', '', series_title, flags=re.I)
        series_title = series_title.strip(" -|:")

        return {
            'is_series': 1,
            'series_title': series_title,
            'season_num': s_num,
            'episode_num': e_num,
            'clean_title': f"{series_title} | الموسم {s_num} - الحلقة {e_num}",
            'quality': quality
        }

    movie_title = clean_line
    movie_title = re.sub(r'\b(1080p|720p|480p|2160p|4k|bluray|web-dl|webrip|hdrip|x264|x265|hevc|aac)\b', '', movie_title, flags=re.I).strip(" -|:")
    
    return {
        'is_series': 0,
        'series_title': None,
        'season_num': 1,
        'episode_num': 0,
        'clean_title': movie_title or "بدون عنوان",
        'quality': quality
    }

def add_media_item(parsed_data, raw_caption, source_chat_id, source_msg_id, 
                   file_size=0, duration=0, media_type="video", target_msg_id=None, is_transferred=0):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO media_items (
        is_series, series_title, season_num, episode_num,
        title, clean_title, raw_caption, source_chat_id, source_msg_id,
        target_msg_id, file_size, duration, quality, media_type, is_transferred
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(source_chat_id, source_msg_id) DO UPDATE SET
        is_series=excluded.is_series,
        series_title=excluded.series_title,
        season_num=excluded.season_num,
        episode_num=excluded.episode_num,
        title=excluded.title,
        clean_title=excluded.clean_title,
        raw_caption=excluded.raw_caption,
        file_size=excluded.file_size,
        duration=excluded.duration,
        quality=excluded.quality
    """, (
        parsed_data['is_series'],
        parsed_data['series_title'],
        parsed_data['season_num'],
        parsed_data['episode_num'],
        parsed_data['clean_title'],
        parsed_data['clean_title'],
        raw_caption,
        source_chat_id,
        source_msg_id,
        target_msg_id,
        file_size,
        duration,
        parsed_data['quality'],
        media_type,
        is_transferred
    ))
    conn.commit()
    item_id = cursor.lastrowid
    conn.close()

    # Also update MongoDB if connected
    mdb = get_mongo_db()
    if mdb is not None:
        try:
            doc = {
                'id': item_id,
                'is_series': parsed_data['is_series'],
                'series_title': parsed_data['series_title'],
                'season_num': parsed_data['season_num'],
                'episode_num': parsed_data['episode_num'],
                'title': parsed_data['clean_title'],
                'clean_title': parsed_data['clean_title'],
                'raw_caption': raw_caption,
                'source_chat_id': source_chat_id,
                'source_msg_id': source_msg_id,
                'target_msg_id': target_msg_id,
                'file_size': file_size,
                'duration': duration,
                'quality': parsed_data['quality'],
                'media_type': media_type,
                'is_transferred': is_transferred
            }
            mdb['media_items'].replace_one(
                {'source_chat_id': source_chat_id, 'source_msg_id': source_msg_id},
                doc,
                upsert=True
            )
        except Exception:
            pass

    return item_id

ARABIC_MAPPINGS = {
    'بريكنج باد': 'breaking bad',
    'بريكينج باد': 'breaking bad',
    'صراع العروش': 'game of thrones',
    'قيم اوف ثرونز': 'game of thrones',
    'جيم اوف ثرونز': 'game of thrones',
    'بيكي بلايندرز': 'peaky blinders',
    'بيكي بلاندرز': 'peaky blinders',
    'باتمان': 'batman',
    'سبايدرمان': 'spider',
    'سبايدر مان': 'spider',
    'سوبرمان': 'superman',
    'سوبر مان': 'superman',
    'تيتانيك': 'titanic',
    'انسبشن': 'inception',
    'إنسيبشن': 'inception',
    'انترستيلر': 'interstellar',
    'إنترستيلار': 'interstellar',
    'بين النجوم': 'interstellar',
    'فريندز': 'friends',
    'فريندس': 'friends',
    'شيرلوك': 'sherlock',
    'شارلوك': 'sherlock',
    'سكويد جيم': 'squid game',
    'لعبة الحبار': 'squid game',
    'لا كاسا دي بابيل': 'la casa de papel',
    'لا كاسا': 'la casa de papel',
    'البروفيسور': 'la casa de papel',
    'لوكي': 'loki',
    'دارك': 'dark',
    'هانيبال': 'hannibal',
    'ديكستر': 'dexter',
    'مستر روبوت': 'mr robot',
    'اوزارك': 'ozark',
    'ذا ويتشر': 'the witcher',
    'ويتشر': 'the witcher',
    'ذا بويز': 'the boys',
    'بويز': 'the boys',
    'ذا اوفيس': 'the office',
    'اوفيس': 'the office',
    'شوجون': 'shogun',
    'فول اوت': 'fallout',
    'ريتشر': 'reacher',
    'ناركوس': 'narcos',
    'سوات': 's.w.a.t',
    'الموتى السائرون': 'the walking dead',
    'فايكنج': 'vikings',
    'فايكنجز': 'vikings',
    'جلاديتور': 'gladiator',
    'المصارع': 'gladiator',
    'سترينجر ثينقز': 'stranger things',
    'سترينجر ثينقس': 'stranger things',
    'اشياء غريبة': 'stranger things',
    'أشياء غريبة': 'stranger things',
    'افاتار': 'avatar',
    'أفاتار': 'avatar',
    'ونزداي': 'wednesday',
    'وينزداي': 'wednesday',
    'وينزدي': 'wednesday',
    'بريزون بريك': 'prison break',
    'فاست اند فيورس': 'fast',
    'ماد ماكس': 'mad max',
    'جون ويك': 'john wick',
    'امريكان كرايم ستوري': 'american crime story',
    'امريكان هورور ستوري': 'american horror story',
    'هاوس اوف دراجون': 'house of the dragon',
    'ال تشابو': 'el chapo',
    'ذا لاست اوف اس': 'the last of us',
    'لاست اوف اس': 'the last of us',
    'افينجرز': 'avengers',
    'المنتقمون': 'avengers',
    'ايرون مان': 'iron man',
    'الرجل الحديدي': 'iron man',
    'كابتن امريكا': 'captain america',
    'ديدبول': 'deadpool',
    'جوكر': 'joker',
    'الجوكر': 'joker',
    'هاري بوتر': 'harry potter',
    'سيد الخواتم': 'lord of the rings',
    'ماتريكس': 'matrix',
    'الماتريكس': 'matrix',
    'ترمينيتور': 'terminator',
    'المبيد': 'terminator'
}

def normalize_arabic(text: str) -> str:
    text = re.sub(r'[إأآا]', 'ا', text)
    text = re.sub(r'ة', 'ه', text)
    text = re.sub(r'ى', 'ي', text)
    text = re.sub(r'[\u064B-\u065F\u0670]', '', text)
    return text.strip().lower()

def clean_query_terms(raw_query: str):
    # 0. Multiline pasted message handling: take first line
    lines = [l.strip() for l in raw_query.splitlines() if l.strip()]
    if lines:
        raw_query = lines[0]

    # 1. Strip emojis, symbols, and pictographs
    q = re.sub(r'[\u2600-\u27bf\u2300-\u23ff\U0001f300-\U0001faff\U00010000-\U0010ffff]', ' ', raw_query)
    # 2. Strip markdown symbols, punctuation & brackets
    q = re.sub(r'[*_~`#\[\]\(\)\|:!?,.\"/\\-]+', ' ', q)
    # 3. Strip mentions
    q = re.sub(r'@\w+', ' ', q)
    # 4. Strip leading prefixes (فيلم, مسلسل, etc.)
    q = re.sub(r'^(فيلم|فلم|مسلسل|سلسلة|انمي|أنمي|movie|series)\s+', '', q.strip(), flags=re.I)
    # 5. Strip quality/resolution words
    q = re.sub(r'\b(1080p|720p|480p|4k|2160p|hd|fhd|bluray|web-dl|webrip|x264|x265)\b', ' ', q, flags=re.I)
    # 6. Strip year tags
    q = re.sub(r'\b(19\d\d|20\d\d)\b', ' ', q)
    q = ' '.join(q.split()).strip()

    q_norm = normalize_arabic(q)
    terms = [q] if q else []

    # Check Arabic mappings
    for ar_k, en_v in ARABIC_MAPPINGS.items():
        if ar_k in q_norm or ar_k in raw_query.lower():
            if en_v not in terms:
                terms.append(en_v)
            break

    if not terms:
        terms = [raw_query.strip()]

    return terms

def search_media(query: str, limit: int = 15):
    terms = clean_query_terms(query)
    series_rows = []
    movie_rows = []
    seen_series = set()
    seen_movies = set()

    mdb = get_mongo_db()
    if mdb is not None:
        col = mdb['media_items']
        for term in terms:
            if not term:
                continue
            words = [re.escape(w) for w in term.split() if len(w) >= 2]

            # 1. Exact / Phrase match
            exact_reg = re.compile(re.escape(term), re.IGNORECASE)
            
            # Search series
            for st in col.distinct('series_title', {'is_series': 1, 'series_title': exact_reg}):
                if st and st not in seen_series:
                    first_doc = col.find_one({'is_series': 1, 'series_title': st})
                    seasons = len(col.distinct('season_num', {'is_series': 1, 'series_title': st}))
                    episodes = col.count_documents({'is_series': 1, 'series_title': st})
                    series_rows.append({
                        'is_series': 1,
                        'series_title': st,
                        'seasons_count': seasons,
                        'episodes_count': episodes,
                        'first_id': first_doc['id'] if first_doc else 0
                    })
                    seen_series.add(st)

            # Search movies (valid target_msg_id <= 3050)
            m_docs = list(col.find(
                {'is_series': 0, 'clean_title': exact_reg, 'target_msg_id': {'$lte': 3050}},
                {'id': 1, 'clean_title': 1, 'quality': 1, 'file_size': 1, 'duration': 1, 'target_msg_id': 1}
            ).sort('id', -1).limit(limit))
            for m in m_docs:
                if m['id'] not in seen_movies:
                    movie_rows.append(m)
                    seen_movies.add(m['id'])

            # 2. Multi-word AND search (all words must appear in title in any order)
            if len(words) > 1 and (len(series_rows) < limit or len(movie_rows) < limit):
                and_pattern = ''.join(f'(?=.*{w})' for w in words)
                and_reg = re.compile(and_pattern, re.IGNORECASE)

                for st in col.distinct('series_title', {'is_series': 1, 'series_title': and_reg}):
                    if st and st not in seen_series and len(series_rows) < limit:
                        first_doc = col.find_one({'is_series': 1, 'series_title': st})
                        seasons = len(col.distinct('season_num', {'is_series': 1, 'series_title': st}))
                        episodes = col.count_documents({'is_series': 1, 'series_title': st})
                        series_rows.append({
                            'is_series': 1,
                            'series_title': st,
                            'seasons_count': seasons,
                            'episodes_count': episodes,
                            'first_id': first_doc['id'] if first_doc else 0
                        })
                        seen_series.add(st)

                m_docs_and = list(col.find(
                    {'is_series': 0, 'clean_title': and_reg, 'target_msg_id': {'$lte': 3050}},
                    {'id': 1, 'clean_title': 1, 'quality': 1, 'file_size': 1, 'duration': 1, 'target_msg_id': 1}
                ).sort('id', -1).limit(limit))
                for m in m_docs_and:
                    if m['id'] not in seen_movies and len(movie_rows) < limit:
                        movie_rows.append(m)
                        seen_movies.add(m['id'])

            # 3. Individual words fallback (if AND returned no results, test prominent words)
            if not series_rows and not movie_rows and len(words) > 1:
                for w in words:
                    if len(w) >= 4:
                        single_reg = re.compile(w, re.IGNORECASE)
                        for st in col.distinct('series_title', {'is_series': 1, 'series_title': single_reg}):
                            if st and st not in seen_series and len(series_rows) < limit:
                                first_doc = col.find_one({'is_series': 1, 'series_title': st})
                                seasons = len(col.distinct('season_num', {'is_series': 1, 'series_title': st}))
                                episodes = col.count_documents({'is_series': 1, 'series_title': st})
                                series_rows.append({
                                    'is_series': 1,
                                    'series_title': st,
                                    'seasons_count': seasons,
                                    'episodes_count': episodes,
                                    'first_id': first_doc['id'] if first_doc else 0
                                })
                                seen_series.add(st)
                        m_docs_single = list(col.find(
                            {'is_series': 0, 'clean_title': single_reg, 'target_msg_id': {'$lte': 3050}},
                            {'id': 1, 'clean_title': 1, 'quality': 1, 'file_size': 1, 'duration': 1, 'target_msg_id': 1}
                        ).sort('id', -1).limit(limit))
                        for m in m_docs_single:
                            if m['id'] not in seen_movies and len(movie_rows) < limit:
                                movie_rows.append(m)
                                seen_movies.add(m['id'])
                        if series_rows or movie_rows:
                            break

            # 4. Prefix Substring fallback (for partial words e.g. "avat" -> "avatar")
            if not series_rows and not movie_rows and len(words) == 1 and len(term) >= 3:
                sub_pattern = re.escape(term[:max(3, len(term) - 1)])
                sub_reg = re.compile(sub_pattern, re.IGNORECASE)

                for st in col.distinct('series_title', {'is_series': 1, 'series_title': sub_reg}):
                    if st and st not in seen_series and len(series_rows) < limit:
                        first_doc = col.find_one({'is_series': 1, 'series_title': st})
                        seasons = len(col.distinct('season_num', {'is_series': 1, 'series_title': st}))
                        episodes = col.count_documents({'is_series': 1, 'series_title': st})
                        series_rows.append({
                            'is_series': 1,
                            'series_title': st,
                            'seasons_count': seasons,
                            'episodes_count': episodes,
                            'first_id': first_doc['id'] if first_doc else 0
                        })
                        seen_series.add(st)

                m_docs_sub = list(col.find(
                    {'is_series': 0, 'clean_title': sub_reg, 'target_msg_id': {'$lte': 3050}},
                    {'id': 1, 'clean_title': 1, 'quality': 1, 'file_size': 1, 'duration': 1, 'target_msg_id': 1}
                ).sort('id', -1).limit(limit))
                for m in m_docs_sub:
                    if m['id'] not in seen_movies and len(movie_rows) < limit:
                        movie_rows.append(m)
                        seen_movies.add(m['id'])

            if series_rows or movie_rows:
                break

        return {"series": series_rows[:limit], "movies": movie_rows[:limit]}

    # SQLite Fallback
    conn = get_connection()
    cursor = conn.cursor()
    for term in terms:
        if not term:
            continue
        search_pattern = f"%{term}%"
        words = [w for w in term.split() if len(w) >= 2]

        cursor.execute("""
        SELECT is_series, series_title, COUNT(DISTINCT season_num) as seasons_count, COUNT(*) as episodes_count, MIN(id) as first_id
        FROM media_items
        WHERE is_series = 1 AND series_title LIKE ?
        GROUP BY series_title
        ORDER BY episodes_count DESC LIMIT ?
        """, (search_pattern, limit))
        for r in cursor.fetchall():
            s_dict = dict(r)
            if s_dict['series_title'] not in seen_series:
                series_rows.append(s_dict)
                seen_series.add(s_dict['series_title'])

        cursor.execute("""
        SELECT id, clean_title, quality, file_size, duration, target_msg_id
        FROM media_items
        WHERE is_series = 0 AND target_msg_id <= 3050 AND clean_title LIKE ?
        ORDER BY id DESC LIMIT ?
        """, (search_pattern, limit))
        for r in cursor.fetchall():
            m_dict = dict(r)
            if m_dict['id'] not in seen_movies:
                movie_rows.append(m_dict)
                seen_movies.add(m_dict['id'])

        # Multi-word AND search for SQLite
        if len(words) > 1 and (len(series_rows) < limit or len(movie_rows) < limit):
            where_series = " AND ".join(["series_title LIKE ?" for _ in words])
            params_series = [f"%{w}%" for w in words] + [limit]
            cursor.execute(f"""
            SELECT is_series, series_title, COUNT(DISTINCT season_num) as seasons_count, COUNT(*) as episodes_count, MIN(id) as first_id
            FROM media_items
            WHERE is_series = 1 AND {where_series}
            GROUP BY series_title
            ORDER BY episodes_count DESC LIMIT ?
            """, params_series)
            for r in cursor.fetchall():
                s_dict = dict(r)
                if s_dict['series_title'] not in seen_series:
                    series_rows.append(s_dict)
                    seen_series.add(s_dict['series_title'])

            where_movies = " AND ".join(["clean_title LIKE ?" for _ in words])
            params_movies = [f"%{w}%" for w in words] + [limit]
            cursor.execute(f"""
            SELECT id, clean_title, quality, file_size, duration, target_msg_id
            FROM media_items
            WHERE is_series = 0 AND target_msg_id <= 3050 AND {where_movies}
            ORDER BY id DESC LIMIT ?
            """, params_movies)
            for r in cursor.fetchall():
                m_dict = dict(r)
                if m_dict['id'] not in seen_movies and len(movie_rows) < limit:
                    movie_rows.append(m_dict)
                    seen_movies.add(m_dict['id'])

        if series_rows or movie_rows:
            break

    conn.close()
    return {"series": series_rows[:limit], "movies": movie_rows[:limit]}

def get_media_item_by_id(item_id: int):
    mdb = get_mongo_db()
    if mdb is not None:
        doc = mdb['media_items'].find_one({'id': int(item_id)})
        return doc

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM media_items WHERE id = ?", (item_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_series_seasons(series_title: str):
    mdb = get_mongo_db()
    if mdb is not None:
        return sorted(mdb['media_items'].distinct('season_num', {'is_series': 1, 'series_title': series_title}))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT DISTINCT season_num FROM media_items
    WHERE is_series = 1 AND series_title = ?
    ORDER BY season_num ASC
    """, (series_title,))
    seasons = [r['season_num'] for r in cursor.fetchall()]
    conn.close()
    return seasons

def get_season_episodes(series_title: str, season_num: int):
    mdb = get_mongo_db()
    if mdb is not None:
        docs = list(mdb['media_items'].find(
            {'is_series': 1, 'series_title': series_title, 'season_num': season_num}
        ).sort('episode_num', 1))
        return docs

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT MIN(id) as id, episode_num, quality, MAX(file_size) as file_size, duration, target_msg_id, is_transferred
    FROM media_items
    WHERE is_series = 1 AND series_title = ? AND season_num = ?
    GROUP BY episode_num
    ORDER BY episode_num ASC
    """, (series_title, season_num))
    episodes = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return episodes

def mark_transferred(source_chat_id: int, source_msg_id: int, target_msg_id: int, file_id: str = None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE media_items 
    SET is_transferred = 1, target_msg_id = ?, file_id = ?
    WHERE source_chat_id = ? AND source_msg_id = ?
    """, (target_msg_id, file_id, source_chat_id, source_msg_id))
    conn.commit()
    conn.close()

    mdb = get_mongo_db()
    if mdb is not None:
        try:
            mdb['media_items'].update_one(
                {'source_chat_id': source_chat_id, 'source_msg_id': source_msg_id},
                {'$set': {'is_transferred': 1, 'target_msg_id': target_msg_id, 'file_id': file_id}}
            )
        except Exception:
            pass

def get_next_episode(series_title: str, season_num: int, current_ep: int):
    mdb = get_mongo_db()
    if mdb is not None:
        doc = mdb['media_items'].find_one(
            {'is_series': 1, 'series_title': series_title, 'season_num': season_num, 'episode_num': {'$gt': current_ep}},
            sort=[('episode_num', 1)]
        )
        return doc

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, episode_num, quality, file_size
    FROM media_items
    WHERE is_series = 1 AND series_title = ? AND season_num = ? AND episode_num > ?
    ORDER BY episode_num ASC LIMIT 1
    """, (series_title, season_num, current_ep))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_stats():
    mdb = get_mongo_db()
    if mdb is not None:
        col = mdb['media_items']
        return {
            "total": col.count_documents({}), 
            "total_series": len(col.distinct('series_title', {'is_series': 1})), 
            "total_movies": col.count_documents({'is_series': 0}), 
            "transferred": col.count_documents({'is_transferred': 1})
        }

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM media_items")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT series_title) FROM media_items WHERE is_series = 1")
    total_series = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM media_items WHERE is_series = 0")
    total_movies = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM media_items WHERE is_transferred = 1")
    transferred = cursor.fetchone()[0]
    conn.close()
    return {
        "total": total, 
        "total_series": total_series, 
        "total_movies": total_movies, 
        "transferred": transferred
    }

if __name__ == "__main__":
    init_db()
    print("Database schema initialized!")
    print(get_stats())
