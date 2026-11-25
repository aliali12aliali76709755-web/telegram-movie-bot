import urllib.request
import urllib.parse
import json
import time
import re
import sys
import os
import concurrent.futures

sys.stdout.reconfigure(encoding='utf-8')
dir_path = os.path.dirname(os.path.abspath(__file__))
if dir_path not in sys.path:
    sys.path.append(dir_path)

import database

TMDB_KEYS = [
    '4e44d9029b1270a757cddc766a1bcb63',
    '844dba0bfd8f3a4f3799f6130ef9e335'
]

TMDB_GENRES = {
    28: "أكشن",
    12: "مغامرة",
    16: "رسوم متحركة",
    35: "كوميديا",
    80: "جريمة",
    99: "وثائقي",
    18: "دراما",
    10751: "عائلي",
    14: "فانتازيا",
    36: "تاريخ",
    27: "رعب",
    10402: "موسيقى",
    9648: "غموض",
    10749: "رومانسي",
    878: "خيال علمي",
    10770: "تلفزيوني",
    53: "إثارة",
    10752: "حرب",
    37: "غرب أمريكي"
}

NOISE_PATTERNS = [
    r'^(?:فيلم|فلم|مشاهدة|تحميل)\s+',
    r'\s+(?:مترجم|مدبلج|كامل|اون لاين|اونلاين|حصريا|نسخة اصلية|عربي|اجنبي)\b',
    r'\b(?:الجزء|الموسم)\s+(?:الاول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|الأول|1|2|3|4|5|6|7|8)\b',
    r'\b(?:Part|Season|Vol|Chapter)\s+\d+\b',
    r'\b(?:1080p|720p|480p|4k|2160p|bluray|web-dl|webrip|hdrip|dvdrip|x264|x265|hevc|aac)\b',
    r'\[.*?\]',
    r'\(.*?\)',
    r'@\w+',
    r'https?://\S+',
    r'[\|\-:]+'
]

def clean_movie_search_title(raw_title: str) -> str:
    if not raw_title:
        return ""
    text = raw_title.strip()
    for p in NOISE_PATTERNS:
        text = re.sub(p, ' ', text, flags=re.I)
    
    text = re.sub(r'[\s_.]+', ' ', text).strip()
    return text

_key_idx = 0
def get_tmdb_key():
    global _key_idx
    k = TMDB_KEYS[_key_idx % len(TMDB_KEYS)]
    _key_idx += 1
    return k

def generate_candidate_queries(raw_title: str) -> list:
    """
    Generates an ordered list of search variants from most specific to broader keywords.
    """
    clean_q = clean_movie_search_title(raw_title)
    if not clean_q:
        clean_q = raw_title

    candidates = [clean_q]

    # 1. If English and Arabic mixed, split into separate queries
    en_words = re.findall(r'[a-zA-Z0-9\']+', clean_q)
    ar_words = re.findall(r'[\u0600-\u06FF0-9]+', clean_q)

    if len(en_words) >= 1:
        candidates.append(" ".join(en_words))
    if len(ar_words) >= 1:
        candidates.append(" ".join(ar_words))

    # 2. First 2 to 3 words of clean query (handles sub-titles / suffixes)
    words = clean_q.split()
    if len(words) > 3:
        candidates.append(" ".join(words[:3]))
    if len(words) > 2:
        candidates.append(" ".join(words[:2]))

    # 3. Handle common Arabic variations (e.g. الأبطال الخارقون -> الخارقون)
    if "الابطال الخارقون" in clean_q or "ابطال خارقون" in clean_q:
        candidates.append("الخارقون")
        candidates.append("Incredibles")

    # 4. Hamza normalization
    norm_hamza = re.sub(r'[أإآ]', 'ا', clean_q)
    if norm_hamza != clean_q:
        candidates.append(norm_hamza)
        words_norm = norm_hamza.split()
        if len(words_norm) > 2:
            candidates.append(" ".join(words_norm[:2]))

    # Deduplicate while preserving order
    seen = set()
    result = []
    for c in candidates:
        c_clean = c.strip()
        if c_clean and len(c_clean) >= 2 and c_clean.lower() not in seen:
            seen.add(c_clean.lower())
            result.append(c_clean)

    return result

def query_tmdb_api(query_str: str, year: int = None, language: str = 'ar'):
    key = get_tmdb_key()
    url = f"https://api.themoviedb.org/3/search/movie?api_key={key}&query={urllib.parse.quote(query_str)}&language={language}"
    if year:
        url += f"&year={year}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
            return data.get('results', [])
    except Exception:
        return []

def fetch_from_tmdb(query_title: str):
    """
    Searches TMDB for a movie title using progressive candidate matching.
    Returns parsed metadata dict or None.
    """
    candidates = generate_candidate_queries(query_title)

    # Extract year if present
    year_match = re.search(r'\b(19\d\d|20\d\d)\b', query_title)
    extracted_year = int(year_match.group(1)) if year_match else None

    for q in candidates:
        # First try with year, then without year
        for y in [extracted_year, None]:
            results = query_tmdb_api(q, year=y, language='ar')
            if not results and not re.search(r'[\u0600-\u06FF]', q):
                results = query_tmdb_api(q, year=y, language='en-US')

            if results:
                top = results[0]
                poster_path = top.get('poster_path')
                backdrop_path = top.get('backdrop_path')
                ar_title = top.get('title')
                orig_title = top.get('original_title') or ar_title
                overview = top.get('overview', '')
                rel_date = top.get('release_date', '')
                year = int(rel_date[:4]) if rel_date and len(rel_date) >= 4 and rel_date[:4].isdigit() else extracted_year
                rating = top.get('vote_average')
                vote_count = top.get('vote_count')
                genre_ids = top.get('genre_ids', [])
                genres = [TMDB_GENRES[gid] for gid in genre_ids if gid in TMDB_GENRES]

                # If Arabic overview is empty or poster is missing, fetch English details
                if not overview or not poster_path or not backdrop_path or not genres:
                    try:
                        key = get_tmdb_key()
                        en_url = f"https://api.themoviedb.org/3/movie/{top['id']}?api_key={key}&language=en-US"
                        req_en = urllib.request.Request(en_url, headers={'User-Agent': 'Mozilla/5.0'})
                        with urllib.request.urlopen(req_en, timeout=5) as resp_en:
                            en_data = json.loads(resp_en.read().decode())
                            if not poster_path:
                                poster_path = en_data.get('poster_path')
                            if not backdrop_path:
                                backdrop_path = en_data.get('backdrop_path')
                            if not overview:
                                overview = en_data.get('overview', '')
                            if not genres and en_data.get('genres'):
                                genres = [TMDB_GENRES.get(g['id'], g['name']) for g in en_data['genres']]
                    except Exception:
                        pass

                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""
                backdrop_url = f"https://image.tmdb.org/t/p/w1280{backdrop_path}" if backdrop_path else ""

                return {
                    "tmdb_id": top.get('id'),
                    "arabic_title": ar_title if ar_title != orig_title else "",
                    "clean_title": orig_title or ar_title,
                    "poster_url": poster_url,
                    "backdrop_url": backdrop_url,
                    "description": overview,
                    "release_year": year,
                    "rating": round(float(rating), 1) if rating else None,
                    "vote_count": vote_count,
                    "genres": ", ".join(genres) if genres else "أكشن, دراما"
                }

    return None

def fetch_wikipedia_fallback(title: str):
    clean_q = clean_movie_search_title(title)
    if not clean_q:
        return None
    for q in [clean_q, " ".join(clean_q.split()[:2])]:
        try:
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(q)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'TelegramMovieBot/2.0 (contact@example.com)'})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode())
                thumb = data.get('thumbnail', {}).get('source')
                extract = data.get('extract')
                if thumb or extract:
                    return {
                        "poster_url": thumb or "",
                        "backdrop_url": thumb or "",
                        "description": extract or "",
                        "arabic_title": "",
                        "genres": "دراما, إثارة"
                    }
        except Exception:
            pass
    return None

def enrich_single_movie(movie: dict):
    m_id = movie['id']
    title = movie.get('clean_title') or movie.get('title') or ""
    
    meta = fetch_from_tmdb(title)
    if not meta or not meta.get('poster_url'):
        wiki_meta = fetch_wikipedia_fallback(title)
        if wiki_meta:
            if not meta:
                meta = wiki_meta
            else:
                if not meta.get('poster_url') and wiki_meta.get('poster_url'):
                    meta['poster_url'] = wiki_meta['poster_url']
                    meta['backdrop_url'] = wiki_meta['poster_url']
                if not meta.get('description') and wiki_meta.get('description'):
                    meta['description'] = wiki_meta['description']

    if meta:
        database.update_media_metadata(m_id, meta)
        return m_id, True, meta.get('clean_title') or title, meta.get('poster_url')
    return m_id, False, title, None

def run_enrichment_batch(limit: int = 50, force_all: bool = False):
    conn = database.get_connection()
    cursor = conn.cursor()
    
    if force_all:
        cursor.execute("SELECT id, title, clean_title FROM media_items WHERE is_series = 0 ORDER BY id DESC LIMIT ?", (limit,))
    else:
        cursor.execute("""
        SELECT id, title, clean_title FROM media_items 
        WHERE is_series = 0 AND (poster_url IS NULL OR poster_url = '')
        ORDER BY is_transferred DESC, id DESC LIMIT ?
        """, (limit,))
        
    movies = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    print(f"Starting enrichment batch for {len(movies)} movies...")
    success_count = 0
    t0 = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(enrich_single_movie, m): m for m in movies}
        for future in concurrent.futures.as_completed(futures):
            m_id, success, title, poster = future.result()
            if success:
                success_count += 1
                p_disp = "has poster" if poster else "no poster"
                print(f"  [+] #{m_id} {title[:32]} ({p_disp})")
            else:
                print(f"  [-] #{m_id} {title[:32]} (not found)")

    elapsed = round(time.time() - t0, 1)
    print(f"\nBatch complete: {success_count}/{len(movies)} enriched in {elapsed}s.")
    return success_count

def background_enrichment_loop():
    """
    Continuous background daemon that periodically enriches movies in batches.
    Runs perpetually on Render to keep the entire movie catalog 100% enriched.
    """
    time.sleep(12)
    print("🎬 Background movie metadata enrichment worker started!", flush=True)
    while True:
        try:
            enriched = run_enrichment_batch(limit=25, force_all=False)
            if enriched == 0:
                time.sleep(60)
            else:
                time.sleep(10)
        except Exception as e:
            print(f"Enrichment worker notice: {e}", flush=True)
            time.sleep(15)

def start_background_enrichment_worker():
    import threading
    t = threading.Thread(target=background_enrichment_loop, daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    run_enrichment_batch(limit=limit)
