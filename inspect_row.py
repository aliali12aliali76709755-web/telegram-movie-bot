import sys
sys.stdout.reconfigure(encoding='utf-8')
from database import get_connection

conn = get_connection()
row = conn.cursor().execute("SELECT id, clean_title, source_chat_id, source_msg_id, file_size FROM media_items WHERE series_title LIKE '%Move%' ORDER BY episode_num ASC LIMIT 1").fetchone()
print(dict(row))
