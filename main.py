import asyncio
import os
import sys
import json
import time
import queue
import socket
import re
from collections import deque
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
import threading
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Ring buffer to capture last 200 stdout/stderr log lines for /logs endpoint
_LOG_BUFFER = deque(maxlen=200)

class LogCapture:
    def __init__(self, original):
        self.original = original
    def write(self, s):
        try:
            self.original.write(s)
            self.original.flush()
        except Exception:
            pass
        if s and s.strip():
            _LOG_BUFFER.append(s.strip())
    def flush(self):
        try:
            self.original.flush()
        except Exception:
            pass
    def reconfigure(self, **kwargs):
        if hasattr(self.original, 'reconfigure'):
            try:
                return self.original.reconfigure(**kwargs)
            except Exception:
                pass
    def __getattr__(self, name):
        return getattr(self.original, name)

sys.stdout = LogCapture(sys.stdout)
sys.stderr = LogCapture(sys.stderr)

# Global event loop reference for cross-thread Telethon async streaming
BOT_ASYNC_LOOP = None

BOT_RUNTIME_STATE = {
    "connected": False,
    "username": "@zxeeabot",
    "id": 8884645024,
    "started_at": None,
    "last_heartbeat": None,
    "last_error": None
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HIGH-SPEED VIDEO STREAMING CACHE & UTILITIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_DOC_METADATA_CACHE = {}
_DOC_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 7200  # 2 hours

def get_cached_media_document(target_msg_id):
    now = time.time()
    with _DOC_CACHE_LOCK:
        if target_msg_id in _DOC_METADATA_CACHE:
            doc, file_size, mime_type, cached_time = _DOC_METADATA_CACHE[target_msg_id]
            if now - cached_time < _CACHE_TTL:
                return doc, file_size, mime_type
            else:
                _DOC_METADATA_CACHE.pop(target_msg_id, None)
    return None

def set_cached_media_document(target_msg_id, doc, file_size, mime_type):
    now = time.time()
    with _DOC_CACHE_LOCK:
        if len(_DOC_METADATA_CACHE) >= 2000:
            oldest = sorted(_DOC_METADATA_CACHE.items(), key=lambda x: x[1][3])[:200]
            for k, _ in oldest:
                _DOC_METADATA_CACHE.pop(k, None)
        _DOC_METADATA_CACHE[target_msg_id] = (doc, file_size, mime_type, now)

def parse_byte_range(range_header: str, file_size: int):
    """
    Parses RFC 7233 Range header.
    Returns: (start, end, is_range_request)
    Handles:
      - bytes=start-end (e.g. bytes=0-1048575)
      - bytes=start-    (e.g. bytes=0- or bytes=2097152-)
      - bytes=-suffix   (e.g. bytes=-1048576)
    """
    if not range_header or not range_header.strip().startswith("bytes="):
        return 0, file_size - 1, False

    raw = range_header.strip()[6:].strip()
    if "," in raw:
        raw = raw.split(",")[0].strip()

    if raw.startswith("-"):
        try:
            suffix = int(raw[1:])
            start = max(0, file_size - suffix)
            end = file_size - 1
            return start, end, True
        except ValueError:
            return 0, file_size - 1, False

    if "-" in raw:
        parts = raw.split("-", 1)
        try:
            start = int(parts[0])
            if parts[1].strip():
                end = min(int(parts[1]), file_size - 1)
            else:
                end = file_size - 1
            return start, end, True
        except ValueError:
            return 0, file_size - 1, False

    return 0, file_size - 1, False

def resolve_media_target(item_id: int):
    """
    Resolves Telegram document metadata for item_id.
    Uses in-memory cache to eliminate redundant database and MTProto queries.
    Returns (target_msg_id, ch_peer, alt_peer, doc, file_size, mime_type)
    """
    import database
    from bot import bot as telethon_bot, MOVIES_PEER, SERIES_PEER, get_channel_peers_for_item

    item = database.get_movie_by_id(item_id)
    if not item or not item.get('target_msg_id'):
        mdb = database.get_mongo_db()
        if mdb:
            doc_entry = mdb['media_items'].find_one({'id': item_id})
            if doc_entry and doc_entry.get('target_msg_id'):
                if not item:
                    item = database.format_movie_for_api(doc_entry)
                item['target_msg_id'] = doc_entry.get('target_msg_id')
                item['is_series'] = doc_entry.get('is_series', 0)
                item['channel_id'] = doc_entry.get('channel_id')
                item['is_cartoon'] = doc_entry.get('is_cartoon', 0)

    if not item or not item.get('target_msg_id'):
        return None, None, None, None, 0, "video/mp4"

    target_msg_id = item['target_msg_id']
    candidate_peers = get_channel_peers_for_item(item)
    ch_peer = candidate_peers[0] if candidate_peers else (MOVIES_PEER if item.get('is_series') == 0 else SERIES_PEER)
    alt_peer = candidate_peers[1] if len(candidate_peers) > 1 else (SERIES_PEER if ch_peer == MOVIES_PEER else MOVIES_PEER)

    # 1. Check in-memory metadata cache (0ms instant lookup)
    cache_key = f"{getattr(ch_peer, 'channel_id', 0)}_{target_msg_id}"
    cached = get_cached_media_document(cache_key) or get_cached_media_document(target_msg_id)
    if cached:
        doc, file_size, mime_type = cached
        return target_msg_id, ch_peer, alt_peer, doc, file_size, mime_type

    # 2. Query Telegram bot if not cached
    if BOT_ASYNC_LOOP is None or not telethon_bot:
        return target_msg_id, ch_peer, alt_peer, None, 0, "video/mp4"

    async def fetch_document():
        for peer in candidate_peers:
            try:
                msg = await telethon_bot.get_messages(peer, ids=target_msg_id)
                if msg and msg.media and hasattr(msg.media, 'document') and msg.media.document:
                    d = msg.media.document
                    return d, d.size, d.mime_type or "video/mp4"
            except Exception as e:
                pass
        return None, 0, "video/mp4"

    try:
        fut = asyncio.run_coroutine_threadsafe(fetch_document(), BOT_ASYNC_LOOP)
        doc, file_size, mime_type = fut.result(timeout=15)
        if doc and file_size > 0:
            set_cached_media_document(cache_key, doc, file_size, mime_type)
        return target_msg_id, ch_peer, alt_peer, doc, file_size, mime_type
    except Exception as e:
        print(f"resolve_media_target fetch error: {e}", flush=True)
        return target_msg_id, ch_peer, alt_peer, None, 0, "video/mp4"

# 1. Health check, Status, Mini App & API HTTP Server
class HealthHandler(BaseHTTPRequestHandler):
    def send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, Range')
        self.send_header('Access-Control-Expose-Headers', 'Content-Range, Content-Length, Accept-Ranges')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_HEAD(self):
        import urllib.parse
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/stream/") or path.startswith("/stream/"):
            try:
                parts = path.strip("/").split("/")
                item_id = int(parts[-1])
                target_msg_id, ch_peer, alt_peer, doc, file_size, mime_type = resolve_media_target(item_id)
                if doc and file_size > 0:
                    range_header = self.headers.get('Range')
                    if range_header:
                        start, end, is_range = parse_byte_range(range_header, file_size)
                        if is_range and start < file_size and start <= end:
                            content_length = end - start + 1
                            self.send_response(206)
                            self.send_header('Content-Type', mime_type or 'video/mp4')
                            self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                            self.send_header('Content-Length', str(content_length))
                            self.send_header('Accept-Ranges', 'bytes')
                            self.send_header('Cache-Control', 'public, max-age=3600, no-transform')
                            self.send_header('Connection', 'keep-alive')
                            self.send_header('Keep-Alive', 'timeout=60, max=100')
                            self.send_cors_headers()
                            self.end_headers()
                            return
                    self.send_response(200)
                    self.send_header('Content-Type', mime_type or 'video/mp4')
                    self.send_header('Content-Length', str(file_size))
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Cache-Control', 'public, max-age=3600, no-transform')
                    self.send_header('Connection', 'keep-alive')
                    self.send_header('Keep-Alive', 'timeout=60, max=100')
                    self.send_cors_headers()
                    self.end_headers()
                    return
            except Exception:
                pass
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def handle_video_stream(self, item_id: int):
        from bot import bot as telethon_bot

        target_msg_id, ch_peer, alt_peer, doc, file_size, mime_type = resolve_media_target(item_id)

        if not target_msg_id:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b'{"error": "Video not found or not yet transferred"}')
            return

        if BOT_ASYNC_LOOP is None or not telethon_bot:
            self.send_response(503)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b'{"error": "Bot streaming service initializing"}')
            return

        if not doc or file_size <= 0:
            self.send_response(404)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b'{"error": "Storage document missing"}')
            return

        # Parse HTTP Range header with full RFC 7233 support
        range_header = self.headers.get('Range')
        start, end, is_range_request = parse_byte_range(range_header, file_size)

        if start >= file_size or start > end:
            self.send_response(416)  # Range Not Satisfiable
            self.send_header('Content-Range', f'bytes */{file_size}')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_cors_headers()
            self.end_headers()
            return

        content_length = end - start + 1

        # High-speed HTTP 206 Partial Content / 200 OK headers
        self.send_response(206 if is_range_request else 200)
        self.send_header('Content-Type', mime_type or 'video/mp4')
        if is_range_request:
            self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
        self.send_header('Content-Length', str(content_length))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'public, max-age=3600, no-transform')
        self.send_header('Connection', 'keep-alive')
        self.send_header('Keep-Alive', 'timeout=60, max=100')
        self.send_cors_headers()
        self.end_headers()

        # MTProto optimal chunk size (512 KB per RPC)
        CHUNK_SIZE = 524288
        num_chunks = max(1, (content_length + CHUNK_SIZE - 1) // CHUNK_SIZE)

        # Dynamic chunk pipelining queue:
        # Pre-allocates burst window (up to 32 chunks = 16MB) to keep forward buffer healthy
        # so mobile players and high-latency connections never experience starvation/buffering.
        PREFETCH_CHUNKS = 32
        chunk_q = queue.Queue(maxsize=PREFETCH_CHUNKS)
        stop_event = threading.Event()

        async def fetch_chunks():
            try:
                bytes_yielded = 0
                async for chunk in telethon_bot.iter_download(
                    doc,
                    offset=start,
                    limit=num_chunks,
                    chunk_size=CHUNK_SIZE,
                    request_size=524288
                ):
                    if stop_event.is_set():
                        break
                    if not chunk:
                        continue

                    needed = content_length - bytes_yielded
                    if needed <= 0:
                        break

                    to_send = chunk[:needed] if len(chunk) > needed else chunk

                    # Non-blocking async queue insertion:
                    # Yields back to BOT_ASYNC_LOOP when queue is full so other tasks are NEVER blocked.
                    while not stop_event.is_set():
                        try:
                            chunk_q.put_nowait(to_send)
                            break
                        except queue.Full:
                            await asyncio.sleep(0.01)

                    bytes_yielded += len(to_send)
                    if bytes_yielded >= content_length:
                        break
            except asyncio.CancelledError:
                pass
            except Exception as err:
                print(f"Telethon iter_download streaming error: {err}", flush=True)
                while not stop_event.is_set():
                    try:
                        chunk_q.put_nowait(err)
                        break
                    except queue.Full:
                        await asyncio.sleep(0.01)
            finally:
                while not stop_event.is_set():
                    try:
                        chunk_q.put_nowait(None)
                        break
                    except queue.Full:
                        try:
                            chunk_q.get_nowait()
                        except queue.Empty:
                            pass
                        await asyncio.sleep(0.01)

        fetch_fut = asyncio.run_coroutine_threadsafe(fetch_chunks(), BOT_ASYNC_LOOP)

        # Optimize TCP socket for instant chunk dispatch
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass

        try:
            while not stop_event.is_set():
                try:
                    item = chunk_q.get(timeout=25)
                except queue.Empty:
                    if fetch_fut.done():
                        break
                    continue

                if item is None:
                    break
                if isinstance(item, Exception):
                    break

                self.wfile.write(item)
                self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError, socket.error):
            # Client disconnected or seeked to new position (standard player behavior)
            pass
        except Exception as e:
            print(f"Streaming write error: {e}", flush=True)
        finally:
            stop_event.set()
            if not fetch_fut.done():
                fetch_fut.cancel()
            while not chunk_q.empty():
                try:
                    chunk_q.get_nowait()
                except queue.Empty:
                    break
        return

    def do_GET(self):
        import urllib.parse
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        # 1. Telegram Mini App Frontend (HTML/SPA)
        if path in ("/", "/app", "/miniapp", "/webapp"):
            html_path = os.path.join(os.path.dirname(__file__), "webapp", "index.html")
            if os.path.exists(html_path):
                with open(html_path, "r", encoding="utf-8") as f:
                    content = f.read()
                body = content.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
                return
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"Mini App template not found.")
                return

        # 1.5. Live Video Stream for In-App Player (HTML5 Range requests)
        elif path.startswith("/api/stream/") or path.startswith("/stream/"):
            try:
                parts = path.strip("/").split("/")
                item_id = int(parts[-1])
            except Exception:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(b'{"error": "Invalid video item ID"}')
                return

            self.handle_video_stream(item_id)
            return

        # 2. Mini App API: List Movies & Series (Paginated, Searchable, Filterable)
        elif path == "/api/movies":
            page = int(params.get('page', ['1'])[0])
            limit = min(50, max(1, int(params.get('limit', ['24'])[0])))
            query = params.get('query', [None])[0] or params.get('q', [None])[0]
            genre = params.get('genre', [None])[0]
            sort = params.get('sort', ['featured'])[0]
            content_type = params.get('type', [None])[0] or params.get('content_type', ['all'])[0]

            try:
                import database
                res = database.get_miniapp_movies(page=page, limit=limit, query=query, genre=genre, sort=sort, content_type=content_type)
                body = json.dumps({"status": "success", **res}, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'public, max-age=60')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # 2.5. Mini App API: Series Catalog & Episodes
        elif path == "/api/series":
            page = int(params.get('page', ['1'])[0])
            limit = min(50, max(1, int(params.get('limit', ['24'])[0])))
            query = params.get('query', [None])[0] or params.get('q', [None])[0]
            try:
                import database
                res = database.get_miniapp_series(page=page, limit=limit, query=query)
                body = json.dumps({"status": "success", **res}, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'public, max-age=60')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        elif path.startswith("/api/series/") and path.endswith("/episodes"):
            try:
                parts = path.strip("/").split("/")
                import urllib.parse
                series_key = urllib.parse.unquote(parts[2])
                import database
                eps = database.get_series_episodes(series_key)
                body = json.dumps({"status": "success", "episodes": eps, "total": len(eps)}, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'public, max-age=120')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # 3. Mini App API: Single Movie Details
        elif path.startswith("/api/movie/"):
            m_id_str = path.replace("/api/movie/", "").strip("/")
            try:
                m_id = int(m_id_str)
                import database
                item = database.get_movie_by_id(m_id)
                if item:
                    body = json.dumps({"status": "success", "movie": item}, ensure_ascii=False).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Cache-Control', 'public, max-age=300')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(b'{"status": "error", "message": "Movie not found"}')
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # 4. Mini App API: Featured Carousel Movies
        elif path == "/api/featured":
            limit = min(12, max(1, int(params.get('limit', ['6'])[0])))
            try:
                import database
                featured = database.get_featured_movies(limit=limit)
                body = json.dumps({"status": "success", "items": featured}, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'public, max-age=120')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # 5. Mini App API: Available Genres
        elif path == "/api/genres":
            try:
                import database
                genres = database.get_genres_summary()
                body = json.dumps({"status": "success", "genres": genres}, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'public, max-age=300')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # 6. Status & Health Check
        elif path in ("/status", "/health"):
            mongo_err = None
            stats = {}
            db_status = "unknown"
            try:
                import database
                stats = database.get_stats()
                db_status = "connected"
            except Exception as e:
                db_status = "failed"
                mongo_err = str(e)

            bot_status = "connected" if BOT_RUNTIME_STATE["connected"] else "disconnected"

            resp = {
                "status": "online",
                "service": "telegram_movie_bot",
                "bot": bot_status,
                "bot_username": BOT_RUNTIME_STATE["username"],
                "bot_id": BOT_RUNTIME_STATE["id"],
                "bot_started_at": BOT_RUNTIME_STATE["started_at"],
                "last_heartbeat": BOT_RUNTIME_STATE["last_heartbeat"],
                "mongodb": db_status,
                "stats": stats
            }
            body = json.dumps(resp, ensure_ascii=False, indent=2).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        # 7. Secure Live Logs
        elif path.startswith("/logs"):
            if params.get('key', [''])[0] != '6641619062':
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "Access Denied"}')
                return

            body = "\n".join(_LOG_BUFFER).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)
            return

        # Default fallback
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b'{"status":"online","service":"telegram_movie_bot","miniapp":"/app"}')

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError, socket.error):
            pass

    def log_message(self, format, *args):
        return  # suppress verbose access logs

class StreamingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def start_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = StreamingHTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"Threading HTTP Server listening on 0.0.0.0:{port} (/status, /logs, /api/stream)...")
    server.serve_forever()

def keep_alive_watchdog():
    """
    Continuous watchdog thread that runs every 8 minutes:
    - Pings public Render URL to keep the container awake 24/7 (Render sleeps after 15m).
    - Uses standard browser User-Agent to avoid Cloudflare rate limiting.
    - Updates heartbeat.
    """
    import urllib.request

    raw_public = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-movie-bot-jno5.onrender.com").rstrip("/")
    public_url = f"{raw_public}/status"
    port = int(os.environ.get("PORT", 10000))
    local_url = f"http://127.0.0.1:{port}/status"

    print("🔄 Keep-Alive Watchdog started. Monitoring every 8 minutes...")
    time.sleep(30)

    while True:
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        BOT_RUNTIME_STATE["last_heartbeat"] = now_str

        # 1. Ping Render Public URL to reset 15-minute inactivity timer
        try:
            req = urllib.request.Request(
                public_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                pass
        except Exception:
            try:
                with urllib.request.urlopen(local_url, timeout=5) as l_resp:
                    pass
            except Exception:
                pass

        time.sleep(480)  # Ping every 8 minutes (Render sleeps at 15m)

async def main():
    global BOT_ASYNC_LOOP
    BOT_ASYNC_LOOP = asyncio.get_running_loop()

    # 0. Initialize Database Schema and Indexes (both MongoDB and SQLite)
    try:
        import database
        database.init_db()
        print("✅ Database schema and indexes initialized.")
    except Exception as e:
        print(f"Notice during init_db: {e}")

    # 1. Start HTTP Server in daemon thread (serves Mini App & APIs)
    t_http = threading.Thread(target=start_http_server, daemon=True)
    t_http.start()

    # 2. Start 1-Minute Keep-Alive Watchdog in daemon thread
    t_keepalive = threading.Thread(target=keep_alive_watchdog, daemon=True)
    t_keepalive.start()

    # 3. Start Background Movie Metadata & Poster Enrichment Worker
    try:
        import metadata_enricher
        metadata_enricher.start_background_enrichment_worker()
        print("🚀 Background movie metadata & poster enrichment daemon launched!")
    except Exception as e:
        print(f"Notice starting metadata enricher: {e}")

    # 4. Run Telegram Bot Service in main event loop
    from bot import main as run_bot
    await run_bot(state_dict=BOT_RUNTIME_STATE)

if __name__ == "__main__":
    asyncio.run(main())
