import sqlite3
import os
import re
import difflib
import threading
import time
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
    if not text:
        return ""
    text = re.sub(r'[إأآا]', 'ا', text)
    text = re.sub(r'ة', 'ه', text)
    text = re.sub(r'ى', 'ي', text)
    text = re.sub(r'[\u064B-\u065F\u0670]', '', text)
    return text.strip().lower()

def strip_ar_prefix(w: str) -> str:
    if w.startswith("ال") and len(w) > 3:
        return w[2:]
    return w

def clean_text(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r'[\u2600-\u27bf\u2300-\u23ff\U0001f300-\U0001faff\U00010000-\U0010ffff]', ' ', text)
    t = re.sub(r'[*_~`#\[\]\(\)\|:!?,.\"/\\-]+', ' ', t)
    t = re.sub(r'@\w+', ' ', t)
    t = re.sub(r'^(فيلم|فلم|مسلسل|سلسلة|انمي|أنمي|movie|series)\s+', '', t.strip(), flags=re.I)
    t = re.sub(r'\b(1080p|720p|480p|4k|2160p|hd|fhd|bluray|web-dl|webrip|x264|x265)\b', ' ', t, flags=re.I)
    t = re.sub(r'\b(19\d\d|20\d\d)\b', ' ', t)
    return ' '.join(t.split()).strip().lower()

def normalize_ar_key(text: str) -> str:
    norm = normalize_arabic(clean_text(text))
    words = [strip_ar_prefix(w) for w in norm.split() if len(w) >= 2]
    return ' '.join(words)

CORE_MAPPINGS = {normalize_ar_key(k): v.lower() for k, v in ARABIC_MAPPINGS.items()}

def map_arabic_query(q: str) -> list:
    q_norm = normalize_ar_key(q)
    if not q_norm:
        return []
    mapped = []
    if q_norm in CORE_MAPPINGS:
        mapped.append(CORE_MAPPINGS[q_norm])
    for k, v in CORE_MAPPINGS.items():
        if k in q_norm or q_norm in k:
            if v not in mapped:
                mapped.append(v)
    if not mapped:
        for k, v in CORE_MAPPINGS.items():
            if difflib.SequenceMatcher(None, q_norm, k).ratio() >= 0.78:
                if v not in mapped:
                    mapped.append(v)
                break
    return mapped

def phonetic_skeleton(w: str) -> str:
    w = re.sub(r'(ea|ee|ei|ie|ey|y)', 'i', w)
    w = re.sub(r'oo|ou', 'u', w)
    w = re.sub(r'ph', 'f', w)
    w = re.sub(r'ck', 'k', w)
    return re.sub(r'(.)\1+', r'\1', w)

def word_similarity(w1: str, w2: str) -> float:
    if w1 == w2:
        return 1.0
    l1, l2 = len(w1), len(w2)
    diff = abs(l1 - l2)
    if diff > 3:
        if min(l1, l2) >= 4 and (w1.startswith(w2) or w2.startswith(w1)):
            return min(l1, l2) / max(l1, l2)
        return 0.0

    # Fast character overlap guard
    common = sum(min(w1.count(c), w2.count(c)) for c in set(w1))
    if common < max(l1, l2) - 2:
        return 0.0

    # Phonetic check
    sk1 = phonetic_skeleton(w1)
    sk2 = phonetic_skeleton(w2)
    if sk1 == sk2:
        return 0.92

    # Fast Levenshtein distance
    prev = list(range(l2 + 1))
    for i, c1 in enumerate(w1):
        curr = [i + 1] * (l2 + 1)
        for j, c2 in enumerate(w2):
            cost = 0 if c1 == c2 else 1
            curr[j + 1] = min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost)
        prev = curr
    dist = prev[l2]
    max_len = max(l1, l2)
    lev_ratio = 1.0 - (dist / max_len)

    seq_ratio = difflib.SequenceMatcher(None, w1, w2).ratio()
    sk_ratio = difflib.SequenceMatcher(None, sk1, sk2).ratio()
    return max(lev_ratio, seq_ratio, sk_ratio * 0.90)

def score_candidate(q_norm: str, q_words: list, item: dict) -> float:
    t_norm = item['norm']
    t_words = item['words']
    t_words_core = item['words_core']

    if not t_norm or not q_norm:
        return 0.0

    # 1. Exact match
    if q_norm == t_norm:
        return 100.0

    # 2. Phrase contains
    if q_norm in t_norm:
        return 92.0 + min(6.0, (len(q_norm) / len(t_norm)) * 6.0)

    # 3. Token match
    matched_count = 0
    sim_scores = []
    has_exact_long_word = False
    for qw in q_words:
        qw_core = strip_ar_prefix(qw)
        best_sim = 0.0
        for tw, tw_core in zip(t_words, t_words_core):
            if qw == tw or qw_core == tw_core:
                best_sim = 1.0
                if len(qw) >= 5:
                    has_exact_long_word = True
                break
            s = word_similarity(qw, tw)
            s_core = word_similarity(qw_core, tw_core)
            m_s = max(s, s_core)
            if m_s > best_sim:
                best_sim = m_s

        threshold = 0.60 if has_exact_long_word else 0.70
        if best_sim >= threshold:
            matched_count += 1
            sim_scores.append(best_sim)

    if matched_count == len(q_words):
        avg_sim = sum(sim_scores) / len(sim_scores)
        return 78.0 + (avg_sim * 16.0)

    # 4. Long keyword match
    if has_exact_long_word and len(q_words) >= 2 and matched_count >= 1:
        avg_sim = sum(sim_scores) / len(sim_scores)
        return 72.0 + (avg_sim * 12.0)

    # 5. Multi-word partial query match (3+ words)
    if len(q_words) >= 3 and matched_count >= len(q_words) - 1:
        avg_sim = sum(sim_scores) / len(sim_scores)
        return 68.0 + (avg_sim * 12.0)

    # 6. Global single word fallback
    if len(q_words) == 1 and len(q_norm) >= 4:
        sim = difflib.SequenceMatcher(None, q_norm, t_norm).ratio()
        if sim >= 0.72:
            return sim * 85.0

    return 0.0

def extract_movie_part(title: str) -> int:
    t = (title or "").lower()
    m_ar = re.search(r'الجزء\s*(الاول|الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر|\d+)', t)
    if m_ar:
        ar_map = {
            'الاول': 1, 'الأول': 1, 'الثاني': 2, 'الثالث': 3, 'الرابع': 4, 'الخامس': 5,
            'السادس': 6, 'السابع': 7, 'الثامن': 8, 'التاسع': 9, 'العاشر': 10
        }
        val = m_ar.group(1)
        return ar_map.get(val, int(val) if val.isdigit() else 1)

    m_en = re.search(r'\b(?:part|chapter|vol|volume)\.?\s*([0-9]+|[ivx]+)\b', t, re.I)
    if m_en:
        val = m_en.group(1).lower()
        roman = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5, 'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10}
        return roman.get(val, int(val) if val.isdigit() else 1)

    m_digit = re.search(r'\b([2-9])\b(?!\s*(?:p|k|fps|bit|min|hr|gb|mb))', t)
    if m_digit:
        return int(m_digit.group(1))

    return 1

def deduplicate_movie_candidates(movies):
    def preference_key(m):
        t = m['clean_title']
        has_year = 1 if re.search(r'\b(19\d\d|20\d\d)\b', t) else 0
        return (has_year, m.get('file_size', 0))

    sorted_candidates = sorted(movies, key=preference_key, reverse=True)
    unique_movies = []
    seen = set()

    for m in sorted_candidates:
        title = m['clean_title']
        size_bytes = m.get('file_size', 0)
        size_mb = round(size_bytes / (1024 * 1024))

        base = clean_text(re.sub(r'\b(19\d\d|20\d\d)\b', '', title))
        base = re.sub(r'\b(chapter|part|vol|volume|الجزء)\s*[0-9ivx]+\b', '', base, flags=re.I).strip()
        base = re.sub(r'\b[2-9]\b', '', base).strip()

        part = extract_movie_part(title)
        size_bucket = round(size_mb / 40.0) * 40 if size_mb > 0 else 0

        sig = (base, part, size_bucket)
        if sig in seen:
            continue

        seen.add(sig)
        unique_movies.append(m)

    return unique_movies

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# IN-MEMORY CATALOG CACHE (LIGHTWEIGHT & HIGH-SPEED SEARCH)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_CATALOG_CACHE = {
    'series': [],
    'movies': [],
    'last_refresh': 0.0
}
_CATALOG_LOCK = threading.Lock()

def refresh_catalog_cache(force: bool = False):
    now = time.time()
    if not force and (now - _CATALOG_CACHE['last_refresh']) < 45.0 and _CATALOG_CACHE['movies']:
        return

    with _CATALOG_LOCK:
        # Double-check inside lock
        if not force and (now - _CATALOG_CACHE['last_refresh']) < 45.0 and _CATALOG_CACHE['movies']:
            return

        loaded_series = []
        loaded_movies = []

        mdb = get_mongo_db()
        if mdb is not None:
            col = mdb['media_items']
            # Load series summary
            pipeline = [
                {'$match': {'is_series': 1}},
                {'$group': {
                    '_id': '$series_title',
                    'seasons_count': {'$addToSet': '$season_num'},
                    'episodes_count': {'$sum': 1},
                    'first_id': {'$min': '$id'}
                }}
            ]
            for doc in col.aggregate(pipeline):
                st = doc['_id']
                if st:
                    loaded_series.append({
                        'is_series': 1,
                        'series_title': st,
                        'seasons_count': len(doc.get('seasons_count', [])),
                        'episodes_count': doc.get('episodes_count', 0),
                        'first_id': doc.get('first_id', 0)
                    })

            # Load transferred movies
            m_docs = list(col.find(
                {'is_series': 0, 'target_msg_id': {'$gt': 0}},
                {'id': 1, 'clean_title': 1, 'quality': 1, 'file_size': 1, 'duration': 1, 'target_msg_id': 1}
            ))
            for m in m_docs:
                loaded_movies.append(m)
        else:
            conn = get_connection()
            c = conn.cursor()
            c.execute('''
                SELECT is_series, series_title, COUNT(DISTINCT season_num) as seasons_count, COUNT(*) as episodes_count, MIN(id) as first_id
                FROM media_items
                WHERE is_series = 1
                GROUP BY series_title
            ''')
            loaded_series = [dict(r) for r in c.fetchall()]

            c.execute('''
                SELECT id, clean_title, quality, file_size, duration, target_msg_id
                FROM media_items
                WHERE is_series = 0 AND target_msg_id > 0
            ''')
            loaded_movies = [dict(r) for r in c.fetchall()]
            conn.close()

        # Precompute search metadata on all items for microsecond speed
        for s in loaded_series:
            s_norm = normalize_arabic(clean_text(s['series_title']))
            s['norm'] = s_norm
            s['words'] = [w for w in s_norm.split() if len(w) >= 2]
            s['words_core'] = [strip_ar_prefix(w) for w in s['words']]

        for m in loaded_movies:
            m_norm = normalize_arabic(clean_text(m['clean_title']))
            m['norm'] = m_norm
            m['words'] = [w for w in m_norm.split() if len(w) >= 2]
            m['words_core'] = [strip_ar_prefix(w) for w in m['words']]

        _CATALOG_CACHE['series'] = loaded_series
        _CATALOG_CACHE['movies'] = loaded_movies
        _CATALOG_CACHE['last_refresh'] = time.time()

def get_search_prefixes(q_words: list) -> list:
    prefixes = set()
    for w in q_words:
        if len(w) >= 2:
            prefixes.add(w[:2])
        if len(w) >= 3:
            prefixes.add(w[:3])
            prefixes.add(w[-3:])
        if len(w) >= 4:
            prefixes.add(w[1:4])
    return list(prefixes)

def search_media(query: str, limit: int = 15):
    # Ensure cache is hot
    refresh_catalog_cache()

    # Expand query with Arabic canonical mappings
    terms = [query]
    mapped = map_arabic_query(query)
    for m in mapped:
        if m not in terms:
            terms.append(m)

    scored_series = {}
    scored_movies = {}

    series_catalog = _CATALOG_CACHE['series']
    movies_catalog = _CATALOG_CACHE['movies']

    for term in terms:
        q_clean = clean_text(term)
        q_norm = normalize_arabic(q_clean)
        q_words = [w for w in q_norm.split() if len(w) >= 2]
        if not q_words:
            continue

        prefixes = get_search_prefixes(q_words)

        # 1. Series Candidates
        s_cands = [s for s in series_catalog if any(p in s['norm'] for p in prefixes)]
        for s in s_cands:
            sc = score_candidate(q_norm, q_words, s)
            if sc >= 60.0:
                cur = scored_series.get(s['series_title'])
                if not cur or sc > cur['score']:
                    item_copy = dict(s)
                    item_copy['score'] = sc
                    scored_series[s['series_title']] = item_copy

        # 2. Movie Candidates
        m_cands = [m for m in movies_catalog if any(p in m['norm'] for p in prefixes)]
        for m in m_cands:
            sc = score_candidate(q_norm, q_words, m)
            if sc >= 60.0:
                cur = scored_movies.get(m['id'])
                if not cur or sc > cur['score']:
                    item_copy = dict(m)
                    item_copy['score'] = sc
                    scored_movies[m['id']] = item_copy

    series_list = sorted(scored_series.values(), key=lambda x: x['score'], reverse=True)

    # Intelligent deduplication of duplicate movie uploads
    deduped_movies = deduplicate_movie_candidates(list(scored_movies.values()))

    # Sort franchise movies by tight score tier (3-pt buckets), sequential part, and size
    deduped_movies.sort(key=lambda x: (
        round(x['score'] / 3.0),
        -extract_movie_part(x['clean_title']),
        x.get('file_size', 0)
    ), reverse=True)

    return {"series": series_list[:limit], "movies": deduped_movies[:limit]}

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
