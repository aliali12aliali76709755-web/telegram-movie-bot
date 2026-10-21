import sqlite3
import os
import re

DB_PATH = os.path.join(os.path.dirname(__file__), "movies.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
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
    # Check if columns exist, if not add them
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
    """
    Intelligently parses movie or series details:
    Returns dict: {
        'is_series': bool,
        'series_title': str,
        'season_num': int,
        'episode_num': int,
        'clean_title': str,
        'quality': str
    }
    """
    clean_line = ""
    if caption:
        lines = [l.strip() for l in caption.splitlines() if l.strip()]
        if lines:
            first_line = lines[0]
            # Replace markdown link [Title](url) with just Title
            clean = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', first_line)
            # Remove usernames and urls
            clean = re.sub(r'@\w+', '', clean)
            clean = re.sub(r'https?://\S+', '', clean)
            clean = re.sub(r'[\U0001F1E6-\U0001F1FF]{2}', '', clean)
            clean_line = clean.strip(" -|:")

    if not clean_line and file_name:
        clean_line = os.path.splitext(file_name)[0]
        clean_line = re.sub(r'[\._]', ' ', clean_line)

    # Detect quality
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

    # Detect Series vs Movie
    # Pattern 1: S01E02 or s1e2
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

    # Pattern 2: EP.01 / EP 01 / Episode 01 / الحلقة 01
    ep_match = re.search(r'(?:EP\.?|Episode|الحلقة|حلقة)\s*(\d+)', clean_line, re.I)
    if ep_match:
        e_num = int(ep_match.group(1))
        # Check season in line
        season_match = re.search(r'(?:S|Season|الموسم)\s*(\d+)', clean_line, re.I)
        s_num = int(season_match.group(1)) if season_match else 1
        
        # Strip episode and season tags to get clean series title
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

    # Otherwise: It's a Movie!
    movie_title = clean_line
    # Clean quality tags from movie title
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
    return item_id

def search_media(query: str, limit: int = 20):
    """Search movies or distinct series by title."""
    conn = get_connection()
    cursor = conn.cursor()
    search_term = f"%{query}%"
    
    # 1. Search distinct series
    cursor.execute("""
    SELECT is_series, series_title, COUNT(DISTINCT season_num) as seasons_count, COUNT(*) as episodes_count, MIN(id) as first_id
    FROM media_items
    WHERE is_series = 1 AND (series_title LIKE ? OR raw_caption LIKE ?)
    GROUP BY series_title
    ORDER BY episodes_count DESC LIMIT ?
    """, (search_term, search_term, limit))
    series_rows = [dict(r) for r in cursor.fetchall()]

    # 2. Search movies
    cursor.execute("""
    SELECT * FROM media_items
    WHERE is_series = 0 AND (clean_title LIKE ? OR raw_caption LIKE ?)
    ORDER BY id DESC LIMIT ?
    """, (search_term, search_term, limit))
    movie_rows = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return {"series": series_rows, "movies": movie_rows}

def get_series_seasons(series_title: str):
    """Returns available season numbers for a given series."""
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
    """Returns distinct episodes for a specific season of a series."""
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
    """Marks an item as transferred to the storage channel."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE media_items 
    SET is_transferred = 1, target_msg_id = ?, file_id = ?
    WHERE source_chat_id = ? AND source_msg_id = ?
    """, (target_msg_id, file_id, source_chat_id, source_msg_id))
    conn.commit()
    conn.close()

def get_next_episode(series_title: str, season_num: int, current_ep: int):
    """Finds the next episode in the same season."""
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
    print("Database schema initialized with Series & Movies structure!")
    print(get_stats())
